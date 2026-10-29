"""The simulation job loop against stand-in child processes: progress, failure, cancel, timeout."""

import sys
import textwrap
import threading
import time
from pathlib import Path

import psutil
import pytest
from fakeredis import FakeStrictRedis
from redis.exceptions import TimeoutError as RedisTimeoutError

from glacies.jobs.state import Simulation, Status, Store, now
from glacies.jobs.worker import (
    INTERRUPTED,
    QUICK_END_S,
    QUICK_ENDS,
    execute,
    interrupt_orphans,
    supervise,
    wait_for_redis,
)


@pytest.fixture
def store() -> Store:
    return Store(FakeStrictRedis())


def child(tmp_path: Path, body: str) -> list[str]:
    """A stand-in for `glacies.jobs.child`: a script that gets <city> <scenario> like it."""
    script = tmp_path / "child.py"
    script.write_text(
        "import json, os, sys, time\n"
        "def emit(**e): print(json.dumps(e), flush=True)\n"
        "open(os.path.join(os.path.dirname(sys.argv[2]), 'pid'), 'w').write(str(os.getpid()))\n"
        + textwrap.dedent(body),
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def simulation(store: Store, tmp_path: Path) -> Simulation:
    folder = tmp_path / "sim_1"
    folder.mkdir()
    (folder / "toy.json").write_text("{}", encoding="utf-8")
    sim = Simulation(
        id="sim_1",
        city="toyville",
        scenario_id="toy",
        scenario_file=str(folder / "toy.json"),
        created_at=now(),
    )
    store.create(sim)
    return sim


def test_a_run_reports_its_stages_and_result(store: Store, tmp_path: Path) -> None:
    sim = simulation(store, tmp_path)
    command = child(
        tmp_path,
        """
        emit(event="stage", message="applying mutations")
        emit(event="stage", message="travel-time matrix: 3 of 10 origins")
        emit(event="chunk", done=2, total=4)
        emit(event="stage", message="comparison")
        emit(event="done", result_key="abc", cached=False)
        """,
    )

    status = execute(store, sim.id, command, timeout_s=60)

    after = store.get(sim.id)
    assert after is not None
    assert status is Status.COMPLETED
    assert (after.status, after.result_key, after.cached) == (Status.COMPLETED, "abc", False)
    assert (after.progress.stage, after.progress.stage_index) == ("comparison", 4)
    assert after.started_at is not None
    assert after.finished_at is not None


def test_progress_is_visible_while_running(store: Store, tmp_path: Path) -> None:
    sim = simulation(store, tmp_path)
    command = child(
        tmp_path,
        """
        emit(event="stage", message="travel-time matrix: all origins (full run)")
        emit(event="chunk", done=1, total=3)
        time.sleep(2)
        emit(event="done", result_key="abc", cached=True)
        """,
    )
    seen: list[Simulation] = []

    def watch() -> None:
        time.sleep(1)
        current = store.get(sim.id)
        assert current is not None
        seen.append(current)

    watcher = threading.Thread(target=watch)
    watcher.start()
    execute(store, sim.id, command, timeout_s=60)
    watcher.join()

    [during] = seen
    assert during.status is Status.RUNNING
    assert (during.progress.stage, during.progress.done, during.progress.total) == (
        "travel-time matrix",
        1,
        3,
    )


def test_a_crash_fails_with_the_end_of_the_log(store: Store, tmp_path: Path) -> None:
    sim = simulation(store, tmp_path)
    command = child(
        tmp_path, "sys.stderr.write('ScenarioError: route R9 is unknown\\n')\nsys.exit(1)\n"
    )

    assert execute(store, sim.id, command, timeout_s=60) is Status.FAILED
    after = store.get(sim.id)
    assert after is not None
    assert after.error is not None
    assert "route R9 is unknown" in after.error


def test_exiting_without_a_result_is_a_failure(store: Store, tmp_path: Path) -> None:
    sim = simulation(store, tmp_path)

    assert execute(store, sim.id, child(tmp_path, "pass\n"), timeout_s=60) is Status.FAILED


def test_cancelling_ends_the_child_process(store: Store, tmp_path: Path) -> None:
    sim = simulation(store, tmp_path)
    command = child(tmp_path, 'emit(event="stage", message="accessibility")\ntime.sleep(120)\n')

    def cancel() -> None:
        time.sleep(1.5)
        store.request_cancel(sim.id)

    threading.Thread(target=cancel).start()
    started = time.monotonic()
    status = execute(store, sim.id, command, timeout_s=60)

    assert status is Status.CANCELLED
    assert time.monotonic() - started < 30
    pid = int((tmp_path / "sim_1" / "pid").read_text(encoding="utf-8"))
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


def test_a_run_past_the_timeout_is_stopped(store: Store, tmp_path: Path) -> None:
    sim = simulation(store, tmp_path)

    status = execute(store, sim.id, child(tmp_path, "time.sleep(120)\n"), timeout_s=1)

    after = store.get(sim.id)
    assert after is not None
    assert status is Status.FAILED
    assert after.error == "timed out after 1 s"


def test_a_job_cancelled_while_queued_never_starts(store: Store, tmp_path: Path) -> None:
    sim = simulation(store, tmp_path)
    store.save(sim.model_copy(update={"status": Status.CANCELLED}))

    status = execute(store, sim.id, child(tmp_path, "pass\n"), timeout_s=60)

    assert status is Status.CANCELLED
    assert not (tmp_path / "sim_1" / "pid").exists()


def test_store_lists_newest_first_and_by_city(store: Store) -> None:
    for i, city in enumerate(["a", "b", "a"]):
        store.create(
            Simulation(id=f"s{i}", city=city, scenario_id="x", scenario_file="x", created_at=now())
        )

    assert [s.id for s in store.list()] == ["s2", "s1", "s0"]
    assert [s.id for s in store.list("a")] == ["s2", "s0"]
    assert store.get("missing") is None


def test_runs_left_by_a_stopped_worker_are_marked_interrupted(store: Store, tmp_path: Path) -> None:
    running = simulation(store, tmp_path)
    running.status, running.started_at = Status.RUNNING, now()
    store.save(running)
    queued = running.model_copy(update={"id": "sim_2", "status": Status.QUEUED})
    done = running.model_copy(update={"id": "sim_3", "status": Status.COMPLETED})
    store.create(queued)
    store.create(done)

    assert interrupt_orphans(store) == ["sim_1"]

    after = store.get("sim_1")
    assert after is not None
    assert (after.status, after.error) == (Status.FAILED, INTERRUPTED)
    assert after.finished_at is not None
    # A queued run will still be picked up; a finished one keeps its result.
    assert {sim.id: sim.status for sim in store.list()} == {
        "sim_1": Status.FAILED,
        "sim_2": Status.QUEUED,
        "sim_3": Status.COMPLETED,
    }
    assert interrupt_orphans(store) == []


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_the_worker_starts_again_after_losing_redis() -> None:
    clock, ends = Clock(), iter([False, False, True])  # timed out twice, then Ctrl+C
    calls: list[str] = []

    def work() -> bool:
        calls.append("work")
        clock.now += 3600  # ran an hour each time
        return next(ends)

    def reconnect() -> bool:
        calls.append("reconnect")
        return True

    supervise(work, reconnect, clock)

    assert calls == ["work", "reconnect", "work", "reconnect", "work"]


def test_the_worker_gives_up_when_redis_stays_away() -> None:
    with pytest.raises(RuntimeError, match="did not come back"):
        supervise(lambda: False, lambda: False, Clock())


def test_a_loop_that_keeps_ending_at_once_stops_the_worker() -> None:
    clock, runs = Clock(), []

    def work() -> bool:
        runs.append(1)
        clock.now += QUICK_END_S / 2
        return False

    with pytest.raises(RuntimeError, match=f"{QUICK_ENDS} times in a row"):
        supervise(work, lambda: True, clock)
    assert len(runs) == QUICK_ENDS


class FlakyRedis:
    def __init__(self, failures: int) -> None:
        self.failures = failures

    def ping(self) -> bool:
        if self.failures:
            self.failures -= 1
            raise RedisTimeoutError("Timeout connecting to server")
        return True


def test_waiting_for_redis_backs_off_until_it_answers() -> None:
    pauses: list[float] = []
    assert wait_for_redis(FlakyRedis(3), 60, pauses.append)  # type: ignore[arg-type]
    assert pauses == [1, 2, 4]
    pauses.clear()
    assert not wait_for_redis(FlakyRedis(100), 60, pauses.append)  # type: ignore[arg-type]
    assert sum(pauses[:-1]) < 60 <= sum(pauses)
