"""Mutations on the toy network, checked by hand: R1 runs A-B-C at 08:00 (T1) and 08:10 (T2)."""

import math
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from glacies.cities import Routing, ScenarioDefaults
from glacies.model.transit.schema import TABLES
from glacies.routing.network import clock, load_router, parse_clock
from glacies.scenario.mutations import apply, mutations_sha256
from glacies.scenario.schema import Scenario

STOP_A, STOP_C = (12.02, 77.02), (12.04, 77.04)
NO_DETOUR = ScenarioDefaults(detour_factor=1.0, dwell_s=0)


@pytest.fixture
def baseline(city_dir: Path) -> dict[str, pl.DataFrame]:
    return {n: pl.read_parquet(city_dir / "transit" / f"{n}.parquet") for n in TABLES}


def scenario(*mutations: dict[str, Any]) -> Scenario:
    return Scenario.model_validate(
        {"schema_version": 1, "scenario_id": "toy", "title": "Toy", "mutations": list(mutations)}
    )


def headway(**rule: Any) -> dict[str, Any]:
    return {"type": "modify_headway", "route_id": "R1", **rule}


def run(baseline: dict[str, pl.DataFrame], *mutations: dict[str, Any]) -> dict[str, pl.DataFrame]:
    return apply(baseline, scenario(*mutations), NO_DETOUR).tables


def timetable(tables: dict[str, pl.DataFrame], route_id: str = "R1") -> list[tuple[str, ...]]:
    """(trip, stop, arrival, departure, nature) for a route, in canonical order."""
    route = tables["routes"].filter(pl.col("source_route_id") == route_id)["route_idx"]
    trips = tables["trips"].filter(pl.col("route_idx").is_in(route.implode()))
    rows = (
        tables["stop_times"]
        .join(trips.select("trip_idx", "source_trip_id"), on="trip_idx")
        .join(tables["stops"].select("stop_idx", "source_stop_id"), on="stop_idx")
        .sort("trip_idx", "position")
    )
    return [
        (t, s, hms(a), hms(d), n)
        for t, s, a, d, n in rows.select(
            "source_trip_id", "source_stop_id", "arrival", "departure", "time_nature"
        ).iter_rows()
    ]


def hms(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def first_departures(tables: dict[str, pl.DataFrame], route_id: str = "R1") -> list[str]:
    return sorted({row[2] for row in timetable(tables, route_id) if row[1] == "A"})


def assert_same(a: dict[str, pl.DataFrame], b: dict[str, pl.DataFrame]) -> None:
    for name in TABLES:
        assert a[name].equals(b[name]), name


def test_halving_the_headway_adds_a_trip_between_each_pair(
    baseline: dict[str, pl.DataFrame],
) -> None:
    out = run(baseline, headway(headway_factor=0.5))
    # 08:05 is midway; ties between T1 and T2 (both 5 min away) copy the earlier trip's run times.
    assert timetable(out) == [
        ("T1", "A", "08:00:00", "08:00:00", "observed"),
        ("T1", "B", "08:03:00", "08:03:30", "observed"),
        ("T1", "C", "08:06:00", "08:06:00", "observed"),
        ("T1@08:05:00", "A", "08:05:00", "08:05:00", "assumed"),
        ("T1@08:05:00", "B", "08:08:00", "08:08:30", "assumed"),
        ("T1@08:05:00", "C", "08:11:00", "08:11:00", "assumed"),
        ("T2", "A", "08:10:00", "08:10:00", "observed"),
        ("T2", "B", "08:13:00", "08:13:30", "observed"),
        ("T2", "C", "08:16:00", "08:16:00", "observed"),
    ]


def test_doubling_the_headway_keeps_every_other_trip(baseline: dict[str, pl.DataFrame]) -> None:
    assert first_departures(run(baseline, headway(headway_factor=2))) == ["08:00:00"]


def test_scaling_keeps_the_shape_of_an_irregular_timetable(
    baseline: dict[str, pl.DataFrame],
) -> None:
    # Gaps of 10 and 30 min become 5 and 15 min.
    irregular = _with_trip(baseline, "T5", "08:40:00")
    out = run(irregular, headway(headway_factor=0.5))
    assert first_departures(out) == ["08:00:00", "08:05:00", "08:10:00", "08:25:00", "08:40:00"]


def test_regularising_replaces_departures_with_even_ones(
    baseline: dict[str, pl.DataFrame],
) -> None:
    irregular = _with_trip(baseline, "T5", "08:40:00")
    out = run(irregular, headway(headway_secs=900))
    # From the first to the last departure every 15 min; 08:00 exists, so T1 is kept as is.
    assert first_departures(out) == ["08:00:00", "08:15:00", "08:30:00"]
    sources = {row[0] for row in timetable(out)}
    assert sources == {"T1", "T2@08:15:00", "T5@08:30:00"}  # copies of the nearest trip


def test_window_limits_the_change(baseline: dict[str, pl.DataFrame]) -> None:
    irregular = _with_trip(baseline, "T5", "08:40:00")
    out = run(irregular, headway(headway_factor=0.5, window=["08:05", "09:00"]))
    # Only T2 and T5 are inside the window, so only their gap is halved.
    assert first_departures(out) == ["08:00:00", "08:10:00", "08:25:00", "08:40:00"]


NO_CHANGE = [
    {"headway_factor": 1},
    {"headway_secs": 600},  # R1 already runs every 10 min
    {"headway_factor": 0.5, "window": ["06:00", "07:00"]},  # no R1 trips in the window
]


@pytest.mark.parametrize("rule", NO_CHANGE)
def test_a_change_to_the_current_timetable_returns_the_baseline(
    baseline: dict[str, pl.DataFrame], rule: dict[str, Any]
) -> None:
    assert_same(run(baseline, headway(**rule)), baseline)


def test_remove_route_drops_its_trips_and_patterns(baseline: dict[str, pl.DataFrame]) -> None:
    out = apply(baseline, scenario({"type": "remove_route", "route_id": "R1"}), NO_DETOUR)
    assert out.changes[0].trips_removed == 2
    assert timetable(out.tables) == []
    assert out.tables["trips"]["trip_idx"].to_list() == [0]  # dense after renumbering
    assert out.tables["patterns"]["pattern_idx"].to_list() == [0]
    assert out.tables["routes"].equals(baseline["routes"])  # route indices stay stable


def test_add_route_runs_at_the_given_speed(baseline: dict[str, pl.DataFrame]) -> None:
    add = {
        "type": "add_route",
        "route_id": "NEW",
        "name": "New line",
        "stops": ["A", "B", "C"],
        "headway_secs": 600,
        "span": ["07:00", "07:20"],
        "speed_kmh": 36,  # 10 m/s
        "dwell_secs": 30,
    }
    out = apply(baseline, scenario(add), ScenarioDefaults(detour_factor=1.2, dwell_s=0))
    tables = out.tables
    stops = {r["source_stop_id"]: r for r in tables["stops"].iter_rows(named=True)}
    # Seconds at 10 m/s over 1.2x the straight line; rounded once, on the running total.
    ab = 1.2 * _metres(stops["A"], stops["B"]) / 10
    bc = 1.2 * _metres(stops["B"], stops["C"]) / 10
    at_b, at_c = (parse_clock("07:00") + math.floor(x + 0.5) for x in (ab, ab + 30 + bc))
    assert timetable(tables, "NEW")[:3] == [
        ("NEW:0:07:00:00", "A", "07:00:00", "07:00:00", "assumed"),
        ("NEW:0:07:00:00", "B", hms(at_b), hms(at_b + 30), "assumed"),
        ("NEW:0:07:00:00", "C", hms(at_c), hms(at_c), "assumed"),
    ]
    assert out.changes[0].trips_added == 6  # 07:00, 07:10, 07:20 in both directions
    back = [r for r in timetable(tables, "NEW") if r[0] == "NEW:1:07:00:00"]
    assert [r[1] for r in back] == ["C", "B", "A"]

    route = tables["routes"].filter(pl.col("source_route_id") == "NEW").row(0, named=True)
    assert (route["route_idx"], route["mode"], route["route_type"]) == (
        baseline["routes"].height,
        "bus",
        3,
    )
    feed = tables["feeds"].filter(pl.col("feed_idx") == route["feed_idx"]).row(0, named=True)
    assert (feed["dataset"], feed["snapshot"]) == ("scenario", "toy")
    assert feed["checksum_sha256"] == mutations_sha256(scenario(add))
    assert tables["stops"].equals(baseline["stops"])


def test_mutations_apply_in_order_and_are_reported(baseline: dict[str, pl.DataFrame]) -> None:
    out = apply(
        baseline,
        scenario(headway(headway_factor=0.5), {"type": "remove_route", "route_id": "R3"}),
        NO_DETOUR,
    )
    assert [(c.mutation, c.type, c.trips_removed, c.trips_added) for c in out.changes] == [
        (1, "modify_headway", 0, 1),
        (2, "remove_route", 1, 0),
    ]


def test_same_scenario_writes_identical_parquet(
    baseline: dict[str, pl.DataFrame], tmp_path: Path
) -> None:
    mutations = (
        headway(headway_factor=0.5),
        {**_ADD_FEEDER, "route_id": "F"},
        {"type": "remove_route", "route_id": "R3"},
    )
    for run_dir in ("a", "b"):
        (tmp_path / run_dir).mkdir()
        for name, frame in run(baseline, *mutations).items():
            frame.write_parquet(tmp_path / run_dir / f"{name}.parquet")
    for name in TABLES:
        a = (tmp_path / "a" / f"{name}.parquet").read_bytes()
        assert a == (tmp_path / "b" / f"{name}.parquet").read_bytes(), name


def test_titles_do_not_change_the_mutation_hash() -> None:
    a = scenario(headway(headway_factor=0.5))
    b = a.model_copy(update={"title": "Another title", "description": "x"})
    assert mutations_sha256(a) == mutations_sha256(b)
    assert mutations_sha256(a) != mutations_sha256(scenario(headway(headway_factor=0.4)))


# --- the router on the scenario network (phase doc kickoff tests) ---------------------------


def plan_arrival(city_dir: Path, tables: dict[str, pl.DataFrame], at: str) -> str | None:
    """Earliest arrival at C from A, routing on ``tables`` written over the toy network."""
    for name, frame in tables.items():
        frame.write_parquet(city_dir / "transit" / f"{name}.parquet")
    journeys = load_router(city_dir, Routing(), "EPSG:32643").plan(STOP_A, STOP_C, parse_clock(at))
    return clock(min(j.arrival for j in journeys)) if journeys else None


def test_halving_the_headway_shortens_the_wait(
    city_dir: Path, baseline: dict[str, pl.DataFrame]
) -> None:
    assert plan_arrival(city_dir, baseline, "08:01") == "08:16"  # waits for T2 at 08:10
    halved = run(baseline, headway(headway_factor=0.5))
    assert plan_arrival(city_dir, halved, "08:01") == "08:11"  # the new 08:05 trip


def test_removing_the_only_route_makes_the_destination_unreachable(
    city_dir: Path, baseline: dict[str, pl.DataFrame]
) -> None:
    removed = run(baseline, {"type": "remove_route", "route_id": "R1"})
    assert plan_arrival(city_dir, removed, "07:59") is None


def test_an_added_route_is_used_by_the_router(
    city_dir: Path, baseline: dict[str, pl.DataFrame]
) -> None:
    added = run(baseline, {"type": "remove_route", "route_id": "R1"}, _ADD_FEEDER)
    assert plan_arrival(city_dir, added, "07:59") is not None


_ADD_FEEDER = {
    "type": "add_route",
    "route_id": "FEEDER",
    "stops": ["A", "C"],
    "headway_secs": 600,
    "span": ["08:00", "09:00"],
    "speed_kmh": 20,
}


def _metres(a: dict[str, Any], b: dict[str, Any]) -> float:
    rad = math.pi / 180
    h = (
        math.sin((b["lat"] - a["lat"]) * rad / 2) ** 2
        + math.cos(a["lat"] * rad)
        * math.cos(b["lat"] * rad)
        * math.sin((b["lon"] - a["lon"]) * rad / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def _with_trip(tables: dict[str, pl.DataFrame], trip_id: str, at: str) -> dict[str, pl.DataFrame]:
    """A copy of T1 departing at ``at``, as if the feed had it (Observed)."""
    trips, stop_times = tables["trips"], tables["stop_times"]
    t1 = trips.filter(pl.col("source_trip_id") == "T1")
    new_idx = trips.height
    shift = parse_clock(at) - parse_clock("08:00")
    trip = t1.with_columns(
        pl.lit(new_idx, pl.UInt32).alias("trip_idx"), pl.lit(trip_id).alias("source_trip_id")
    )
    times = stop_times.filter(pl.col("trip_idx") == t1["trip_idx"][0]).with_columns(
        pl.lit(new_idx, pl.UInt32).alias("trip_idx"),
        pl.col("arrival") + shift,
        pl.col("departure") + shift,
    )
    return tables | {
        "trips": pl.concat([trips, trip]),
        "stop_times": pl.concat([stop_times, times]),
    }


REPO = Path(__file__).parent.parent
BENGALURU = REPO / "data" / "processed" / "bengaluru" / "transit"


@pytest.mark.slow
@pytest.mark.skipif(not (BENGALURU / "trips.parquet").is_file(), reason="needs the built city")
def test_bengaluru_scenarios_apply_and_no_change_is_identity() -> None:
    from glacies.cities import load_city
    from glacies.scenario.schema import load_scenario

    base = {n: pl.read_parquet(BENGALURU / f"{n}.parquet") for n in TABLES}
    defaults = load_city(REPO / "cities" / "bengaluru" / "city.toml").scenario
    no_change = scenario({"type": "modify_headway", "route_id": "1066", "headway_factor": 1})
    assert_same(apply(base, no_change, defaults).tables, base)
    for path in sorted((REPO / "scenarios" / "bengaluru").glob("*.json")):
        out = apply(base, load_scenario(path), defaults).tables
        assert out["trips"]["trip_idx"].to_list() == list(range(out["trips"].height))
        assert out["stops"].equals(base["stops"])
