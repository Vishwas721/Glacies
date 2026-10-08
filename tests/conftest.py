"""Fixtures shared by several test modules."""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from glacies.cli import app

FIXTURES = Path(__file__).parent / "fixtures"


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
    runner = CliRunner()
    for name, path in (("toy_gtfs", feed), ("toy_osm", osm)):
        result = runner.invoke(app, ["ingest", "register", name, str(path), "--snapshot", "v1"])
        assert result.exit_code == 0, result.output
    for stage in ("transit", "walk"):
        result = runner.invoke(app, ["build", stage])
        assert result.exit_code == 0, result.output
    return tmp_path / "data" / "processed" / "toyville"
