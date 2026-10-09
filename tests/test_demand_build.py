"""Attainable attractions on toys, and `glacies build demand` on the toy city (Phase 5 M1-M2)."""

import json
import shutil
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from glacies.cli import app
from glacies.demand.feasibility import attainable
from glacies.demand.gravity import furness
from tests.gtfs_edit import TOY_FEED
from tests.zone_inputs import write_buildings, write_landcover, write_population

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def pairs(cells: list[tuple[int, int]]) -> tuple[np.ndarray, np.ndarray]:
    o, d = zip(*cells, strict=True)
    return np.array(o, dtype=np.uint32), np.array(d, dtype=np.uint32)


def test_feasible_targets_are_untouched() -> None:
    origin, dest = pairs([(0, 0), (0, 1), (1, 0), (1, 1)])
    result = attainable(
        origin, dest, np.array([60.0, 40.0]), np.array([50.0, 50.0]), tolerance=1e-9
    )

    np.testing.assert_allclose(result.attractions, [50, 50])
    assert result.keep.all()
    assert (result.blocks, result.trips_moved) == (1, 0)


def test_bottleneck_is_split_by_hand() -> None:
    """O = (10, 90), D = (50, 50); origin 0 reaches both zones, origin 1 only zone 0.

    Origin 1's 90 trips can only go to zone 0, which wants 50: the bottleneck is {origin 1} ->
    {zone 0}. In the balanced limit origin 0 sends nothing to zone 0, so that pair is dropped,
    zone 0 gets 90 and zone 1 the remaining 10: 40 trips of attraction move.
    """
    origin, dest = pairs([(0, 0), (0, 1), (1, 0)])
    o, d = np.array([10.0, 90.0]), np.array([50.0, 50.0])

    result = attainable(origin, dest, o, d, tolerance=1e-9)

    np.testing.assert_allclose(result.attractions, [90, 10])
    assert result.keep.tolist() == [False, True, True]
    assert result.blocks == 2
    assert result.trips_moved == pytest.approx(40)
    balanced = furness(
        origin[result.keep], dest[result.keep], np.ones(2), o, result.attractions,
        tolerance=1e-12, max_iterations=100,
    )  # fmt: skip
    assert balanced.converged
    np.testing.assert_allclose(balanced.trips, [10, 90])


def test_isolated_groups_are_balanced_separately() -> None:
    """Zones 0 and 1 reach only each other: 0 -> 1 carries 5 trips, 1 -> 0 carries 10, so the
    attractions must be (10, 5) whatever the proxy says (here 7.5 each)."""
    origin, dest = pairs([(0, 1), (1, 0)])

    result = attainable(origin, dest, np.array([5.0, 10.0]), np.array([7.5, 7.5]), tolerance=1e-9)

    np.testing.assert_allclose(result.attractions, [10, 5])
    assert result.keep.all()
    assert result.trips_moved == pytest.approx(2.5)


@pytest.fixture
def city(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Toyville built from raw with a baseline matrix and the employment proxy."""
    monkeypatch.setenv("GLACIES_CITIES_DIR", str(FIXTURES / "cities"))
    monkeypatch.setenv("GLACIES_CITY", "toyville")
    monkeypatch.setenv("GLACIES_DATA_DIR", str(tmp_path / "data"))
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    sources = {
        "toy_gtfs": shutil.copytree(TOY_FEED, downloads / "toy_feed"),
        "toy_osm": shutil.copy(FIXTURES / "osm" / "toy.osm", downloads / "toy.osm"),
        "toy_population": write_population(downloads / "pop.tif"),
        "toy_landcover": write_landcover(downloads / "lc.tif"),
        "toy_buildings": write_buildings(downloads / "buildings.csv.gz"),
    }
    for name, path in sources.items():
        result = runner.invoke(app, ["ingest", "register", name, str(path), "--snapshot", "v1"])
        assert result.exit_code == 0, result.output
    for command in (["build-city"], ["build", "tt-matrix"], ["build", "paths"]):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
    processed = tmp_path / "data" / "processed" / "toyville"
    # The toy's buildings and POIs lie away from its stops; equal scores everywhere let every
    # zone with a stop attract trips.
    path = processed / "attraction" / "attraction.parquet"
    table = pl.read_parquet(path)
    table.with_columns(pl.lit(1 / table.height).alias("employment_score")).write_parquet(path)
    return processed


def test_build_demand_balances_and_is_reproducible(city: Path) -> None:
    result = runner.invoke(app, ["build", "demand"])
    assert result.exit_code == 0, result.output
    out = city / "demand" / "baseline"
    ends = pl.read_parquet(out / "trip_ends.parquet")
    od = pl.read_parquet(out / "od.parquet")
    first = {p.name: p.read_bytes() for p in sorted(out.glob("*.parquet"))}

    assert od.height > 0
    assert (od["origin_zone"] != od["dest_zone"]).all()
    rows = od.group_by("origin_zone").agg(pl.col("trips").sum())
    cols = od.group_by("dest_zone").agg(pl.col("trips").sum())
    check = ends.join(rows, left_on="zone_idx", right_on="origin_zone", how="left").join(
        cols, left_on="zone_idx", right_on="dest_zone", how="left", suffix="_in"
    )
    np.testing.assert_allclose(check["trips"].fill_null(0), check["origin"], rtol=1e-5, atol=1e-9)
    np.testing.assert_allclose(
        check["trips_in"].fill_null(0), check["destination"], rtol=1e-5, atol=1e-9
    )
    assert (ends.filter(~pl.col("has_access"))["origin"] == 0).all()
    report = (out / "BUILD_REPORT.md").read_text(encoding="utf-8")
    assert "Estimated" in report
    assert "Glacies test fixture (not verified)" in report

    version = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["version"]
    assert len(version) == 16

    again = runner.invoke(app, ["build", "demand"])
    assert again.exit_code == 0, again.output
    assert {p.name: p.read_bytes() for p in sorted(out.glob("*.parquet"))} == first
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["version"] == version


def test_misspelt_held_out_station_fails(
    city: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cities = shutil.copytree(FIXTURES / "cities", tmp_path / "cities")
    demand = cities / "toyville" / "demand.toml"
    text = demand.read_text(encoding="utf-8").replace('"Central Station"', '"Centrl Station"')
    demand.write_text(text, encoding="utf-8")
    monkeypatch.setenv("GLACIES_CITIES_DIR", str(cities))

    result = runner.invoke(app, ["build", "demand"])

    assert result.exit_code != 0
    assert "Centrl Station" in result.output


def test_station_flows_on_the_toy_city(city: Path) -> None:
    """Plumbing and determinism: the toy's OD pairs are all fastest on foot, so the metro
    arithmetic is covered by tests/test_metro.py and crates/raptor/tests/paths.rs."""
    assert runner.invoke(app, ["build", "demand"]).exit_code == 0
    result = runner.invoke(app, ["build", "station-flows"])
    assert result.exit_code == 0, result.output
    out = city / "metro" / "baseline"
    stations = pl.read_parquet(out / "stations.parquet")
    pairs = pl.read_parquet(out / "station_pairs.parquet")
    reach = pl.read_parquet(city / "paths" / "baseline" / "od_reach.parquet")
    od = pl.read_parquet(city / "demand" / "baseline" / "od.parquet")
    first = {p.name: p.read_bytes() for p in sorted(out.glob("*.parquet"))}

    assert "Central Station" in stations["name"].to_list()
    assert reach.height == od.height
    assert (reach["reached"] >= reach["walked"]).all()
    assert stations["entries"].sum() == pytest.approx(pairs["trips"].sum())
    assert stations["exits"].sum() == pytest.approx(pairs["trips"].sum())
    assert "Simulated" in (out / "BUILD_REPORT.md").read_text(encoding="utf-8")

    again = runner.invoke(app, ["build", "station-flows"])
    assert again.exit_code == 0, again.output
    assert {p.name: p.read_bytes() for p in sorted(out.glob("*.parquet"))} == first


def test_walk_pairs_are_left_out_when_configured(
    city: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every toy pair is fastest on foot, so excluding walk pairs leaves no transit demand."""
    cities = shutil.copytree(FIXTURES / "cities", tmp_path / "cities")
    demand = cities / "toyville" / "demand.toml"
    text = demand.read_text(encoding="utf-8").replace(
        "exclude_walk_pairs = false", "exclude_walk_pairs = true"
    )
    demand.write_text(text, encoding="utf-8")
    monkeypatch.setenv("GLACIES_CITIES_DIR", str(cities))
    reach = pl.read_parquet(city / "paths" / "baseline" / "od_reach.parquet")
    assert (reach["walked"] * 2 >= reach["reached"]).all()

    result = runner.invoke(app, ["build", "demand"])

    assert result.exit_code != 0
    assert "no zone with transit access" in result.output


def test_rides_to_stations_use_their_own_matrix(
    city: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With [demand.ride_access], demand gets its own matrix and the walk-only tt-matrix (used
    by accessibility) is left alone; zones reached only by the ride produce but never attract."""
    cities = shutil.copytree(FIXTURES / "cities", tmp_path / "cities")
    demand = cities / "toyville" / "demand.toml"
    text = (
        demand.read_text(encoding="utf-8")
        .replace(
            "\n[demand.priors.trip_rate]",
            "\n[demand.ride_access]\nmax_km = 50.0\nspeed_kmh = 15.0\ndetour_factor = 1.3\n"
            'penalty_min = 5.0\nsource = "Glacies test fixture"\nverified = false\n'
            "\n[demand.priors.trip_rate]",
        )
        .replace("beta_per_min = 0.1\n", "beta_per_min = 0.1\nmax_iterations = 100000\n")
    )
    demand.write_text(text, encoding="utf-8")
    monkeypatch.setenv("GLACIES_CITIES_DIR", str(cities))
    walk_only = {
        p.name: p.read_bytes() for p in sorted((city / "tt_matrix" / "baseline").iterdir())
    }

    missing = runner.invoke(app, ["build", "paths"])
    assert missing.exit_code != 0
    assert "demand-matrix" in missing.output
    for command in (["build", "demand-matrix"], ["build", "paths"], ["build", "demand"]):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output

    assert (city / "demand_matrix" / "baseline" / "manifest.json").is_file()
    assert {
        p.name: p.read_bytes() for p in sorted((city / "tt_matrix" / "baseline").iterdir())
    } == walk_only
    access = pl.read_parquet(city / "paths" / "baseline" / "zone_access.parquet")
    assert (access["ride_stations"] > 0).all()  # every zone is within 50 km of a station
    ends = pl.read_parquet(city / "demand" / "baseline" / "trip_ends.parquet")
    assert (ends.filter(~pl.col("has_walk_access"))["destination"] == 0).all()
    assert ends["has_access"].sum() > ends["has_walk_access"].sum()
