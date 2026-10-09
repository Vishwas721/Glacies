"""Doubly constrained gravity model with Furness balancing (Phase 5 M2).

``T_ij = a_i b_j f(c_ij)`` with ``f(c) = exp(-β c)``, where the balancing factors make every
row sum to ``O_i`` and every column sum to ``D_j`` (Ortúzar & Willumsen, ch. 5). The matrix is
sparse: only pairs the travel-time matrix reaches get trips, so the model works on parallel
arrays of pairs and sums with ``np.bincount`` instead of dense ``n x n`` arrays (10k zones
would be 100M cells).

Furness alternates ``a = O / (F b)`` and ``b = D / (Fᵀ a)``. After each column step the column
sums are exact, so convergence is judged on the row sums. A sparse pattern can make the targets
impossible to meet together (a destination reachable from one small origin only); then the
error stops falling and the result says it did not converge rather than looping forever.
Trips are **Estimated**.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from glacies.demand.production import DemandError

F64 = npt.NDArray[np.float64]
U32 = npt.NDArray[np.uint32]


def exponential(cost_min: F64, beta_per_min: float) -> F64:
    """Friction ``exp(-β c)``; β is per minute, so ``1/β`` is a characteristic trip time."""
    return np.exp(-beta_per_min * cost_min)


@dataclass
class Balanced:
    trips: F64  # per pair, aligned with the input arrays
    iterations: int
    converged: bool
    max_row_error: float  # largest |row sum - O| / O over producing zones
    max_column_error: float
    row_error_history: list[float] = field(default_factory=list)


def _relative_error(actual: F64, target: F64) -> float:
    active = target > 0
    if not active.any():
        return 0.0
    return float(np.max(np.abs(actual[active] - target[active]) / target[active]))


def furness(
    origin: U32,
    dest: U32,
    friction: F64,
    productions: F64,
    attractions: F64,
    *,
    tolerance: float,
    max_iterations: int,
) -> Balanced:
    """Balance ``friction`` on the pairs (origin, dest) to the given trip ends."""
    n = productions.size
    if attractions.size != n:
        raise DemandError("productions and attractions must cover the same zones")
    if not (origin.size == dest.size == friction.size):
        raise DemandError("pair arrays must have the same length")
    total_o, total_d = float(productions.sum()), float(attractions.sum())
    if total_o <= 0 or abs(total_o - total_d) > 1e-9 * total_o:
        raise DemandError(f"ΣO ({total_o:.6g}) and ΣD ({total_d:.6g}) must be equal and positive")
    keep = (friction > 0) & (productions[origin] > 0) & (attractions[dest] > 0)
    o_idx, d_idx, f = origin[keep], dest[keep], friction[keep]
    for name, ends, idx in (("origin", productions, o_idx), ("destination", attractions, d_idx)):
        stranded = (ends > 0) & (np.bincount(idx, minlength=n) == 0)
        if stranded.any():
            raise DemandError(f"{int(stranded.sum())} {name} zone(s) have trips but no pair")

    a = np.zeros(n)
    b = np.where(attractions > 0, 1.0, 0.0)
    history: list[float] = []
    row_error = np.inf
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        row_supply = np.bincount(o_idx, weights=f * b[d_idx], minlength=n)
        a = np.divide(productions, row_supply, out=np.zeros(n), where=productions > 0)
        column_supply = np.bincount(d_idx, weights=f * a[o_idx], minlength=n)
        b = np.divide(attractions, column_supply, out=np.zeros(n), where=attractions > 0)
        rows = np.bincount(o_idx, weights=a[o_idx] * b[d_idx] * f, minlength=n).astype(np.float64)
        row_error = _relative_error(rows, productions)
        history.append(row_error)
        if row_error <= tolerance:
            break

    trips = np.zeros(origin.size)
    trips[keep] = a[o_idx] * b[d_idx] * f
    columns = np.bincount(dest, weights=trips, minlength=n).astype(np.float64)
    return Balanced(
        trips=trips,
        iterations=iteration,
        converged=row_error <= tolerance,
        max_row_error=row_error,
        max_column_error=_relative_error(columns, attractions),
        row_error_history=history,
    )
