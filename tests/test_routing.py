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


def router(city_dir: Path, **overrides: float) -> Router:
    routing = Routing().model_copy(update=overrides)
    return load_router(city_dir, routing, "EPSG:32643")


def test_journey_between_two_points(city_dir: Path) -> None:
    r = router(city_dir)

    journeys = r.plan(STOP_A, STOP_C, parse_clock("07:59"))

    assert len(journeys) == 1
    (journey,) = journeys
    assert (clock(journey.arrival), journey.transfers) == ("08:06", 0)
    assert r.describe(journey) == ["08:00 ride 10 from Stop A to Stop C, arrive 08:06"]


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
