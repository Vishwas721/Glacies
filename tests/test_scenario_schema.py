import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from glacies.cli import app
from glacies.model.transit.build import FeedInput, build_transit
from glacies.scenario.schema import (
    AddRoute,
    ModifyHeadway,
    RemoveRoute,
    Scenario,
    ScenarioError,
    json_schema_text,
    load_scenario,
    resolve,
)
from glacies.validate.gtfs.report import Thresholds
from tests.gtfs_edit import copy_toy_feed

REPO = Path(__file__).parent.parent
TUESDAY = date(2026, 10, 13)


def toy_tables(tmp_path: Path, copies: int = 1) -> dict[str, pl.DataFrame]:
    inputs = [
        FeedInput(
            dataset=f"toy{i}",
            snapshot="v1",
            checksum_sha256=str(i) * 64,
            directory=copy_toy_feed(tmp_path / f"feed{i}"),
            route_number_pattern=r"^\S+",
        )
        for i in range(copies)
    ]
    return build_transit(
        inputs, service_date=TUESDAY, bbox=(77.0, 12.0, 77.1, 12.1), thresholds=Thresholds()
    ).tables


@pytest.fixture
def tables(tmp_path: Path) -> dict[str, pl.DataFrame]:
    return toy_tables(tmp_path)


def scenario(*mutations: dict[str, Any], **fields: Any) -> Scenario:
    data = {
        "schema_version": 1,
        "scenario_id": "toy",
        "title": "Toy",
        "mutations": list(mutations),
        **fields,
    }
    return Scenario.model_validate(data)


ADD = {
    "type": "add_route",
    "route_id": "NEW",
    "stops": ["A", "B", "C"],
    "headway_secs": 600,
    "span": ["07:00", "09:00"],
    "speed_kmh": 20,
}
HEADWAY = {"type": "modify_headway", "route_id": "R1"}


def test_mutations_are_parsed_by_type() -> None:
    s = scenario(
        {"type": "remove_route", "route_id": "R1"},
        {"type": "modify_headway", "route_id": "R2", "headway_factor": 0.5},
        ADD,
    )
    assert [type(m) for m in s.mutations] == [RemoveRoute, ModifyHeadway, AddRoute]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"type": "close_road", "route_id": "R1"}, "does not match any of the expected tags"),
        ({"type": "remove_route", "route_id": "R1", "extra": 1}, "Extra inputs"),
        ({"type": "modify_headway", "route_id": "R1"}, "exactly one of"),
        (
            {"type": "modify_headway", "route_id": "R1", "headway_factor": 0.5, "headway_secs": 60},
            "exactly one of",
        ),
        ({"type": "modify_headway", "route_id": "R1", "headway_factor": 0}, "greater than 0"),
        (
            {**HEADWAY, "headway_secs": 60, "window": ["9:00", "8:00"]},
            "must end after it starts",
        ),
        ({**ADD, "span": ["7am", "09:00"]}, "invalid time"),
        ({**ADD, "stops": ["A"]}, "at least 2"),
        ({**ADD, "stops": ["A", "B", "A"]}, "appears twice"),
        ({**ADD, "mode": "hovercraft"}, "unknown mode"),
        ({**ADD, "one_way": True, "return_stops": ["C", "A"]}, "one_way"),
        ({k: v for k, v in ADD.items() if k != "speed_kmh"}, "speed_kmh"),
    ],
)
def test_invalid_mutations_are_rejected(mutation: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        scenario(mutation)


def test_scenario_needs_a_mutation_and_a_clean_id() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        scenario()
    with pytest.raises(ValueError, match="pattern"):
        scenario(ADD, scenario_id="Has Spaces")


def test_add_route_runs_both_ways_unless_one_way() -> None:
    both = AddRoute.model_validate(ADD)
    assert both.directions() == [["A", "B", "C"], ["C", "B", "A"]]
    explicit = AddRoute.model_validate({**ADD, "return_stops": ["C", "A"]})
    assert explicit.directions() == [["A", "B", "C"], ["C", "A"]]
    assert AddRoute.model_validate({**ADD, "one_way": True}).directions() == [["A", "B", "C"]]


def write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_checks_version_and_file_name(tmp_path: Path) -> None:
    good = {"schema_version": 1, "scenario_id": "toy", "title": "T", "mutations": [ADD]}
    assert load_scenario(write(tmp_path / "toy.json", good)).scenario_id == "toy"
    # The $schema editor hint is accepted and ignored.
    load_scenario(write(tmp_path / "toy.json", {"$schema": "x.json", **good}))
    with pytest.raises(ScenarioError, match="schema_version 2 is not supported"):
        load_scenario(write(tmp_path / "toy.json", {**good, "schema_version": 2}))
    with pytest.raises(ScenarioError, match="does not match the file name"):
        load_scenario(write(tmp_path / "other.json", good))
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(ScenarioError, match=r"bad\.json"):
        load_scenario(tmp_path / "bad.json")


def test_resolve_maps_ids_to_baseline_indices(tables: dict[str, pl.DataFrame]) -> None:
    resolved = resolve(
        scenario(
            {"type": "remove_route", "route_id": "R1"},
            {"type": "modify_headway", "route_id": "R3", "headway_secs": 300, "feed": "toy0"},
            ADD,
        ),
        tables,
    )
    routes = tables["routes"]
    stops = tables["stops"]
    for source_id, idx in resolved.route_idx.items():
        assert routes.filter(pl.col("route_idx") == idx)["source_route_id"][0] == source_id
    assert sorted(resolved.stop_idx) == ["A", "B", "C"]
    for source_id, idx in resolved.stop_idx.items():
        assert stops.filter(pl.col("stop_idx") == idx)["source_stop_id"][0] == source_id


def problems(s: Scenario, tables: dict[str, pl.DataFrame]) -> str:
    with pytest.raises(ScenarioError) as info:
        resolve(s, tables)
    return str(info.value)


def test_resolve_reports_every_problem_at_once(tables: dict[str, pl.DataFrame]) -> None:
    message = problems(
        scenario(
            {"type": "remove_route", "route_id": "R9"},
            {"type": "remove_route", "route_id": "R1"},
            {"type": "modify_headway", "route_id": "R1", "headway_factor": 0.5},
            {"type": "remove_route", "route_id": "R2", "feed": "nope"},
            {**ADD, "route_id": "R3", "stops": ["A", "Z", "S1"]},
            {"type": "remove_route", "route_id": "R3"},
        ),
        tables,
    )
    assert "mutation 1 (remove_route): route 'R9' is not in the baseline network" in message
    assert "mutation 3 (modify_headway): route 'R1' was already removed" in message
    assert "mutation 4 (remove_route): unknown feed 'nope'" in message
    assert "mutation 5 (add_route): route 'R3' already exists" in message
    assert "stop 'Z' is not in the baseline network" in message
    assert "stop 'S1' is a station, not a boarding point" in message
    assert "mutation 6 (remove_route): route 'R3' is added by this scenario" in message


def test_resolve_rejects_new_ids_that_repeat_within_the_scenario(
    tables: dict[str, pl.DataFrame],
) -> None:
    assert "route 'NEW' already exists" in problems(scenario(ADD, ADD), tables)


def test_resolve_rejects_a_route_without_trips(tables: dict[str, pl.DataFrame]) -> None:
    r3 = tables["routes"].filter(pl.col("source_route_id") == "R3")["route_idx"][0]
    no_r3 = {**tables, "trips": tables["trips"].filter(pl.col("route_idx") != r3)}
    message = problems(scenario({"type": "remove_route", "route_id": "R3"}), no_r3)
    assert "has no trips on the service day" in message


def test_ids_in_two_feeds_need_the_feed(tmp_path: Path) -> None:
    two = toy_tables(tmp_path, copies=2)
    message = problems(scenario({"type": "remove_route", "route_id": "R1"}, ADD), two)
    assert "route 'R1' is in several feeds; set 'feed'" in message
    assert "stop 'A' is in several feeds" in message
    resolved = resolve(
        scenario(
            {"type": "remove_route", "route_id": "R1", "feed": "toy1"}, {**ADD, "feed": "toy1"}
        ),
        two,
    )
    feed_of = dict(zip(two["routes"]["route_idx"], two["routes"]["feed_idx"], strict=True))
    assert feed_of[resolved.route_idx["R1"]] == 1


def test_exported_json_schema_is_current() -> None:
    exported = (REPO / "schemas" / "scenario.schema.json").read_text(encoding="utf-8")
    assert exported == json_schema_text(), "run `glacies scenario schema` to refresh it"


SCENARIO_FILES = sorted((REPO / "scenarios").glob("*/*.json"))


@pytest.mark.parametrize("path", SCENARIO_FILES, ids=lambda p: p.name)
def test_committed_scenarios_parse(path: Path) -> None:
    assert load_scenario(path).mutations


def test_schema_command_writes_the_schema(tmp_path: Path) -> None:
    out = tmp_path / "scenario.schema.json"
    result = CliRunner().invoke(app, ["scenario", "schema", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == json_schema_text()
