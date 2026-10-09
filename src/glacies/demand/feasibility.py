"""Attainable attractions for a sparse doubly constrained model (Phase 5 M2).

Furness can only meet both margins if every set of destinations can be filled by the origins
that reach it (a transportation-problem condition, checked here as a max flow). On a transit
matrix it often cannot: a zone with a large employment score whose only transit links come from
a few small origins. Then Furness never converges and its balancing factors drift to overflow,
even though its row-exact iterates approach a limit: rows equal to ``O`` and columns as close
to ``D`` as the pairs allow (Gietl & Reffel 2017, "Accumulation points of the iterative
proportional fitting procedure").

This module computes that limit's structure directly. A max flow finds the bottleneck: origins
``S_o`` whose reachable destinations ``S_d`` cannot absorb their trips. In the limit no trips
go from the other origins into ``S_d``, so those pairs are dropped, and each side becomes its
own block with attractions rescaled to its productions. Blocks are split again until each is
feasible. Productions are never changed: trips stay with the homes that make them, and the
attraction totals move only where the network forces it. The trips moved are reported.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.sparse import csr_array
from scipy.sparse.csgraph import breadth_first_order, maximum_flow

F64 = npt.NDArray[np.float64]
U32 = npt.NDArray[np.uint32]
BOOL = npt.NDArray[np.bool_]
_INT32_MAX = 2**31 - 1


@dataclass
class Attainable:
    attractions: F64  # per zone; ΣD = ΣO within every block
    keep: BOOL  # per pair: False where no trips can flow in the balanced limit
    blocks: int
    trips_moved: float  # Σ|D' - D| / 2


def _min_cut(
    origin: U32, dest: U32, productions: F64, attractions: F64, rows: U32, cols: U32
) -> tuple[float, BOOL, BOOL]:
    """Deficit in trips and the source side of the minimal min cut (origins, destinations).

    Works on block-local indices: ``rows``/``cols`` are the block's zones, ``origin``/``dest``
    index into them. Capacities are integers, so trips are scaled to the finest unit that
    keeps the total within int32.
    """
    n_o, n_d = rows.size, cols.size
    o, d = productions[rows], attractions[cols]
    unit = (_INT32_MAX // 4) / max(float(o.sum()), float(d.sum()))
    source, sink = n_o + n_d, n_o + n_d + 1
    cap_o, cap_d = np.floor(o * unit), np.floor(d * unit)
    big = float(min(_INT32_MAX // 2, cap_o.sum() + 1))
    graph = csr_array(
        (
            np.concatenate([cap_o, np.full(origin.size, big), cap_d]).astype(np.int32),
            (
                np.concatenate([np.full(n_o, source), origin, n_o + np.arange(n_d)]),
                np.concatenate([np.arange(n_o), n_o + dest, np.full(n_d, sink)]),
            ),
        ),
        shape=(sink + 1, sink + 1),
    )
    flow = maximum_flow(graph, source, sink)
    residual = csr_array(graph - flow.flow)
    residual.data[residual.data < 0] = 0
    residual.eliminate_zeros()
    reached = breadth_first_order(residual, source, directed=True, return_predecessors=False)
    side = np.zeros(sink + 1, dtype=bool)
    side[reached] = True
    deficit = (min(cap_o.sum(), cap_d.sum()) - flow.flow_value) / unit
    return float(deficit), side[:n_o], side[n_o : n_o + n_d]


def attainable(
    origin: U32, dest: U32, productions: F64, attractions: F64, *, tolerance: float
) -> Attainable:
    """Attractions the pairs can deliver and the pairs that carry trips; see module doc.

    A block counts as feasible when its deficit is at most ``tolerance x`` its trips (the
    integer max flow cannot resolve less).
    """
    n = productions.size
    d_new = attractions.astype(np.float64).copy()
    keep = np.ones(origin.size, dtype=bool)
    stack = [np.arange(origin.size)]
    blocks = 0
    while stack:
        pair_idx = stack.pop()
        pair_idx = pair_idx[keep[pair_idx]]
        rows = np.unique(origin[pair_idx]).astype(np.uint32)
        cols = np.unique(dest[pair_idx]).astype(np.uint32)
        total = float(productions[rows].sum())
        d_new[cols] *= total / d_new[cols].sum()
        local_o = np.searchsorted(rows, origin[pair_idx]).astype(np.uint32)
        local_d = np.searchsorted(cols, dest[pair_idx]).astype(np.uint32)
        deficit, s_o, s_d = _min_cut(local_o, local_d, productions, d_new, rows, cols)
        if deficit <= tolerance * total or not s_o.any() or s_o.all():
            blocks += 1
            continue
        # No trips from the sink-side origins into the bottleneck's destinations.
        cross = ~s_o[local_o] & s_d[local_d]
        keep[pair_idx[cross]] = False
        inside = s_o[local_o] & s_d[local_d]
        outside = ~s_o[local_o] & ~s_d[local_d]
        stack += [pair_idx[outside], pair_idx[inside]]
    zero = np.bincount(dest[keep], minlength=n) == 0
    d_new[zero] = 0.0
    return Attainable(
        attractions=d_new,
        keep=keep,
        blocks=blocks,
        trips_moved=float(np.abs(d_new - attractions).sum() / 2),
    )
