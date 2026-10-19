"""Crowding-aware assignment by the method of successive averages (Phase 6 M3, ADR 0018).

Each OD pair has up to three alternatives, routed once (``glacies_raptor.ChoiceSet``): the
fastest journey, the fastest on buses only and the fastest with at most one transfer. Their
generalised cost is walking, waiting, riding to a station and transfers weighted as in
``[route_choice]``, fares over the value of time, and in-vehicle minutes times the crowding
multiplier of every segment ridden. Trips split between a pair's alternatives by a logit.

The loop: loads -> multipliers -> costs -> logit shares -> new loads, and the shares are
averaged with step 1/n (MSA). Loads are linear in the shares, so averaging shares averages the
loads exactly. It stops when segment loads change by less than ``[msa] gap`` (relative, L1)
or after ``max_iterations``. Everything is deterministic: no sampling, sums in a fixed order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import glacies_raptor as gr
import numpy as np
import numpy.typing as npt
import polars as pl

from glacies.analytics.travel_times import ZoneWalks
from glacies.assignment.aon import (
    CHUNK_ORIGINS,
    AonFlows,
    AssignmentError,
    by_origin,
    flows_from_totals,
    pair_table,
)
from glacies.assignment.crowding import multipliers
from glacies.assignment.metrics import great_circle_km
from glacies.cities import AssignmentConfig, AssignmentWindow, RideAccess
from glacies.demand.metro import MetroNetwork
from glacies.routing.network import Router

F64 = npt.NDArray[np.float64]
U32 = npt.NDArray[np.uint32]


@dataclass(frozen=True)
class Rows:
    """Per stop-time row (sorted by trip_idx, position): what the loop needs."""

    trip: U32  # trip_idx of the row
    offset: U32  # by trip_idx: first row of the trip
    km: F64  # cumulative straight-line km from the trip's first stop
    seconds: F64  # to the next stop's departure (0 at the last stop)


def row_tables(stop_times: pl.DataFrame, stops: pl.DataFrame) -> Rows:
    table = stop_times.select("trip_idx", "position", "stop_idx", "departure").join(
        stops.select("stop_idx", "lat", "lon"), on="stop_idx", how="left", maintain_order="left"
    )
    nxt = table.select(
        pl.col("lat").shift(-1).over("trip_idx").alias("lat1"),
        pl.col("lon").shift(-1).over("trip_idx").alias("lon1"),
        pl.col("departure").shift(-1).over("trip_idx").alias("dep1"),
    )
    step = great_circle_km(
        table["lat"].to_numpy(),
        table["lon"].to_numpy(),
        nxt["lat1"].fill_null(table["lat"]).to_numpy(),
        nxt["lon1"].fill_null(table["lon"]).to_numpy(),
    )
    km = (
        pl.DataFrame({"trip_idx": table["trip_idx"], "step": step})
        .select((pl.col("step").cum_sum() - pl.col("step")).over("trip_idx"))
        .to_series()
        .to_numpy()
    )
    seconds = (nxt["dep1"].cast(pl.Float64) - table["departure"].cast(pl.Float64)).fill_null(0.0)
    trip = table["trip_idx"].to_numpy().astype(np.uint32)
    firsts = table.with_row_index("row").filter(pl.col("position") == 0)
    offset = np.zeros(int(trip.max()) + 1 if trip.size else 0, dtype=np.uint32)
    offset[firsts["trip_idx"].to_numpy()] = firsts["row"].to_numpy().astype(np.uint32)
    return Rows(trip=trip, offset=offset, km=km, seconds=seconds.to_numpy())


def _fare_rules(
    config: AssignmentConfig, ride: RideAccess | None
) -> tuple[list[float], list[int], list[float]] | None:
    if not config.route_choice.use_fares:
        return None
    f, vot = config.fares, config.value_of_time.inr_per_hour
    penalty_s, speed = (ride.penalty_min * 60, ride.speed_kmh) if ride else (0.0, 1.0)
    scalars = [
        60.0 / vot,
        f.metro.above_inr,
        f.metro.smart_card_discount,
        f.bus.stage_km,
        f.bus.fare_per_stage_inr,
        f.bus.free_share,
        f.ride_access.base_inr,
        f.ride_access.base_km,
        f.ride_access.per_km_inr,
        penalty_s,
        speed,
    ]
    if f.metro.distance != "station_hops":
        raise AssignmentError("only station-hop metro fares are implemented")
    return scalars, [int(b) for b in f.metro.band_km], list(f.metro.fare_inr)


def build_choice_set(
    router: Router,
    walks: ZoneWalks,
    od: pl.DataFrame,
    rows: Rows,
    window: AssignmentWindow,
    metro: MetroNetwork,
    config: AssignmentConfig,
    ride: RideAccess | None,
    max_travel_time_s: int,
    *,
    on_chunk: Callable[[int, int], None] | None = None,
) -> gr.ChoiceSet:
    """Route every pair's alternatives once (purposes summed, as in all-or-nothing)."""
    routing = router.routing
    bus_only = router.timetable.retain_trips((1 - metro.metro_trip).astype(np.uint8))
    origins, dests, trips = by_origin(pair_table(od))
    rc = config.route_choice
    cost = (rc.walk_weight, rc.wait_weight, rc.ride_weight, rc.transfer_penalty_min)
    fares = _fare_rules(config, ride)
    choices = gr.ChoiceSet()
    for start in range(0, len(origins), CHUNK_ORIGINS):
        chunk = range(start, min(start + CHUNK_ORIGINS, len(origins)))
        choices.extend(
            router.timetable,
            bus_only,
            [
                (*walks.access[origins[k]], *walks.walk_only[origins[k]], dests[k], trips[k])
                for k in chunk
            ],
            np.asarray([origins[k] for k in chunk], dtype=np.uint32),
            np.array(window.departures(), dtype=np.uint32),
            np.array(window.weights(), dtype=np.float64),
            len(walks.access),
            *walks.egress,
            metro.metro_trip,
            metro.station,
            rows.offset,
            rows.km,
            cost,
            fares,
            max_travel_time_s,
            routing.max_rounds,
            routing.min_transfer_time_s,
            walks.rides([origins[k] for k in chunk]),
        )
        if on_chunk is not None:
            on_chunk(chunk.stop, len(origins))
    return choices


def _within_trip_cumsum(trip: U32, values: F64, *, exclusive: bool) -> F64:
    """Running sum per trip in row order (rows of a trip are contiguous)."""
    frame = pl.DataFrame({"trip": trip, "v": values})
    total = pl.col("v").cum_sum().over("trip")
    expr = total - pl.col("v") if exclusive else total
    return frame.select(expr).to_series().to_numpy()


@dataclass(frozen=True)
class MsaResult:
    shares: F64  # per alternative, averaged
    boardings: F64
    alightings: F64
    convergence: pl.DataFrame  # iteration, gap, mean_cost_min, max_multiplier
    converged: bool


def run_msa(
    choices: gr.ChoiceSet,
    rows: Rows,
    vehicles: pl.DataFrame,
    config: AssignmentConfig,
    *,
    theta: float | None = None,
    on_iteration: Callable[[int, float], None] | None = None,
) -> MsaResult:
    """``vehicles``: trip_idx, seats, standing_area_m2 for every trip (``trip_vehicles``)."""
    by_trip = vehicles.sort("trip_idx")
    seats_of = np.zeros(rows.offset.size, dtype=np.float64)
    area_of = np.zeros(rows.offset.size, dtype=np.float64)
    ids = by_trip["trip_idx"].to_numpy()
    seats_of[ids] = by_trip["seats"].to_numpy()
    area_of[ids] = by_trip["standing_area_m2"].to_numpy()
    seats, area = seats_of[rows.trip], area_of[rows.trip]
    curve, crush = config.crowding, config.capacity.crush_standing_per_m2
    theta = config.route_choice.theta_per_min if theta is None else theta
    n_rows = rows.trip.size

    def segment_loads(boardings: F64, alightings: F64) -> F64:
        return np.maximum(
            _within_trip_cumsum(rows.trip, boardings - alightings, exclusive=False), 0.0
        )

    def respond(load: F64) -> tuple[F64, F64, float]:
        m = multipliers(load, seats, area, curve, crush)
        crowded = _within_trip_cumsum(rows.trip, rows.seconds * m, exclusive=True)
        costs = choices.costs(crowded, rows.offset)
        return choices.shares(costs, theta), m, float(costs.mean()) if costs.size else 0.0

    zero = np.zeros(n_rows)
    shares, m, mean_cost = respond(zero)  # uncrowded costs
    boardings, alightings = choices.loads(shares, rows.offset, n_rows)
    load = segment_loads(boardings, alightings)
    log = [(0, float("nan"), mean_cost, float(m.max()) if m.size else 1.0)]
    converged = False
    for n in range(1, config.msa.max_iterations + 1):
        target, m, mean_cost = respond(load)
        b, a = choices.loads(target, rows.offset, n_rows)
        new_load = segment_loads(b, a)
        total = float(np.abs(load).sum())
        gap = float(np.abs(new_load - load).sum()) / total if total > 0 else 0.0
        step = 1.0 / (n + 1)
        shares = shares + step * (target - shares)
        boardings, alightings = choices.loads(shares, rows.offset, n_rows)
        load = segment_loads(boardings, alightings)
        log.append((n, gap, mean_cost, float(m.max()) if m.size else 1.0))
        if on_iteration is not None:
            on_iteration(n, gap)
        if gap < config.msa.gap:
            converged = True
            break
    convergence = pl.DataFrame(
        log,
        schema={
            "iteration": pl.UInt32,
            "gap": pl.Float64,
            "mean_cost_min": pl.Float64,
            "max_multiplier": pl.Float64,
        },
        orient="row",
    )
    return MsaResult(
        shares=shares,
        boardings=boardings,
        alightings=alightings,
        convergence=convergence,
        converged=converged,
    )


def msa_flows(od: pl.DataFrame, choices: gr.ChoiceSet, result: MsaResult) -> AonFlows:
    """The averaged assignment in the shape all-or-nothing produces (metrics take either)."""
    origin, dest, transit, walked, unreached = choices.pairs()
    totals, gates = choices.summary(result.shares)
    return flows_from_totals(
        pair_table(od),
        (origin, dest),
        (transit, walked, unreached),
        totals,
        result.boardings,
        result.alightings,
        gates,
    )
