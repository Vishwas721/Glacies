"""The RQ job and worker that run simulations (PRD §47).

One worker runs one simulation at a time: a run uses every core and gigabytes of memory. RQ on
Windows offers only ``SimpleWorker`` (no fork; it cannot kill a running job), so every job
starts the run as a child process (`glacies.jobs.child`) and ends it itself on cancel or
timeout. The same code runs on Linux, so CI tests what Windows runs.
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import IO

from redis import Redis
from rq import Queue, SimpleWorker, get_current_job
from rq.timeouts import TimerDeathPenalty

from glacies.config import Settings
from glacies.jobs.state import STAGES, Progress, Simulation, Status, Store, now

QUEUE = "glacies"
POLL_S = 0.5  # how often a running job checks for a cancel request
LOG_NAME = "log.txt"
log = logging.getLogger(__name__)


class _Worker(SimpleWorker):
    # SimpleWorker's default timeout uses SIGALRM, which Windows lacks.
    death_penalty_class = TimerDeathPenalty


def enqueue(redis: Redis, sim: Simulation, timeout_s: int) -> None:
    Queue(QUEUE, connection=redis).enqueue(
        "glacies.jobs.worker.run_simulation",
        sim.id,
        timeout_s,
        job_id=sim.id,
        job_timeout=timeout_s + 300,  # a backstop: the job enforces timeout_s itself
        result_ttl=3600,
        failure_ttl=86400,
    )


def cancel_queued(redis: Redis, sim_id: str) -> bool:
    """Take a job off the queue if no worker has started it; True if it was removed."""
    removed = Queue(QUEUE, connection=redis).remove(sim_id)
    return bool(removed)


def run_simulation(sim_id: str, timeout_s: int) -> str:
    """The RQ job: run the simulation's child process and keep its record current."""
    job = get_current_job()
    if job is None:
        raise RuntimeError("run_simulation runs inside an RQ worker")
    command = [sys.executable, "-m", "glacies.jobs.child"]
    return execute(Store(job.connection), sim_id, command, timeout_s).value


def execute(store: Store, sim_id: str, command: Sequence[str], timeout_s: float) -> Status:
    """Run ``command + [city, scenario_file]`` and follow it to a final status."""
    sim = store.get(sim_id)
    if sim is None:
        raise LookupError(f"no simulation {sim_id!r}")
    if sim.status.finished:  # cancelled while queued
        return sim.status
    sim.status, sim.started_at = Status.RUNNING, now()
    store.save(sim)

    log_path = Path(sim.scenario_file).parent / LOG_NAME
    with log_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            [*command, sim.city, sim.scenario_file],
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
        )
        lines = _reader(process.stdout)
        deadline = time.monotonic() + timeout_s
        status: Status | None = None
        while status is None:
            try:
                line = lines.get(timeout=POLL_S)
            except queue.Empty:
                line = ""
            if line is None:  # stdout closed: the child is ending
                code = process.wait()
                status = Status.COMPLETED if code == 0 and sim.result_key else Status.FAILED
                if status is Status.FAILED:
                    sim.error = _tail(log_path) or f"the run exited with code {code}"
            elif line:
                _apply(sim, json.loads(line))
                store.save(sim)
            if status is None and store.cancel_requested(sim_id):
                _stop(process)
                status = Status.CANCELLED
            elif status is None and time.monotonic() > deadline:
                _stop(process)
                status, sim.error = Status.FAILED, f"timed out after {timeout_s:.0f} s"
    sim.status, sim.finished_at = status, now()
    store.save(sim)
    return status


def _reader(stream: IO[str] | None) -> queue.Queue[str | None]:
    """Lines of ``stream`` in a queue, then ``None``; the job loop never blocks on the pipe."""
    out: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        if stream is not None:
            for line in stream:
                out.put(line.strip())
        out.put(None)

    threading.Thread(target=pump, daemon=True).start()
    return out


def _apply(sim: Simulation, event: dict[str, object]) -> None:
    kind = event.get("event")
    if kind == "stage":
        message = str(event["message"])
        index = next((i for i, s in enumerate(STAGES) if message.startswith(s)), None)
        sim.progress = Progress(
            stage=STAGES[index] if index is not None else None,
            stage_index=index,
            message=message,
        )
    elif kind == "chunk":
        done, total = event["done"], event["total"]
        if isinstance(done, int) and isinstance(total, int):
            sim.progress.done, sim.progress.total = done, total
    elif kind == "done":
        sim.result_key = str(event["result_key"])
        sim.cached = bool(event["cached"])


def _stop(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _tail(path: Path, lines: int = 20) -> str:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return "\n".join(text.splitlines()[-lines:])


def serve(settings: Settings, *, burst: bool = False) -> None:
    """Run the worker until stopped (or, with ``burst``, until the queue is empty)."""
    redis = Redis.from_url(settings.redis_url)
    redis.ping()
    _Worker([Queue(QUEUE, connection=redis)], connection=redis).work(burst=burst)
