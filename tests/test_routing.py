"""The router built from processed toy-city data: transfers, access walks, journeys."""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from glacies.cities import Routing, load_city
from glacies.cli import app
from glacies.routing.network import (
    Router,
    RouterError,
    clock,
    load_router,
    parse_clock,
    walk_seconds,
)

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()
STOP_A, STOP_C = (12.02, 77.02), (12.04, 77.04)  # toy stops A and C sit on walk nodes 1 and 5


@pytest.fixture
def city_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Toyville with transit and walk networks built by the real pipeline."""
    monkeypatch.setenv("GLACIES_CITIES_DIR", str(FIXTURES / "cities"))
    monkeypatch.setenv("GLACIES_CITY", "toyville")
    monkeypatch.setenv("GLACIES_DATA_DIR", str(tmp_path / "data"))
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    feed = shutil.copytree(FIXTURES / "gtfs" / "toy_feed", downloads / "toy_feed")
    osm = shutil.copy(FIXTURES / "osm" / "toy.osm", downloads / "toy.osm")
    for name, path in (("toy_gtfs", feed), ("toy_osm", osm)):
        result = runner.invoke(app, ["ingest", "register", name, str(path), "--snapshot", "v1"])
        assert result.exit_code == 0, result.output
    for stage in ("transit", "walk"):
        result = runner.invoke(app, ["build", stage])
        assert result.exit_code == 0, result.output
    return tmp_path / "data" / "processed" / "toyville"


def router(city_dir: Path, **overrides: object) -> Router:
    routing = Routing().model_copy(update=overrides)
    return load_router(city_dir, routing, "EPSG:32643")


def test_journey_between_two_points(city_dir: Path) -> None:
    r = router(city_dir)

    journeys = r.plan(STOP_A, STOP_C, parse_clock("07:59"))

    assert len(journeys) == 1
    (journey,) = journeys
    assert (clock(journey.arrival), journey.transfers) == ("08:06", 0)
    assert r.describe(journey) == ["08:00 ride 10 from Stop A to Stop C, arrive 08:06"]


def test_boarding_time_applies_to_stops_of_the_configured_mode(city_dir: Path) -> None:
    metro = router(city_dir, boarding_time_s={"metro": 240})
    seconds = metro.timetable.boarding_times()
    stop_ids = metro.stops.sort("stop_idx")["source_stop_id"].to_list()

    # The metro route M1 (trip T4) serves platform P1 and Stop D; bus stops need no time.
    assert {stop_ids[i]: int(seconds[i]) for i in seconds.nonzero()[0]} == {"P1": 240, "D": 240}


def test_boarding_time_delays_the_journey(city_dir: Path) -> None:
    # Reaching Stop A just before 08:00 and needing 5 min to board: T1 (08:00) is missed and
    # T2 (08:10, arriving 08:16) is taken.
    slow = router(city_dir, boarding_time_s={"bus": 300})

    (journey,) = slow.plan(STOP_A, STOP_C, parse_clock("07:59"))

    assert clock(journey.arrival) == "08:16"


def test_access_walks_follow_the_network(city_dir: Path) -> None:
    r = router(city_dir)

    at_a = r.access(*STOP_A)
    wide = r.access(*STOP_A, max_m=2_500)

    assert at_a.stops.tolist() == [r.stops.filter(r.stops["source_stop_id"] == "A")["stop_idx"][0]]
    assert at_a.seconds.tolist() == [0]
    assert at_a.snap_m == pytest.approx(0, abs=0.01)
    # B is 0.01 deg east then 0.01 deg north of A along the streets: about 2.2 km.
    names = dict(r.stops.select("stop_idx", "source_stop_id").iter_rows())
    pairs = zip(wide.stops.tolist(), wide.seconds.tolist(), strict=True)
    reached = {names[s]: sec for s, sec in pairs}
    # P1 is the metro platform 1.5 km from the main walk network, attached next to A.
    assert set(reached) == {"A", "B", "P1"}
    assert 2_150 / 1.2 < reached["B"] < 2_250 / 1.2
    assert 1_400 / 1.2 < reached["P1"] < 1_600 / 1.2


def test_transfers_are_symmetric_walks_within_the_limit(city_dir: Path) -> None:
    assert router(city_dir).transfer_count == 0  # toy stops are over 400 m apart

    wide = router(city_dir, max_transfer_walk_m=2_500)

    assert wide.transfer_count > 0
    assert wide.transfer_count % 2 == 0  # every walk exists in both directions


def test_points_far_from_any_stop_are_reported(city_dir: Path) -> None:
    with pytest.raises(RouterError, match="no stop within 800 m"):
        router(city_dir).plan((12.095, 77.095), STOP_C, parse_clock("08:00"))


def test_missing_processed_data_is_reported(tmp_path: Path) -> None:
    with pytest.raises(RouterError, match="build-city"):
        load_router(tmp_path, Routing(), "EPSG:32643")


def test_clock_helpers() -> None:
    assert parse_clock("08:30") == 30_600
    assert parse_clock("24:05:30") == 86_730
    assert clock(86_730) == "24:05"
    for bad in ("8", "08:60", "aa:bb"):
        with pytest.raises(RouterError):
            parse_clock(bad)


def test_walk_seconds_round_up() -> None:
    import numpy as np

    assert walk_seconds(np.array([0.0, 1.0, 120.0]), 1.2).tolist() == [0, 1, 100]


def test_city_config_routing_is_used() -> None:
    config = load_city(FIXTURES / "cities" / "toyville" / "city.toml")

    assert config.routing.max_rounds == 4


def test_route_command(city_dir: Path) -> None:
    result = runner.invoke(app, ["route", "12.02,77.02", "12.04,77.04", "--at", "07:59"])

    assert result.exit_code == 0, result.output
    assert "arrive 08:06 · 7 min · 0 transfer(s)" in result.output
    assert "[Simulated]" in result.output
    assert "08:00 ride 10 from Stop A to Stop C, arrive 08:06" in result.output


def test_route_command_reports_bad_input(city_dir: Path) -> None:
    bad_point = runner.invoke(app, ["route", "north", "12.04,77.04", "--at", "08:00"])
    bad_time = runner.invoke(app, ["route", "12.02,77.02", "12.04,77.04", "--at", "8"])

    assert bad_point.exit_code == 1
    assert "invalid point" in bad_point.output
    assert bad_time.exit_code == 1
    assert "invalid time" in bad_time.output


SANITY_HEADER = (
    "id,origin,origin_stop,origin_lat,origin_lon,destination,destination_stop,"
    "destination_lat,destination_lon,departure,expected_min,source,review_note\n"
)


def test_validate_routing_compares_with_expected_times(city_dir: Path, tmp_path: Path) -> None:
    sanity = tmp_path / "sanity.csv"
    sanity.write_text(
        SANITY_HEADER
        + "1,A,Stop A,12.02,77.02,C,Stop C,12.04,77.04,07:59,7,fixture,\n"
        + "2,A,Stop A,12.02,77.02,C,Stop C,12.04,77.04,07:59,30,fixture,check me\n"
        + "3,Far,nowhere,12.095,77.095,C,Stop C,12.04,77.04,07:59,10,fixture,\n",
        encoding="utf-8",
    )
    out = tmp_path / "routing.md"

    result = runner.invoke(app, ["validate", "routing", "--sanity", str(sanity), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert "1 of 3 pairs within tolerance" in result.output
    report = out.read_text(encoding="utf-8")
    assert "| 1 | A → C | 07:59 | 7 min | 7 min | 0 | 7 min | ✅ |" in report
    assert "| 2 | A → C | 07:59 | 30 min | 7 min | 0 | 7 min | ❌ | check me |" in report
    assert "no stop within 800 m" in report


def test_bench_routing_writes_a_report(city_dir: Path, tmp_path: Path) -> None:
    import polars as pl

    (city_dir / "zones").mkdir()
    pl.DataFrame({"population": [10.0, 0.0, 5.0]}).write_parquet(
        city_dir / "zones" / "zones.parquet"
    )
    out = tmp_path / "bench.md"

    result = runner.invoke(app, ["bench", "routing", "--samples", "4", "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert "one-to-one plan" in result.output
    text = out.read_text(encoding="utf-8")
    assert "one origin per populated zone\n(2 zones)" in text
    assert "| range search, 120 departures 07:30-09:29 | 1 |" in text


def test_parallel_range_search_matches_serial(city_dir: Path) -> None:
    import numpy as np

    tt = router(city_dir).timetable
    departures = np.arange(parse_clock("07:50"), parse_clock("08:20"), 60, dtype=np.uint32)
    origins = [(np.array([s], dtype=np.uint32), np.array([0], dtype=np.uint32)) for s in range(6)]

    parallel = tt.range_arrivals_many(origins, departures, 4, 60)
    serial = [tt.range_arrivals(s, sec, departures, 4, 60) for s, sec in origins]

    for p, s in zip(parallel, serial, strict=True):
        assert np.array_equal(p, s)
