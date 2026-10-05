"""`glacies build-city`: rebuild everything from the raw archive (Phase 1 definition of done)."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from glacies.cli import app
from glacies.config import Settings
from glacies.pipeline import PipelineError, clean_city
from glacies.provenance import sha256_file
from tests.gtfs_edit import TOY_FEED
from tests.zone_inputs import write_buildings, write_landcover, write_population

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture
def city(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Toyville with every raw input archived; returns data/processed/toyville."""
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
    return tmp_path / "data" / "processed" / "toyville"


def fingerprint(directory: Path) -> dict[str, str]:
    return {
        p.relative_to(directory).as_posix(): sha256_file(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def test_build_city_runs_every_stage(city: Path) -> None:
    result = runner.invoke(app, ["build-city"])

    assert result.exit_code == 0, result.output
    for stage in ("verify", "validate", "transit", "walk", "zones", "build"):
        assert f"[{stage:<8}]" in result.output
    build = json.loads((city / "BUILD.json").read_text(encoding="utf-8"))
    assert [s["stage"] for s in build["stages"]] == ["transit", "walk", "zones"]
    assert sorted(i["dataset"] for i in build["inputs"]) == [
        "toy_buildings",
        "toy_gtfs",
        "toy_landcover",
        "toy_osm",
        "toy_population",
    ]
    assert build["validation"]["toy_gtfs"]["errors"] == 0
    for stage in build["stages"]:
        manifest = city / stage["directory"] / "manifest.json"
        assert sha256_file(manifest) == stage["manifest_sha256"]


def test_clean_rebuilds_are_byte_identical(city: Path) -> None:
    assert runner.invoke(app, ["build-city", "--clean"]).exit_code == 0
    first = fingerprint(city)
    assert runner.invoke(app, ["build-city", "--clean"]).exit_code == 0

    assert fingerprint(city) == first
    assert {"BUILD.json", "transit/stop_times.parquet", "walk/edges.parquet"} <= set(first)
    assert "zones/zones.parquet" in first
    assert any(path.startswith("reports/toy_gtfs/v1/") for path in first)


def test_clean_removes_stale_outputs(city: Path) -> None:
    stale = city / "transit" / "old.parquet"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")

    assert runner.invoke(app, ["build-city", "--clean"]).exit_code == 0

    assert not stale.exists()


def test_refuses_a_tampered_raw_archive(city: Path) -> None:
    raw = city.parents[1] / "raw" / "toyville" / "toy_gtfs" / "v1" / "data" / "stops.txt"
    raw.write_text(raw.read_text(encoding="utf-8") + "Z,Tampered,12.05,77.05,,\n", "utf-8")

    result = runner.invoke(app, ["build-city"])

    assert result.exit_code == 1
    assert "raw archive failed verification" in result.output
    assert not (city / "BUILD.json").exists()


def test_clean_never_leaves_the_processed_directory(tmp_path: Path) -> None:
    from glacies.cities import load_city

    config = load_city(FIXTURES / "cities" / "toyville" / "city.toml")
    escaping = config.model_copy(
        update={"city": config.city.model_copy(update={"id": "../../outside"})}
    )
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")

    with pytest.raises(PipelineError, match="refusing to delete"):
        clean_city(settings, escaping)
