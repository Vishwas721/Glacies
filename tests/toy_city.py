"""Toyville built from raw by the real pipeline, as far as a test needs."""

import shutil
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from glacies.cli import app
from tests.gtfs_edit import TOY_FEED
from tests.zone_inputs import write_buildings, write_landcover, write_population

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def invoke(*command: str) -> None:
    result = runner.invoke(app, list(command))
    assert result.exit_code == 0, result.output


def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Toyville with a baseline matrix and accessibility; returns its processed folder."""
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
        invoke("ingest", "register", name, str(path), "--snapshot", "v1")
    for command in (["build-city"], ["build", "tt-matrix"], ["build", "accessibility"]):
        invoke(*command)
    return tmp_path / "data" / "processed" / "toyville"


def assign(city: Path) -> None:
    """Add the baseline demand and its assignment to a built Toyville."""
    invoke("build", "paths")
    # The toy's buildings and POIs lie away from its stops, so equal scores let every zone
    # with a stop attract trips.
    proxy = city / "attraction" / "attraction.parquet"
    table = pl.read_parquet(proxy)
    table.with_columns(pl.lit(1 / table.height).alias("employment_score")).write_parquet(proxy)
    invoke("build", "demand")
    invoke("build", "assignment")
