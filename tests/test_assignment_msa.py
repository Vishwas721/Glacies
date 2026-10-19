"""Crowding multipliers and the MSA loop on hand-checkable toys (Phase 6 M3)."""

from pathlib import Path

import glacies_raptor as gr
import numpy as np
import polars as pl
import pytest

from glacies.assignment.crowding import multipliers
from glacies.assignment.msa import Rows, run_msa
from glacies.cities import AssignmentConfig, load_assignment

TOY = Path(__file__).parent / "fixtures" / "cities" / "toyville" / "assignment.toml"
A, B, C = 0, 1, 2


def config(**route_choice: object) -> AssignmentConfig:
    base = load_assignment(TOY)
    return base.model_copy(
        update={
            "route_choice": base.route_choice.model_copy(
                update={"use_fares": False} | route_choice
            ),
            "msa": base.msa.model_copy(update={"max_iterations": 400, "gap": 1e-5}),
        }
    )


def test_tag_multiplier_at_design_density() -> None:
    # A 6-car train at its design capacity of 1,574: 1,288 standees on 214.75 m² (5.998/m²);
    # 286 seated at 1 + 0.09 D, 1,288 standing at 1.43 + 0.13 D; the mean is about 2.088.
    curve = config().crowding
    m = multipliers(
        np.array([1574.0, 200.0, 2500.0]),
        np.array([286.0, 286.0, 286.0]),
        np.array([214.75, 214.75, 214.75]),
        curve,
        8.0,
    )
    d = 1288 / 214.75
    assert m[0] == pytest.approx((286 * (1 + 0.09 * d) + 1288 * (1.43 + 0.13 * d)) / 1574)
    assert m[0] == pytest.approx(2.088, abs=1e-3)
    assert m[1] == 1.0  # seats not full
    # Beyond crush (8/m²) the density is held: everyone standing weighs 1.43 + 1.04 = 2.47.
    assert m[2] == pytest.approx((286 * 1.72 + (2500 - 286) * 2.47) / 2500)


def test_no_standing_area_counts_as_crush() -> None:
    m = multipliers(np.array([50.0]), np.array([40.0]), np.array([0.0]), config().crowding, 8.0)
    assert m[0] == pytest.approx((40 * 1.72 + 10 * 2.47) / 50)


def _toy_choices(theta_trips: float = 100.0) -> tuple[gr.ChoiceSet, Rows]:
    """Metro trip 1 A 08:00 -> C 08:10; bus trip 2 A 08:00 -> B 08:10 -> C 08:20; 100 trips."""
    hm = lambda h, m: h * 3600 + m * 60  # noqa: E731
    u32 = lambda *v: np.array(v, dtype=np.uint32)  # noqa: E731
    times = u32(hm(8, 0), hm(8, 10), hm(8, 0), hm(8, 10), hm(8, 20))
    tt = gr.Timetable.build(3, u32(1, 2), u32(0, 2, 5), u32(A, C, A, B, C), times, times,
                            u32(), u32(), u32())  # fmt: skip
    bus_only = tt.retain_trips(np.array([1, 0, 1], dtype=np.uint8))
    rows = Rows(
        trip=u32(1, 1, 2, 2, 2),
        offset=u32(0, 0, 2),
        km=np.array([0.0, 5.0, 0.0, 3.0, 6.0]),
        seconds=np.array([600.0, 0.0, 600.0, 600.0, 0.0]),
    )
    choices = gr.ChoiceSet()
    choices.extend(
        tt, bus_only,
        [(u32(A), u32(60), u32(), u32(), u32(0), np.array([theta_trips]))],
        u32(0), u32(hm(7, 59)), np.array([1.0]), 1, u32(0), u32(C), u32(60),
        np.array([0, 1, 0], dtype=np.uint8), u32(10, 2**32 - 1, 11),
        rows.offset, rows.km, (2.0, 2.0, 1.0, 5.0), None, 7200, 4, 60,
    )  # fmt: skip
    return choices, rows


# Metro: 30 seats + 5 m² (capacity 60, crush 70). Bus: 200 seats, never crowded.
VEHICLES = pl.DataFrame(
    {"trip_idx": [1, 2], "seats": [30, 200], "standing_area_m2": [5.0, 0.0]},
    schema_overrides={"trip_idx": pl.UInt32},
)


def _equilibrium(theta: float) -> float:
    """Metro trips x with x = 100 x logit(bus cost - metro cost), by bisection.

    Both walk 2 x 1 min (weight 2): 4 generalised minutes. Bus: 20 min in vehicles, never
    crowded. Metro: 10 min times the multiplier of its load.
    """
    curve = config().crowding

    def excess(x: float) -> float:
        m = multipliers(np.array([x]), np.array([30.0]), np.array([5.0]), curve, 8.0)[0]
        metro, bus = 4 + 10 * m, 4 + 20
        return x - 100 / (1 + np.exp(-theta * (bus - metro)))

    low, high = 0.0, 100.0
    for _ in range(100):
        mid = (low + high) / 2
        low, high = (mid, high) if excess(mid) < 0 else (low, mid)
    return (low + high) / 2


def test_crowding_pushes_riders_from_the_full_metro_to_the_bus() -> None:
    choices, rows = _toy_choices()
    cfg = config()
    theta = cfg.route_choice.theta_per_min
    result = run_msa(choices, rows, VEHICLES, cfg)
    metro = result.boardings[0]

    # Without crowding the metro would take 100 / (1 + e^-1.2) = 76.9 of the 100 trips.
    uncrowded = 100 / (1 + np.exp(-theta * 10))
    assert uncrowded == pytest.approx(76.85, abs=0.01)
    assert result.convergence["iteration"][0] == 0
    assert metro < uncrowded - 10
    assert metro == pytest.approx(_equilibrium(theta), abs=0.5)
    assert result.boardings.sum() == pytest.approx(100.0)  # conserved
    assert result.converged
    gaps = result.convergence["gap"].to_numpy()[1:]
    assert gaps[-1] < 1e-5


def test_a_larger_theta_reaches_its_own_equilibrium() -> None:
    choices, rows = _toy_choices()
    result = run_msa(choices, rows, VEHICLES, config(), theta=0.5)
    assert result.boardings[0] == pytest.approx(_equilibrium(0.5), abs=0.5)
