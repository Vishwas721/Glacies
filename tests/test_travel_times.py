"""Travel-time matrix job on Toyville (Phase 3 M2), checked against a brute-force recomputation."""

import math
import shutil
from pathlib import Path

import glacies_raptor as gr
import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from glacies.analytics.travel_times import zone_points, zone_walks
from glacies.cities import Accessibility, load_city
from glacies.cli import app
from glacies.routing.network import load_router
from tests.gtfs_edit import TOY_FEED
from tests.zone_inputs import write_buildings, write_landcover, write_population

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(scope="module")
def city(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Toyville built from raw, then its matrix; returns data/processed/toyville."""
    tmp = tmp_path_factory.mktemp("toyville")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GLACIES_CITIES_DIR", str(FIXTURES / "cities"))
        mp.setenv("GLACIES_CITY", "toyville")
        mp.setenv("GLACIES_DATA_DIR", str(tmp / "data"))
        downloads = tmp / "downloads"
        downloads.mkdir()
        sources = {
            "toy_gtfs": shutil.copytree(TOY_FEED, downloads / "toy_feed"),
            "toy_osm": shutil.copy(FIXTURES / "osm" / "toy.osm", downloads / "toy.osm"),
            "toy_population": write_population(downloads / "pop.tif"),
            "toy_landcover": write_landcover(downloads / "lc.tif"),
            "toy_buildings": write_buildings(downloads / "buildings.csv.gz"),
        }
        for name, path in sources.items():
            args = ["ingest", "register", name, str(path), "--snapshot", "v1"]
            assert runner.invoke(app, args).exit_code == 0
        for args in (["build-city"], ["build", "tt-matrix"]):
            result = runner.invoke(app, args)
            assert result.exit_code == 0, result.output
    return tmp / "data" / "processed" / "toyville"


def matrix(city: Path) -> pl.DataFrame:
    return pl.read_parquet(city / "tt_matrix" / "baseline" / "*.parquet")


def nearest_rank(values: list[float], p: int) -> float:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p * len(ordered) / 100)) - 1]


def test_matches_brute_force(city: Path) -> None:
    config = load_city(FIXTURES / "cities" / "toyville" / "city.toml")
    settings = config.accessibility
    router = load_router(city, config.routing, config.city.crs_projected)
    zones = pl.read_parquet(city / "zones" / "zones.parquet")
    walks = zone_walks(router, city / "walk", zone_points(zones), settings)
    departures = np.array(settings.departures(), dtype=np.uint32)
    limit = settings.max_travel_time_min * 60

    expected = {}
    for o, (stops, secs) in enumerate(walks.access):
        arrivals = router.timetable.range_arrivals(stops, secs, departures, 4, 60).astype(float)
        arrivals[arrivals == gr.UNREACHED] = math.inf
        walk_only = dict(zip(*(a.tolist() for a in walks.walk_only[o]), strict=True))
        for d, (dstops, dsecs) in enumerate(walks.access):
            on_foot = walk_only.get(d, math.inf)
            times = [
                min([on_foot, *(arrivals[i, dstops] + dsecs - dep).tolist()])
                for i, dep in enumerate(departures.tolist())
            ]
            row = [nearest_rank(times, p) for p in settings.percentiles]
            if row[0] <= limit:
                expected[(o, d)] = tuple(None if t > limit else int(t) for t in row)

    got = {
        (o, d): (p25, p50, p75)
        for o, d, p25, p50, p75 in matrix(city).sort("origin_zone", "dest_zone").iter_rows()
    }
    assert got == expected
    by_transit = [k for k in got if k[1] not in walks.walk_only[k[0]][0].tolist()]
    assert by_transit, "some pairs must need transit, not only walking"


def test_every_zone_reaches_itself(city: Path) -> None:
    m = matrix(city)
    own = m.filter(pl.col("origin_zone") == pl.col("dest_zone"))

    assert own.height == pl.read_parquet(city / "zones" / "zones.parquet").height
    assert own.select(pl.col("^p.*_s$").max()).row(0) == (0, 0, 0)


def test_schema_manifest_and_labels(city: Path) -> None:
    m = matrix(city)
    assert m.schema == pl.Schema(
        {
            "origin_zone": pl.UInt32,
            "dest_zone": pl.UInt32,
            "p25_s": pl.UInt16,
            "p50_s": pl.UInt16,
            "p75_s": pl.UInt16,
        }
    )
    out = city / "tt_matrix" / "baseline"
    manifest = (out / "manifest.json").read_text(encoding="utf-8")
    assert '"nature": "simulated"' in manifest
    report = (out / "BUILD_REPORT.md").read_text(encoding="utf-8")
    assert "(Simulated)" in report
    assert "Assumed" in report


def test_rebuild_is_byte_identical(city: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = city / "tt_matrix" / "baseline"
    before = {p.name: p.read_bytes() for p in sorted(out.iterdir())}
    monkeypatch.setenv("GLACIES_CITIES_DIR", str(FIXTURES / "cities"))
    monkeypatch.setenv("GLACIES_CITY", "toyville")
    monkeypatch.setenv("GLACIES_DATA_DIR", str(city.parents[1]))

    assert runner.invoke(app, ["build", "tt-matrix"]).exit_code == 0

    assert {p.name: p.read_bytes() for p in sorted(out.iterdir())} == before


def test_departures_are_half_open() -> None:
    settings = Accessibility(window_start="07:30", window_end="07:33", departure_step_s=60)

    assert settings.departures() == [27000, 27060, 27120]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"window_end": "07:00"}, "after window_start"),
        ({"percentiles": [50, 25]}, "ascending"),
        ({"thresholds_min": [15, 200]}, "cannot exceed"),
        ({"window_start": "7:5"}, "HH:MM"),
    ],
)
def test_bad_settings_are_rejected(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Accessibility.model_validate(overrides)


def test_accessibility_stage_on_toyville(city: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLACIES_CITIES_DIR", str(FIXTURES / "cities"))
    monkeypatch.setenv("GLACIES_CITY", "toyville")
    monkeypatch.setenv("GLACIES_DATA_DIR", str(city.parents[1]))

    result = runner.invoke(app, ["build", "accessibility"])

    assert result.exit_code == 0, result.output
    assert "headline: residents reach on average" in result.output
    out = city / "accessibility" / "baseline"
    table = pl.read_parquet(out / "accessibility.parquet")
    zones = pl.read_parquet(city / "zones" / "zones.parquet").height
    assert table.height == zones * 3 * 4  # percentiles x thresholds
    assert table.select(
        pl.col("est_jobs_share", "population_share").is_between(0, 1 + 1e-9).all()
    ).row(0) == (True, True)
    wide = table.pivot("threshold_min", index=["zone_idx", "percentile"], values="est_jobs_share")
    for lower, upper in (("15", "30"), ("30", "45"), ("45", "60")):
        assert (wide[lower] <= wide[upper]).all()
    by_pct = table.pivot("percentile", index=["zone_idx", "threshold_min"], values="est_jobs_share")
    assert (by_pct["25"] >= by_pct["75"]).all()
    summary = pl.read_parquet(out / "summary.parquet")
    assert set(summary["scope"]) == {"all zones", "excluding edge zones"}
