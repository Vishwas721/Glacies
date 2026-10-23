"""Simulations through the API: queueing, cancelling and, end to end, a real run on Toyville."""

import json
from pathlib import Path

import pytest
from fakeredis import FakeStrictRedis
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue

from glacies.api.app import create_app
from glacies.config import Settings
from glacies.jobs.worker import QUEUE, _Worker
from tests import toy_city
from tests.test_api_network import assert_labelled

SCENARIO = {
    "schema_version": 1,
    "scenario_id": "faster_r1",
    "title": "Run R1 twice as often",
    "mutations": [{"type": "modify_headway", "route_id": "R1", "headway_factor": 0.5}],
}


def make_client(redis: Redis) -> TestClient:
    client = TestClient(create_app(Settings(), redis=redis))
    created = client.post("/api/cities/toyville/scenarios", json=SCENARIO)
    assert created.status_code == 201, created.text
    return client


@pytest.fixture
def redis() -> Redis:
    return FakeStrictRedis()


@pytest.fixture
def client(city_dir: Path, redis: Redis) -> TestClient:
    (city_dir / "accessibility" / "baseline").mkdir(parents=True)
    (city_dir / "accessibility" / "baseline" / "manifest.json").write_text("{}", encoding="utf-8")
    return make_client(redis)


def start(client: TestClient) -> str:
    response = client.post(
        "/api/simulations", json={"city": "toyville", "scenario_id": "faster_r1"}
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    job_id: str = response.json()["job_id"]
    return job_id


def test_queueing_snapshots_the_scenario(client: TestClient, redis: Redis, tmp_path: Path) -> None:
    job_id = start(client)

    sim = client.get(f"/api/simulations/{job_id}").json()
    snapshot = Path(sim["scenario_file"])
    assert (sim["status"], sim["city"], sim["scenario_id"]) == ("queued", "toyville", "faster_r1")
    assert snapshot == tmp_path / "data" / "simulations" / job_id / "faster_r1.json"
    assert json.loads(snapshot.read_text(encoding="utf-8"))["title"] == SCENARIO["title"]
    assert Queue(QUEUE, connection=redis).job_ids == [job_id]
    assert [s["id"] for s in client.get("/api/simulations").json()] == [job_id]
    assert client.get("/api/simulations", params={"city": "elsewhere"}).json() == []

    # Editing the scenario afterwards does not change what the queued run uses.
    client.patch("/api/cities/toyville/scenarios/faster_r1", json={"title": "Changed"})
    assert json.loads(snapshot.read_text(encoding="utf-8"))["title"] == SCENARIO["title"]


def test_cancelling_a_queued_run_takes_it_off_the_queue(client: TestClient, redis: Redis) -> None:
    job_id = start(client)

    cancelled = client.post(f"/api/simulations/{job_id}/cancel").json()

    assert cancelled["status"] == "cancelled"
    assert Queue(QUEUE, connection=redis).job_ids == []
    assert client.post(f"/api/simulations/{job_id}/cancel").status_code == 409


def test_results_wait_for_completion(client: TestClient) -> None:
    job_id = start(client)

    for part in ("metrics", "accessibility", "crowding", "flows"):
        assert client.get(f"/api/simulations/{job_id}/{part}").status_code == 409


def test_unknown_things_are_not_found(client: TestClient) -> None:
    def post(city: str, scenario: str) -> int:
        body = {"city": city, "scenario_id": scenario}
        return client.post("/api/simulations", json=body).status_code

    assert post("toyville", "nope") == 404
    assert post("nowhere", "faster_r1") == 404
    assert client.get("/api/simulations/sim_missing").status_code == 404


def test_a_city_without_a_baseline_cannot_simulate(city_dir: Path, redis: Redis) -> None:
    client = make_client(redis)

    response = client.post(
        "/api/simulations", json={"city": "toyville", "scenario_id": "faster_r1"}
    )

    assert response.status_code == 409


def test_redis_being_down_is_explained(city_dir: Path) -> None:
    down = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=1)
    client = TestClient(create_app(Settings(), redis=down))

    response = client.get("/api/simulations")

    assert response.status_code == 503
    assert "docker compose up -d" in response.json()["detail"]


def test_a_simulation_runs_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, redis: Redis
) -> None:
    """The real worker job and child process on Toyville with demand and assignment."""
    city = toy_city.build(tmp_path, monkeypatch)
    toy_city.assign(city)
    client = make_client(redis)
    job_id = start(client)

    _Worker([Queue(QUEUE, connection=redis)], connection=redis).work(burst=True)

    sim = client.get(f"/api/simulations/{job_id}").json()
    assert sim["status"] == "completed", sim["error"]
    assert sim["progress"]["stage"] == "comparison"
    assert (city / "results" / sim["result_key"] / "comparison" / "metrics.parquet").is_file()
    metrics = client.get(f"/api/simulations/{job_id}/metrics").json()["rows"]
    names = {r["metric"] for r in metrics}
    assert "Assignment: waiting per transit trip" in names
    assert {r["nature"] for r in metrics} == {"simulated"}
    access = client.get(f"/api/simulations/{job_id}/accessibility").json()
    assert access["est_jobs_share_delta"] is not None
    assert len(access["est_jobs_share_delta"]) == len(access["zone_idx"])
    for part in ("accessibility", "crowding", "flows"):
        response = client.get(f"/api/simulations/{job_id}/{part}")
        assert response.status_code == 200, (part, response.text)
        assert_labelled(response.json())
    # The same result is reachable by its key, as the baseline is by name.
    by_key = client.get(f"/api/cities/toyville/results/{sim['result_key']}/accessibility").json()
    assert by_key == access
    # What changed: R1 runs twice as often, drawn through its three stops.
    changed = client.get(f"/api/simulations/{job_id}/changes").json()
    [route] = changed["routes"]
    assert (route["kind"], route["route_id"], route["name"]) == ("modified", "R1", "10")
    assert route["trips_added"] > 0
    assert [len(line) for line in route["coordinates"]] == [3]
    assert route["mutation_idx"] == 0
    assert route["boardings_scenario"] is not None
    assert_labelled(changed)
    assert client.get("/api/cities/toyville/results/baseline/changes").status_code == 404
    # Model checks: bands of peak bus segments cover every segment once.
    checked = client.get(f"/api/simulations/{job_id}/checks").json()
    bands = checked["bus_load_bands"]
    assert [b["band"] for b in bands] == ["under 0.5", "0.5-1.0", "1.0-1.5", "over 1.5"]
    assert sum(b["segment_share"] for b in bands) in (0, pytest.approx(1.0))
    assert_labelled(checked)
    # Finished results are listed from disk, so they outlive the Redis records.
    listed = client.get("/api/cities/toyville/results").json()
    assert [(r["key"], r["scenario_id"], r["compared"]) for r in listed] == [
        (sim["result_key"], "faster_r1", True)
    ]


def test_the_child_reads_the_engine_version_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An edit to the source tree during a run changes the version; the comparison must still
    find the result the run wrote under the version it started with."""
    from glacies.jobs import child
    from glacies.scenario import compare, runner
    from glacies.scenario.runner import EngineVersions

    toy_city.build(tmp_path, monkeypatch)
    path = tmp_path / "faster_r1.json"
    path.write_text(json.dumps(SCENARIO), encoding="utf-8")
    calls = iter(range(100))

    def drifting() -> EngineVersions:
        return EngineVersions(
            glacies="t", glacies_raptor="t", git_commit=f"c{next(calls)}", git_dirty=False
        )

    for module in (child, runner, compare):
        monkeypatch.setattr(module, "engine_versions", drifting)

    assert child.main(["toyville", str(path)]) == 0
