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
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue, SimpleWorker, get_current_job
from rq.timeouts import TimerDeathPenalty

from glacies.config import Settings
from glacies.jobs.state import STAGES, Progress, Simulation, Status, Store, now

QUEUE = "glacies"
POLL_S = 0.5  # how often a running job checks for a cancel request
LOG_NAME = "log.txt"
RECONNECT_S = 300.0  # how long the worker waits for Redis to come back before giving up
QUICK_END_S = 60.0  # a work loop ending sooner than this after starting counts as failing fast
QUICK_ENDS = 5  # this many in a row is a bug, not a dropped connection: stop
INTERRUPTED = (
    "interrupted: the worker stopped while this ran (for example, the computer ran low on "
    "memory); start the simulation again"
)
log = logging.getLogger(__name__)


class _Worker(SimpleWorker):
    # SimpleWorker's default timeout uses SIGALRM, which Windows lacks.
    death_penalty_class = TimerDeathPenalty
    stopping = False

    def handle_warm_shutdown_request(self) -> None:
        self.stopping = True  # Ctrl+C: the loop's end is wanted, not a lost connection
        super().handle_warm_shutdown_request()  # type: ignore[no-untyped-call]


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


def interrupt_orphans(store: Store) -> list[str]:
    """Fail the simulations a stopped worker left as running; their ids.

    A worker killed mid-run (out of memory, a closed window) never writes a final status, so
    the record would say "running" forever. Only one worker runs (see the module docstring),
    so when one starts, nothing can still be running.
    """
    orphans = [sim for sim in store.list() if sim.status is Status.RUNNING]
    for sim in orphans:
        sim.status, sim.finished_at, sim.error = Status.FAILED, now(), INTERRUPTED
        store.save(sim)
    return [sim.id for sim in orphans]


def serve(settings: Settings, *, burst: bool = False) -> None:
    """Run the worker until stopped (or, with ``burst``, until the queue is empty)."""
    redis = Redis.from_url(settings.redis_url)
    redis.ping()

    def work() -> bool:
        for sim_id in interrupt_orphans(Store(redis)):
            log.warning("%s was left running by a stopped worker; marked failed", sim_id)
        worker = _Worker([Queue(QUEUE, connection=redis)], connection=redis)
        try:
            worker.work(burst=burst)
        except RedisError as exc:  # raised, not returned, when Redis is down rather than slow
            log.warning("lost Redis: %s", exc)
            return False
        return burst or worker.stopping

    supervise(work, lambda: wait_for_redis(redis, RECONNECT_S))


def supervise(
    work: Callable[[], bool],
    reconnect: Callable[[], bool],
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Run ``work`` again whenever it ends without being asked to (it returns False).

    RQ's work loop returns when a Redis call times out (as when the computer sleeps) and
    ``serve`` turns a lost connection it raises into a return too; either used to end the
    worker for good. ``reconnect``
    waits for Redis and says whether it came back. A loop that keeps ending quickly while
    Redis answers is a bug, not a dropped connection, and stops the worker.
    """
    quick_ends = 0
    while True:
        started = clock()
        if work():
            return
        quick_ends = quick_ends + 1 if clock() - started < QUICK_END_S else 0
        if quick_ends >= QUICK_ENDS:
            raise RuntimeError(f"the worker loop ended {QUICK_ENDS} times in a row; see the log")
        log.warning("the worker loop ended (lost Redis?); reconnecting")
        if not reconnect():
            raise RuntimeError(f"Redis did not come back within {RECONNECT_S:.0f} s")


def wait_for_redis(
    redis: Redis, limit_s: float, sleep: Callable[[float], None] = time.sleep
) -> bool:
    """Ping Redis until it answers, waiting longer each time; False after ``limit_s``."""
    waited, pause = 0.0, 1.0
    while True:
        try:
            redis.ping()
        except RedisError:
            if waited >= limit_s:
                return False
            sleep(pause)
            waited, pause = waited + pause, min(pause * 2, 30.0)
        else:
            return True
