"""Furness balancing on hand-checkable toys (Phase 5 M2)."""

import math

import numpy as np
import pytest

from glacies.demand.gravity import Balanced, exponential, furness
from glacies.demand.production import DemandError


def dense_pairs(friction: list[list[float]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every cell with positive friction as a pair, row-major."""
    f = np.array(friction, dtype=np.float64)
    o, d = np.nonzero(f > 0)
    return o.astype(np.uint32), d.astype(np.uint32), f[o, d]


def balance(friction: list[list[float]], o: list[float], d: list[float]) -> np.ndarray:
    origin, dest, f = dense_pairs(friction)
    result = furness(
        origin, dest, f, np.array(o), np.array(d), tolerance=1e-12, max_iterations=10_000
    )
    assert result.converged
    matrix = np.zeros((len(o), len(d)))
    matrix[origin, dest] = result.trips
    return matrix


def test_two_by_two_matches_the_hand_solution() -> None:
    """O = (60, 40), D = (50, 50), f = [[2, 1], [1, 2]].

    With T11 = x the sums force T12 = 60 - x, T21 = 50 - x, T22 = x - 10. A doubly constrained
    model keeps the cross ratio of f: x (x - 10) = 4 (60 - x)(50 - x), i.e.
    3x² - 430x + 12000 = 0, whose feasible root is x = (430 - √40900) / 6 ≈ 37.9604.
    """
    x = (430 - math.sqrt(40900)) / 6
    expected = np.array([[x, 60 - x], [50 - x, x - 10]])

    np.testing.assert_allclose(balance([[2, 1], [1, 2]], [60, 40], [50, 50]), expected, rtol=1e-9)


def test_three_by_three_with_separable_friction_is_proportional() -> None:
    """f_ij = u_i v_j cancels into the balancing factors: T_ij = O_i D_j / ΣD.

    O = (100, 200, 300), D = (300, 200, 100) gives row 1 = 50, 33.33, 16.67, and so on.
    """
    u, v = [1.0, 2.0, 0.5], [3.0, 1.0, 0.25]
    friction = [[ui * vj for vj in v] for ui in u]
    expected = np.array(
        [[50, 100 / 3, 50 / 3], [100, 200 / 3, 100 / 3], [150, 100, 50]], dtype=np.float64
    )

    np.testing.assert_allclose(
        balance(friction, [100, 200, 300], [300, 200, 100]), expected, rtol=1e-9
    )


def test_three_by_three_with_an_unreachable_block() -> None:
    """Zones 0-1 reach only each other (all friction 1), zone 2 only itself.

    O = (30, 70, 50), D = (40, 60, 50): the 0-1 block is proportional within its total of 100
    (T = O_i D_j / 100 = 12, 18 / 28, 42) and zone 2 keeps its 50 trips. No trips cross.
    """
    friction = [[1.0, 1.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    expected = np.array([[12, 18, 0], [28, 42, 0], [0, 0, 50]], dtype=np.float64)

    np.testing.assert_allclose(balance(friction, [30, 70, 50], [40, 60, 50]), expected, rtol=1e-9)


def test_exponential_three_by_three_keeps_the_friction_cross_ratios() -> None:
    """The balanced matrix meets both margins and T_ij T_kl / (T_il T_kj) = same for f."""
    cost = np.array([[5.0, 20.0, 40.0], [20.0, 5.0, 25.0], [40.0, 25.0, 5.0]])
    friction = exponential(cost, 0.1)
    o, d = [100.0, 200.0, 300.0], [250.0, 250.0, 100.0]

    t = balance(friction.tolist(), o, d)

    np.testing.assert_allclose(t.sum(axis=1), o, rtol=1e-9)
    np.testing.assert_allclose(t.sum(axis=0), d, rtol=1e-9)
    for i, k in ((0, 1), (0, 2), (1, 2)):
        for j, m in ((0, 1), (0, 2), (1, 2)):
            ratio = t[i, j] * t[k, m] / (t[i, m] * t[k, j])
            friction_ratio = friction[i, j] * friction[k, m] / (friction[i, m] * friction[k, j])
            assert ratio == pytest.approx(friction_ratio, rel=1e-9)


def test_exponential_friction() -> None:
    np.testing.assert_allclose(
        exponential(np.array([0.0, 10.0]), 0.1), [1.0, math.exp(-1.0)], rtol=1e-12
    )


def test_impossible_targets_stop_without_converging() -> None:
    """Destination 1 needs 50 trips but only origin 0, with 10, reaches it."""
    origin = np.array([0, 0, 1], dtype=np.uint32)
    dest = np.array([0, 1, 0], dtype=np.uint32)

    result = furness(
        origin,
        dest,
        np.ones(3),
        np.array([10.0, 90.0]),
        np.array([50.0, 50.0]),
        tolerance=1e-9,
        max_iterations=200,
    )

    assert isinstance(result, Balanced)
    assert not result.converged
    assert result.iterations == 200
    assert len(result.row_error_history) == 200
    assert result.max_row_error > 0.1


def test_converges_in_reported_iterations() -> None:
    origin, dest, f = dense_pairs([[2, 1], [1, 2]])
    result = furness(
        origin, dest, f, np.array([60.0, 40.0]), np.array([50.0, 50.0]), tolerance=1e-6,
        max_iterations=1000,
    )  # fmt: skip

    assert result.converged
    assert result.iterations == len(result.row_error_history) < 1000
    assert result.max_row_error <= 1e-6
    assert result.max_column_error <= 1e-12  # columns are exact after the column step


@pytest.mark.parametrize(
    ("o", "d", "message"),
    [([10.0, 10.0], [10.0, 5.0], "must be equal"), ([0.0, 0.0], [0.0, 0.0], "positive")],
)
def test_rejects_unequal_or_empty_totals(o: list[float], d: list[float], message: str) -> None:
    origin, dest, f = dense_pairs([[1, 1], [1, 1]])
    with pytest.raises(DemandError, match=message):
        furness(origin, dest, f, np.array(o), np.array(d), tolerance=1e-6, max_iterations=10)


def test_rejects_a_zone_with_trips_but_no_pair() -> None:
    origin, dest, f = dense_pairs([[1, 0], [1, 0]])
    with pytest.raises(DemandError, match="destination zone"):
        furness(
            origin, dest, f, np.array([5.0, 5.0]), np.array([5.0, 5.0]), tolerance=1e-6,
            max_iterations=10,
        )  # fmt: skip


def test_identical_inputs_give_identical_bytes() -> None:
    origin, dest, f = dense_pairs(exponential(np.arange(9.0).reshape(3, 3), 0.2).tolist())
    o, d = np.array([1.0, 2.0, 3.0]), np.array([3.0, 2.0, 1.0])

    first = furness(origin, dest, f, o, d, tolerance=1e-10, max_iterations=500)
    second = furness(origin, dest, f, o, d, tolerance=1e-10, max_iterations=500)

    assert first.trips.tobytes() == second.trips.tobytes()


def test_warm_start_converges_to_the_same_matrix_in_fewer_iterations() -> None:
    cost = np.array([[5.0, 20.0, 40.0], [20.0, 5.0, 25.0], [40.0, 25.0, 5.0]])
    origin, dest, _ = dense_pairs(np.ones((3, 3)).tolist())
    o, d = np.array([100.0, 200.0, 300.0]), np.array([250.0, 250.0, 100.0])
    near = furness(
        origin, dest, exponential(cost.ravel(), 0.10), o, d, tolerance=1e-12, max_iterations=999
    )

    cold = furness(
        origin, dest, exponential(cost.ravel(), 0.11), o, d, tolerance=1e-12, max_iterations=999
    )
    warm = furness(
        origin, dest, exponential(cost.ravel(), 0.11), o, d, tolerance=1e-12, max_iterations=999,
        initial_b=near.b,
    )  # fmt: skip

    np.testing.assert_allclose(warm.trips, cold.trips, rtol=1e-9)
    assert warm.iterations < cold.iterations
