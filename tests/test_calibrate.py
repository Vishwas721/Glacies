"""Calibration pieces by hand: station sets, fit statistics, the β search (Phase 5 M4)."""

import math
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from glacies.cities import load_demand
from glacies.demand.calibrate import (
    EXCLUDED,
    HELD_OUT,
    TRAINING,
    fit,
    search_beta,
    station_sets,
)

TOY = Path(__file__).parent / "fixtures" / "cities" / "toyville" / "demand.toml"


def test_station_sets() -> None:
    """Excluded only if every line is excluded (an interchange with a kept line stays)."""
    calibration = load_demand(TOY).calibration.model_copy(
        update={"exclude_lines": ["Yellow"], "held_out_stations": ["D", "E"]}
    )
    stations = pl.DataFrame(
        {
            "station_idx": [1, 2, 3, 4, 5],
            "name": ["A", "B", "C", "D", "E"],
            "lines": ["Purple", "Yellow", "Green+Yellow", "Green", "Yellow"],
        }
    )

    sets = station_sets(stations, calibration)

    assert sets["set"].to_list() == [TRAINING, EXCLUDED, TRAINING, HELD_OUT, EXCLUDED]


def test_perfect_shape_at_any_level() -> None:
    result = fit(np.array([2.0, 1.0, 1.0]), np.array([50.0, 25.0, 25.0]))

    assert result.rmse_share == pytest.approx(0)
    assert result.r2_share == pytest.approx(1)
    assert result.correlation == pytest.approx(1)
    assert result.mean_geh == pytest.approx(0)
    assert result.level_ratio == pytest.approx(4 / 100)


def test_fit_by_hand() -> None:
    """Shares 0.5/0.5 against 0.75/0.25: residuals ±0.25, RMSE 0.25, SS_res = SS_tot = 0.125
    so R² = 0. Scaled counts 2/2 against 3/1: GEH √(2/5) and √(2/3), mean 0.724."""
    result = fit(np.array([1.0, 1.0]), np.array([3.0, 1.0]))

    assert result.rmse_share == pytest.approx(0.25)
    assert result.r2_share == pytest.approx(0)
    assert result.mean_geh == pytest.approx((math.sqrt(2 / 5) + math.sqrt(2 / 3)) / 2)
    assert result.share_geh_below_5 == 1
    assert result.level_ratio == pytest.approx(0.5)


def test_search_finds_an_interior_minimum() -> None:
    calls: list[tuple[float, str]] = []

    def evaluate(beta: float, stage: str) -> float:
        calls.append((beta, stage))
        return (math.log(beta) - math.log(0.03)) ** 2

    chosen, at_boundary = search_beta(evaluate, 0.005, 0.2, 12, 8)

    assert chosen == pytest.approx(0.03, rel=0.03)
    assert not at_boundary
    assert [stage for _, stage in calls].count("grid") == 12
    assert [stage for _, stage in calls].count("refine") == 8
    grid = [beta for beta, stage in calls if stage == "grid"]
    assert grid == sorted(grid)  # ascending, so Furness warm-starts from a neighbour


def test_search_flags_a_minimum_at_the_edge() -> None:
    chosen, at_boundary = search_beta(lambda beta, _: beta, 0.005, 0.2, 6, 4)

    assert at_boundary
    assert chosen == pytest.approx(0.005)
