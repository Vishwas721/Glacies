"""Trip productions ``O_i`` and attractions ``D_j`` per zone (Phase 5 M1).

``O_i = population x trip rate x transit share`` and ``D_j`` is the employment proxy scaled
so that ``ΣD = ΣO``, as a doubly constrained gravity model requires. Population and the proxy
are Estimated, the rate and share are Assumed, so both trip ends are **Estimated**.

Only zones with a stop within the access walk take part: in the travel-time matrix every
other zone reaches nothing but the zones it can walk to, so a transit model cannot place its
trips. Zones that take part must also be able to reach each other: an origin with no reachable
destination, or a destination no origin reaches, would make Furness balancing impossible. Those
zones are dropped (repeatedly, since dropping one can strand another) and counted in the stats,
so the trips left out are reported rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import polars as pl
from pydantic import BaseModel

from glacies.cities import DemandConfig
from glacies.provenance import DataNature

F64 = npt.NDArray[np.float64]
BOOL = npt.NDArray[np.bool_]

COLUMN_NATURE: dict[str, DataNature] = {
    "population": DataNature.ESTIMATED,
    "has_access": DataNature.SIMULATED,  # walk network search from the zone point
    "employment_score": DataNature.ESTIMATED,
    "origin": DataNature.ESTIMATED,
    "destination": DataNature.ESTIMATED,
}


class DemandError(ValueError):
    """Demand cannot be estimated from the given inputs."""


def candidate_pairs(
    matrix: pl.LazyFrame, cost_column: str, *, exclude_intrazonal: bool
) -> pl.DataFrame:
    """(origin_zone, dest_zone, cost_s) for every pair the matrix reaches at ``cost_column``."""
    names = matrix.collect_schema().names()
    if cost_column not in names:
        raise DemandError(f"travel-time matrix has no column {cost_column!r}")
    pairs = matrix.select(
        "origin_zone", "dest_zone", pl.col(cost_column).cast(pl.UInt32).alias("cost_s")
    ).filter(pl.col("cost_s").is_not_null())
    if exclude_intrazonal:
        pairs = pairs.filter(pl.col("origin_zone") != pl.col("dest_zone"))
    return pairs.sort("origin_zone", "dest_zone").collect()


def _connected(
    origin: npt.NDArray[np.uint32],
    dest: npt.NDArray[np.uint32],
    produces: BOOL,
    attracts: BOOL,
) -> tuple[BOOL, BOOL]:
    """Shrink both sets until every origin reaches a destination and vice versa."""
    n = produces.size
    while True:
        live = produces[origin] & attracts[dest]
        new_produces = produces & (np.bincount(origin[live], minlength=n) > 0)
        new_attracts = attracts & (np.bincount(dest[live], minlength=n) > 0)
        if (new_produces == produces).all() and (new_attracts == attracts).all():
            return produces, attracts
        produces, attracts = new_produces, new_attracts


class TripEndStats(BaseModel):
    zones: int
    zones_with_access: int
    origin_zones: int
    destination_zones: int
    population: float
    population_with_access: float
    population_unreachable: float  # with access, but no destination reachable
    trips: float  # ΣO = ΣD
    trips_low: float  # trip rate and transit share both at the low end of their ranges
    trips_high: float
    employment_share_kept: float  # share of the city's employment score in destination zones


@dataclass
class TripEnds:
    table: pl.DataFrame
    stats: TripEndStats


def trip_ends(
    zones: pl.DataFrame,
    employment_score: F64,
    has_access: BOOL,
    pairs: pl.DataFrame,
    demand: DemandConfig,
) -> TripEnds:
    """Productions and attractions per zone; ``zones`` is sorted by ``zone_idx`` = position."""
    n = zones.height
    zone_idx = zones["zone_idx"].to_numpy()
    if not np.array_equal(zone_idx, np.arange(n)):
        raise DemandError("zone_idx must be 0..n-1 in order")
    if employment_score.size != n or has_access.size != n:
        raise DemandError("employment score and access flags must cover every zone")
    population = zones["population"].to_numpy().astype(np.float64)
    origin = pairs["origin_zone"].to_numpy().astype(np.uint32)
    dest = pairs["dest_zone"].to_numpy().astype(np.uint32)
    produces, attracts = _connected(
        origin, dest, has_access & (population > 0), has_access & (employment_score > 0)
    )
    if not produces.any():
        raise DemandError("no zone with transit access can reach a zone with employment")

    priors = demand.priors
    rate = priors.trip_rate.value * priors.transit_share.value
    o = np.where(produces, population * rate, 0.0)
    total = float(o.sum())
    score = np.where(attracts, employment_score, 0.0)
    d = score / score.sum() * total
    table = zones.select("zone_idx", "h3_cell").with_columns(
        pl.Series("population", population),
        pl.Series("has_access", has_access),
        pl.Series("employment_score", employment_score),
        pl.Series("origin", o),
        pl.Series("destination", d),
    )
    low = priors.trip_rate.range[0] * priors.transit_share.range[0] / rate
    high = priors.trip_rate.range[1] * priors.transit_share.range[1] / rate
    stats = TripEndStats(
        zones=n,
        zones_with_access=int(has_access.sum()),
        origin_zones=int(produces.sum()),
        destination_zones=int(attracts.sum()),
        population=float(population.sum()),
        population_with_access=float(population[has_access].sum()),
        population_unreachable=float(population[has_access & ~produces].sum()),
        trips=total,
        trips_low=total * low,
        trips_high=total * high,
        employment_share_kept=float(score.sum() / employment_score.sum()),
    )
    return TripEnds(table=table, stats=stats)
