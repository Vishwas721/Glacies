"""What the optimiser needs to know about each trunk route, measured on the baseline.

Round-trip time and the current headway come from the timetable (Observed), layovers are
Assumed, vehicles are Estimated from both (vehicles = ceil(round trip / headway)), and the
route's peak-hour use of capacity comes from the baseline assignment (Simulated).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from glacies.optimise.config import Optimise
from glacies.scenario.schema import ModifyHeadway, Scenario, ScenarioError, resolve


class OptimiseError(Exception):
    """An optimisation problem that cannot be set up on this network."""


@dataclass(frozen=True)
class RouteFacts:
    route_id: str
    label: str
    route_idx: int
    directions: int
    running_s: float  # mean running time, summed over directions (Observed timetable)
    cycle_s: float  # running_s + a layover per terminal (Assumed)
    headway_now_s: float  # busier direction, over the assignment window (Observed timetable)
    utilisation: float  # peak-hour passenger-km / design capacity-km, baseline (Simulated)

    def vehicles(self, headway_s: float) -> int:
        """Vehicles to run every ``headway_s`` (Estimated)."""
        return math.ceil(self.cycle_s / headway_s - 1e-9)

    def load_factor(self, headway_s: float) -> float:
        """Peak-hour use of capacity at ``headway_s`` if the route kept its baseline riders
        (Estimated): fewer vehicles carry the same passengers."""
        return self.utilisation * headway_s / self.headway_now_s


def _first_departures(tables: Mapping[str, pl.DataFrame], route_idx: int) -> pl.DataFrame:
    """trip_idx, pattern_idx, direction_id, first departure and last arrival of a route."""
    trips = tables["trips"].filter(pl.col("route_idx") == route_idx)
    return (
        tables["stop_times"]
        .join(trips.select("trip_idx", "pattern_idx", "direction_id"), on="trip_idx")
        .group_by("trip_idx", "pattern_idx", "direction_id")
        .agg(pl.col("departure").min().alias("first"), pl.col("arrival").max().alias("last"))
        .sort("trip_idx")
    )


def route_facts(
    tables: Mapping[str, pl.DataFrame],
    loads: pl.DataFrame,
    optimise: Optimise,
    *,
    assignment_window: tuple[int, int],
    report_window: tuple[int, int],
) -> list[RouteFacts]:
    """Facts for each configured route, in configuration order.

    ``loads`` are the baseline assignment's segment loads (``loads.parquet``). A route must
    have exactly one stop pattern per direction inside the optimiser's window: the headway
    mutation spaces each pattern on its own, so a second pattern would double the service.
    """
    probe = Scenario(
        schema_version=1,
        scenario_id="optimise-routes",
        title="Optimiser routes",
        mutations=[
            ModifyHeadway(type="modify_headway", route_id=r.route_id, feed=r.feed, headway_secs=60)
            for r in optimise.routes
        ],
    )
    try:
        resolved = resolve(probe, tables)
    except ScenarioError as exc:
        raise OptimiseError(str(exc)) from exc
    start, end = optimise.window_s()
    a_start, a_end = assignment_window
    r_start, r_end = report_window
    trip_route = tables["trips"].select("trip_idx", "route_idx")
    peak = loads.filter((pl.col("departure") >= r_start) & (pl.col("departure") < r_end)).join(
        trip_route, on="trip_idx"
    )
    facts = []
    for route in optimise.routes:
        idx = resolved.route_idx[route.route_id]
        trips = _first_departures(tables, idx)
        window = trips.filter((pl.col("first") >= start) & (pl.col("first") < end))
        per_direction = window.group_by("direction_id").agg(
            pl.col("pattern_idx").n_unique().alias("patterns"),
            ((pl.col("last") - pl.col("first")).cast(pl.Float64).mean()).alias("running"),
        )
        if per_direction.height == 0:
            raise OptimiseError(f"route {route.label} has no trips in {optimise.window}")
        if (per_direction["patterns"] > 1).any():
            raise OptimiseError(
                f"route {route.label} has several stop patterns in one direction inside "
                f"{optimise.window}; the optimiser needs one per direction"
            )
        busiest = (
            trips.filter((pl.col("first") >= a_start) & (pl.col("first") < a_end))
            .group_by("direction_id")
            .len()["len"]
            .max()
        )
        if not isinstance(busiest, int) or busiest == 0:
            raise OptimiseError(f"route {route.label} has no trips in the assignment window")
        route_loads = peak.filter(pl.col("route_idx") == idx)
        capacity_km = float((route_loads["capacity"] * route_loads["km"]).sum())
        if capacity_km <= 0:
            raise OptimiseError(f"route {route.label} runs no vehicles in the report hour")
        running = float(per_direction["running"].sum())
        facts.append(
            RouteFacts(
                route_id=route.route_id,
                label=route.label,
                route_idx=idx,
                directions=per_direction.height,
                running_s=running,
                cycle_s=running + per_direction.height * optimise.layover_min * 60,
                headway_now_s=(a_end - a_start) / busiest,
                utilisation=float((route_loads["load"] * route_loads["km"]).sum()) / capacity_km,
            )
        )
    return facts
