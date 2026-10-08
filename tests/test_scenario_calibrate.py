import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from glacies.cli import app
from glacies.scenario.calibrate import detour_ratios, markdown

runner = CliRunner()


def test_detour_ratios_measure_consecutive_bus_stops(city_dir: Path) -> None:
    result = detour_ratios(city_dir, samples=100, seed=1)
    # Toy R1 runs A-B-C; R3 is a metro (excluded) and R2 does not run on the service day.
    assert (result.hops, result.sampled) == (2, 2)
    assert result.ratios.size == 2
    assert (result.ratios >= 1.0).all()  # a path is never shorter than the straight line
    assert detour_ratios(city_dir, samples=100, seed=1).ratios.tolist() == result.ratios.tolist()
    text = markdown(result, "Toy.")
    assert f"mean (**{result.mean:.2f}**)" in text


def test_detour_ratios_respect_the_length_range(city_dir: Path) -> None:
    assert detour_ratios(city_dir, samples=100, seed=1, max_m=10.0).hops == 0


def test_calibrate_command_writes_the_report(city_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "detour.md"
    result = runner.invoke(app, ["scenario", "calibrate", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "2 pairs" in result.output
    assert out.read_text(encoding="utf-8").startswith("# Detour factor")


@pytest.mark.usefixtures("city_dir")
def test_check_command_applies_the_scenario(tmp_path: Path) -> None:
    path = tmp_path / "toy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scenario_id": "toy",
                "title": "Toy",
                "mutations": [{"type": "modify_headway", "route_id": "R1", "headway_factor": 0.5}],
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["scenario", "check", str(path)])
    assert result.exit_code == 0, result.output
    assert "1. modify_headway R1: -0 / +1 trips" in result.output
    assert "toy: OK; trips 3 -> 4" in result.output

    path.write_text(path.read_text(encoding="utf-8").replace("R1", "R9"), encoding="utf-8")
    result = runner.invoke(app, ["scenario", "check", str(path)])
    assert result.exit_code == 1
    assert "route 'R9' is not in the baseline network" in result.output
