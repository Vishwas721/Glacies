"""``assignment.toml`` parsing and validation (Phase 6 M1)."""

from pathlib import Path

import pytest

from glacies.cities import CityConfigError, load_assignment

TOY = Path(__file__).parent / "fixtures" / "cities" / "toyville" / "assignment.toml"
REPO = Path(__file__).parents[1] / "cities"


def test_loads_toy_assignment() -> None:
    config = load_assignment(TOY)
    window = config.assignment

    assert len(window.departures()) == 120
    assert window.report_window() == (8 * 3600 + 1800, 9 * 3600 + 1800)
    assert [v.name for v in config.capacity.vehicles if v.is_default] == ["bus", "metro"]


def test_departure_weights_follow_the_hourly_profile() -> None:
    weights = load_assignment(TOY).assignment.weights()

    assert sum(weights) == pytest.approx(1.0)
    assert sum(weights[:60]) == pytest.approx(0.4)  # 08:00-08:59
    assert weights[0] == pytest.approx(0.4 / 60)
    assert weights[-1] == pytest.approx(0.6 / 60)


def test_repository_assignment_files_are_valid() -> None:
    paths = sorted(REPO.glob("*/assignment.toml"))
    assert paths
    for path in paths:
        load_assignment(path)


def test_bengaluru_capacities_match_the_dpr() -> None:
    """Phase-3 DPR p. xviii: a 6-car train holds 2,004 at 8 standees/m² (286 seated)."""
    capacity = load_assignment(REPO / "bengaluru" / "assignment.toml").capacity
    (metro,) = [v for v in capacity.vehicles if v.name == "metro_6car"]

    assert metro.seats + capacity.crush_standing_per_m2 * metro.standing_area_m2 == 2004


def _write(tmp_path: Path, old: str, new: str) -> Path:
    text = TOY.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "assignment.toml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('window_end = "10:00"', 'window_end = "08:00"', "window_end"),
        ('report_end = "09:30"', 'report_end = "08:00"', "report_end"),
        ("hours = [8, 9]", "hours = [8]", "differ in length"),
        ("weights = [0.4, 0.6]", "weights = [0.4, 0.0]", "positive"),
        ('window_end = "10:00"', 'window_end = "11:00"', "no weight for hours"),
        ("crush_standing_per_m2 = 8.0", "crush_standing_per_m2 = 5.0", "crush density"),
        ('name = "bus_express"', 'name = "bus"', "unique"),
        ('route_prefixes = ["10 EXP"]', "", "exactly one vehicle"),
        ("band_km = [2, 4]", "band_km = [4, 2]", "band_km"),
        ("free_share = 0.5", "free_share = 1.5", "free_share"),
        ('function = "density_linear"', 'function = "bpr"', "function"),
        ("[value_of_time]", "[value_of_time]\ntypo = 1", "typo"),
    ],
)
def test_rejects_bad_assignment(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(CityConfigError, match=message):
        load_assignment(_write(tmp_path, old, new))


def test_missing_assignment_file(tmp_path: Path) -> None:
    with pytest.raises(CityConfigError, match="not found"):
        load_assignment(tmp_path / "assignment.toml")
