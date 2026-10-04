import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from glacies.cli import app

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
