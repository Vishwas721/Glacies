"""``demand.toml`` parsing and validation (Phase 5 M1)."""

from datetime import date
from pathlib import Path

import pytest

from glacies.cities import CityConfigError, load_demand

TOY = Path(__file__).parent / "fixtures" / "cities" / "toyville" / "demand.toml"
REPO = Path(__file__).parents[1] / "cities"


def test_loads_toy_demand() -> None:
    demand = load_demand(TOY)

    assert demand.priors.trip_rate.value == 0.10
    assert demand.priors.transit_share.range == (0.4, 0.6)
    assert demand.cost.column == "p50_s"
    assert demand.gravity.tolerance == 1e-6
    assert demand.calibration.dates == [date(2026, 10, 13)]


def test_repository_demand_files_are_valid() -> None:
    paths = sorted(REPO.glob("*/demand.toml"))
    assert paths
    for path in paths:
        load_demand(path)


def test_bengaluru_calibration_window() -> None:
    calibration = load_demand(REPO / "bengaluru" / "demand.toml").calibration

    assert calibration.hours == [8, 9]
    assert {d.isoweekday() for d in calibration.dates} == {2, 3, 4}  # Tue-Thu
    assert "Yeshwantpur" in calibration.held_out_stations
    assert calibration.exclude_lines == ["Yellow"]


def _write(tmp_path: Path, old: str, new: str) -> Path:
    text = TOY.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "demand.toml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("range = [0.08, 0.14]", "range = [0.12, 0.14]", "must contain value"),
        ("range = [0.4, 0.6]", "range = [0.4, 1.2]", "cannot exceed 1"),
        ("accept_km = [1.0, 4.0]", "accept_km = [3.0, 4.0]", "must contain mean_km"),
        ('column = "p50_s"', 'column = "median"', "column"),
        ("hours = [8, 9]", "hours = [9, 8]", "hours"),
        ('dates = ["2026-10-13"]', 'dates = ["2026-10-13", "2026-10-13"]', "dates"),
        (
            'held_out_stations = ["Central Station"]',
            'held_out_stations = ["A", "A"]',
            "held_out_stations",
        ),
        ("beta_per_min = 0.1", "beta_per_min = 0", "beta_per_min"),
        ("exclude_intrazonal = true", "exclude_intrazonal = true\ntypo = 1", "typo"),
    ],
)
def test_rejects_bad_demand(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(CityConfigError, match=message):
        load_demand(_write(tmp_path, old, new))


def test_missing_demand_file(tmp_path: Path) -> None:
    with pytest.raises(CityConfigError, match="not found"):
        load_demand(tmp_path / "demand.toml")
