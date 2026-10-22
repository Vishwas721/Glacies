"""The simulation job loop against stand-in child processes: progress, failure, cancel, timeout."""

import sys
import textwrap
import threading
import time
from pathlib import Path

import psutil
import pytest
from fakeredis import FakeStrictRedis

from glacies.jobs.state import Simulation, Status, Store, now
from glacies.jobs.worker import execute


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
