import shutil
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from glacies.cli import app
from tests.zone_inputs import write_buildings, write_landcover, write_population

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the CLI at the toy city and a temporary data directory."""
    monkeypatch.setenv("GLACIES_CITIES_DIR", str(FIXTURES / "cities"))
    monkeypatch.setenv("GLACIES_CITY", "toyville")
    monkeypatch.setenv("GLACIES_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def toy_gtfs(env: Path) -> Path:
    target = env / "downloads" / "toy_gtfs"
    shutil.copytree(FIXTURES / "toy_gtfs", target)
    return target


def test_list_shows_sources_and_status(env: Path) -> None:
    result = runner.invoke(app, ["ingest", "list"])

    assert result.exit_code == 0, result.output
    assert "toy_gtfs" in result.output
    assert "UNVERIFIED" in result.output  # toy_population is verified = false


def test_register_then_list_and_verify(env: Path, toy_gtfs: Path) -> None:
    registered = runner.invoke(
        app, ["ingest", "register", "toy_gtfs", str(toy_gtfs), "--snapshot", "20260907"]
    )
    assert registered.exit_code == 0, registered.output
    assert "archived 3 files" in registered.output
    assert not toy_gtfs.exists()
    assert (env / "data" / "raw" / "toyville" / "toy_gtfs" / "20260907" / "manifest.json").is_file()

    listed = runner.invoke(app, ["ingest", "list"])
    assert "20260907" in listed.output

    verified = runner.invoke(app, ["ingest", "verify"])
    assert verified.exit_code == 0, verified.output
    assert "1 snapshot(s) OK" in verified.output


def test_register_copy_keeps_source(env: Path, toy_gtfs: Path) -> None:
    result = runner.invoke(
        app, ["ingest", "register", "toy_gtfs", str(toy_gtfs), "--snapshot", "v1", "--copy"]
    )

    assert result.exit_code == 0, result.output
    assert toy_gtfs.exists()


def test_register_same_content_twice_reports_existing(env: Path, toy_gtfs: Path) -> None:
    args = ["ingest", "register", "toy_gtfs", str(toy_gtfs), "--copy"]
    runner.invoke(app, [*args, "--snapshot", "v1"])

    result = runner.invoke(app, [*args, "--snapshot", "v2"])

    assert result.exit_code == 0, result.output
    assert "already archived" in result.output


def test_verify_fails_on_tampering(env: Path, toy_gtfs: Path) -> None:
    runner.invoke(app, ["ingest", "register", "toy_gtfs", str(toy_gtfs), "--snapshot", "v1"])
    stops = env / "data" / "raw" / "toyville" / "toy_gtfs" / "v1" / "data" / "stops.txt"
    stops.write_text("tampered\n", encoding="utf-8")

    result = runner.invoke(app, ["ingest", "verify"])

    assert result.exit_code == 1
    assert "checksum mismatch: stops.txt" in result.output


def test_errors_are_reported_without_traceback(env: Path) -> None:
    result = runner.invoke(
        app, ["ingest", "register", "nope", str(env / "missing"), "--snapshot", "v1"]
    )

    assert result.exit_code == 1
    assert "unknown dataset 'nope'" in result.output
    assert "Traceback" not in result.output


def test_unknown_city_is_reported(env: Path) -> None:
    result = runner.invoke(app, ["ingest", "list", "--city", "atlantis"])

    assert result.exit_code == 1
    assert "city config not found" in result.output


@pytest.fixture
def archived_feed(env: Path) -> Path:
    feed = env / "downloads" / "toy_feed"
    shutil.copytree(FIXTURES / "gtfs" / "toy_feed", feed)
    result = runner.invoke(app, ["ingest", "register", "toy_gtfs", str(feed), "--snapshot", "v1"])
    assert result.exit_code == 0, result.output
    return env / "data" / "processed" / "toyville" / "reports" / "toy_gtfs" / "v1"


def test_validate_gtfs_writes_reports(archived_feed: Path) -> None:
    result = runner.invoke(app, ["validate", "gtfs", "toy_gtfs"])

    assert result.exit_code == 0, result.output
    assert "0 errors, 0 warnings, 1 info" in result.output
    assert "coverage ratio vs reference: 50% to 100%" in result.output
    assert (archived_feed / "gtfs_validation.json").is_file()
    assert (
        (archived_feed / "gtfs_validation.md")
        .read_text(encoding="utf-8")
        .startswith("# GTFS validation")
    )


def test_validate_gtfs_fail_on(env: Path, archived_feed: Path) -> None:
    stops = env / "data" / "raw" / "toyville" / "toy_gtfs" / "v1" / "data" / "stops.txt"
    stops.write_text(stops.read_text(encoding="utf-8") + "Q,Lonely,12.06,77.06,,\n", "utf-8")

    lenient = runner.invoke(app, ["validate", "gtfs", "toy_gtfs", "--fail-on", "error"])
    strict = runner.invoke(app, ["validate", "gtfs", "toy_gtfs", "--fail-on", "warning"])

    assert lenient.exit_code == 0, lenient.output
    assert strict.exit_code == 1


def test_validate_gtfs_requires_archived_gtfs(env: Path) -> None:
    missing = runner.invoke(app, ["validate", "gtfs", "toy_gtfs"])
    wrong_kind = runner.invoke(app, ["validate", "gtfs", "toy_population"])

    assert missing.exit_code == 1
    assert "no archived snapshot" in missing.output
    assert wrong_kind.exit_code == 1
    assert "not GTFS" in wrong_kind.output


def test_build_transit(env: Path, archived_feed: Path) -> None:
    result = runner.invoke(app, ["build", "transit"])

    assert result.exit_code == 0, result.output
    assert "3 trips" in result.output
    out = env / "data" / "processed" / "toyville" / "transit"
    assert (out / "stop_times.parquet").is_file()
    assert (out / "manifest.json").is_file()


def test_build_transit_refuses_feeds_with_errors(env: Path, archived_feed: Path) -> None:
    trips = env / "data" / "raw" / "toyville" / "toy_gtfs" / "v1" / "data" / "trips.txt"
    trips.write_text(trips.read_text(encoding="utf-8") + "R9,WK,T9,,0\n", "utf-8")

    refused = runner.invoke(app, ["build", "transit"])
    forced = runner.invoke(app, ["build", "transit", "--force"])

    assert refused.exit_code == 1
    assert "unknown_route" in refused.output
    assert forced.exit_code == 0, forced.output


def test_build_walk(env: Path, archived_feed: Path) -> None:
    assert runner.invoke(app, ["build", "transit"]).exit_code == 0
    osm = env / "downloads" / "toy.osm"
    shutil.copy(FIXTURES / "osm" / "toy.osm", osm)
    registered = runner.invoke(app, ["ingest", "register", "toy_osm", str(osm), "--snapshot", "v1"])
    assert registered.exit_code == 0, registered.output

    result = runner.invoke(app, ["build", "walk"])

    assert result.exit_code == 0, result.output
    assert "9 nodes, 8 edges" in result.output
    out = env / "data" / "processed" / "toyville" / "walk"
    links = pl.read_parquet(out / "stop_links.parquet")
    assert links.height == 5  # boarding points A, B, C, D, P1
    assert (out / "BUILD_REPORT.md").is_file()


def test_build_walk_needs_transit_and_osm(env: Path) -> None:
    no_osm = runner.invoke(app, ["build", "walk"])
    assert no_osm.exit_code == 1
    assert "no archived snapshot of 'toy_osm'" in no_osm.output

    osm = env / "downloads" / "toy.osm"
    osm.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "osm" / "toy.osm", osm)
    runner.invoke(app, ["ingest", "register", "toy_osm", str(osm), "--snapshot", "v1"])
    no_transit = runner.invoke(app, ["build", "walk"])
    assert no_transit.exit_code == 1
    assert "run `glacies build transit` first" in no_transit.output


def test_build_zones(env: Path, archived_feed: Path) -> None:
    downloads = env / "downloads"
    assert runner.invoke(app, ["build", "transit"]).exit_code == 0
    sources = {
        "toy_population": write_population(downloads / "pop.tif"),
        "toy_landcover": write_landcover(downloads / "lc.tif"),
        "toy_buildings": write_buildings(downloads / "buildings.csv.gz"),
        "toy_osm": shutil.copy(FIXTURES / "osm" / "toy_pois.osm", downloads / "toy_pois.osm"),
    }
    for name, path in sources.items():
        args = ["ingest", "register", name, str(path), "--snapshot", "v1"]
        assert runner.invoke(app, args).exit_code == 0

    result = runner.invoke(app, ["build", "zones"])

    assert result.exit_code == 0, result.output
    assert "conservation error 0.0e+00" in result.output
    zones = pl.read_parquet(env / "data" / "processed" / "toyville" / "zones" / "zones.parquet")
    assert int(zones["stops_bus"].sum()) == 3
    assert int(zones["building_count_c65"].sum()) == 3


def test_build_zones_needs_every_input(env: Path) -> None:
    result = runner.invoke(app, ["build", "zones"])

    assert result.exit_code == 1
    assert "no archived snapshot of 'toy_population'" in result.output
