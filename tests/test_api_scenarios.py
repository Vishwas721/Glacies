"""Scenario CRUD on Toyville: repository files are read-only, the user's are editable."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from glacies.api.app import create_app
from glacies.api.routers.scenarios import merge_patch
from glacies.config import Settings

URL = "/api/cities/toyville/scenarios"


def scenario(scenario_id: str = "faster_r1", **changes: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "title": "Run R1 twice as often",
        "mutations": [{"type": "modify_headway", "route_id": "R1", "headway_factor": 0.5}],
        **changes,
    }


@pytest.fixture
def client(city_dir: Path, tmp_path: Path) -> TestClient:
    repository = tmp_path / "scenarios" / "toyville"
    repository.mkdir(parents=True)
    shipped = scenario(
        "drop_r1", title="Remove R1", mutations=[{"type": "remove_route", "route_id": "R1"}]
    )
    (repository / "drop_r1.json").write_text(json.dumps(shipped), encoding="utf-8")
    return TestClient(create_app(Settings(scenarios_dir=tmp_path / "scenarios")))


def test_create_read_list_and_delete(client: TestClient, tmp_path: Path) -> None:
    created = client.post(URL, json=scenario())

    assert created.status_code == 201
    assert created.json()["source"] == "user"
    assert created.json()["editable"] is True
    saved = tmp_path / "data" / "scenarios" / "toyville" / "faster_r1.json"
    assert json.loads(saved.read_text(encoding="utf-8"))["mutations"][0]["headway_factor"] == 0.5
    assert client.get(f"{URL}/faster_r1").json()["scenario"]["title"] == "Run R1 twice as often"
    listed = {s["scenario_id"]: (s["source"], s["mutation_types"]) for s in client.get(URL).json()}
    assert listed == {
        "drop_r1": ("repository", ["remove_route"]),
        "faster_r1": ("user", ["modify_headway"]),
    }

    assert client.delete(f"{URL}/faster_r1").status_code == 204
    assert not saved.exists()
    assert client.get(f"{URL}/faster_r1").status_code == 404


def test_saved_files_are_what_the_cli_reads(client: TestClient, tmp_path: Path) -> None:
    from glacies.scenario.schema import load_scenario

    client.post(URL, json=scenario())

    loaded = load_scenario(tmp_path / "data" / "scenarios" / "toyville" / "faster_r1.json")
    assert loaded.scenario_id == "faster_r1"


def test_references_are_checked_against_the_baseline_network(client: TestClient) -> None:
    bad = scenario(mutations=[{"type": "remove_route", "route_id": "R9"}])

    response = client.post(URL, json=bad)

    assert response.status_code == 422
    assert "route 'R9' is not in the baseline network" in response.json()["detail"]


def test_schema_errors_are_rejected(client: TestClient) -> None:
    assert client.post(URL, json=scenario(mutations=[])).status_code == 422
    assert client.post(URL, json=scenario(scenario_id="Bad Id")).status_code == 422


def test_ids_are_unique_across_repository_and_user(client: TestClient) -> None:
    client.post(URL, json=scenario())

    assert client.post(URL, json=scenario()).status_code == 409
    assert client.post(URL, json=scenario("drop_r1")).status_code == 409


def test_patch_merges_and_rechecks(client: TestClient) -> None:
    client.post(URL, json=scenario())

    patched = client.patch(
        f"{URL}/faster_r1",
        json={"title": "Every 2 minutes", "description": "test"},
        headers={"Content-Type": "application/merge-patch+json"},
    )
    unknown_route = client.patch(
        f"{URL}/faster_r1", json={"mutations": [{"type": "remove_route", "route_id": "R9"}]}
    )
    renamed = client.patch(f"{URL}/faster_r1", json={"scenario_id": "other"})
    invalid = client.patch(f"{URL}/faster_r1", json={"title": ""})

    assert patched.status_code == 200
    assert (patched.json()["scenario"]["title"], patched.json()["scenario"]["description"]) == (
        "Every 2 minutes",
        "test",
    )
    assert [r.status_code for r in (unknown_route, renamed, invalid)] == [422, 422, 422]
    assert client.get(f"{URL}/faster_r1").json()["scenario"]["title"] == "Every 2 minutes"


def test_repository_scenarios_are_read_only(client: TestClient) -> None:
    assert client.get(f"{URL}/drop_r1").json()["editable"] is False
    assert client.patch(f"{URL}/drop_r1", json={"title": "x"}).status_code == 403
    assert client.delete(f"{URL}/drop_r1").status_code == 403


@pytest.mark.parametrize("scenario_id", ["..%5Cdrop_r1", "%2E%2E%5Cdrop_r1", "DROP_R1", "nope"])
def test_odd_or_unknown_ids_are_not_found(client: TestClient, scenario_id: str) -> None:
    assert client.get(f"{URL}/{scenario_id}").status_code == 404
    assert client.delete(f"{URL}/{scenario_id}").status_code == 404


def test_merge_patch_follows_rfc_7396() -> None:
    target = {"a": "b", "c": {"d": "e", "f": "g"}}

    assert merge_patch(target, {"a": "z", "c": {"f": None}}) == {"a": "z", "c": {"d": "e"}}
    assert merge_patch(target, {"c": ["x"]}) == {"a": "b", "c": ["x"]}
    assert merge_patch(target, ["whole"]) == ["whole"]
