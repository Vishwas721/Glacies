"""All-or-nothing transit assignment of the OD matrix onto scheduled trips (Phase 6 M1-M2).

Each OD pair's trips leave home over the assignment window in proportion to the departure
profile (``assignment.toml``), only at departures that reach the destination within the time
limit, and each departure takes its fastest journey: the rule of the travel-time matrix and
the Phase 5 path table, with the same walks and rides to stations as demand. Flows are expected
values rather than sampled passengers, so totals are exact and runs are byte-identical.

Loads are passengers on each trip segment (between consecutive stops of a trip), compared with
the vehicle's capacity at design standing density and at crush density. Nothing here reacts to
crowding yet (M3). Every flow is **Simulated**: Estimated demand routed on the timetable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import polars as pl
from pydantic import BaseModel

from glacies.analytics.travel_times import ZoneWalks
from glacies.cities import AssignmentWindow, Capacity, Routing
from glacies.routing.network import Router

F64 = npt.NDArray[np.float64]
U32 = npt.NDArray[np.uint32]
CHUNK_ORIGINS = 256
# Per transit trip of each pair, in this column order from the router (seconds, count, trips).
JOURNEY_COLUMNS = ("in_vehicle", "waiting", "walking", "riding", "vehicles", "ridden")
# Relative tolerance of the conservation checks (sums of many fractional trips).
CONSERVATION_RTOL = 1e-9


class AssignmentError(ValueError):
    """The assignment cannot run or its results fail a conservation check."""


@dataclass(frozen=True)
class AonFlows:
    # origin_zone, dest_zone, trips, transit, walked, unreached; per transit trip of the pair
    # (null without one): in_vehicle_min, waiting_min, walking_min, riding_min, vehicles; and
    # ridden, the trips whose journey starts with a ride to a station.
    od: pl.DataFrame
    boardings: F64  # per stop_times row (trip_idx, position order)
    alightings: F64
    gates: pl.DataFrame  # entry_station, exit_station, trips: metro fare-gate passes


def _row_offsets(stop_times: pl.DataFrame) -> npt.NDArray[np.int64]:
    """Index of each trip's first stop_times row, by trip_idx (rows sorted by trip, position)."""
    firsts = stop_times.with_row_index("row").filter(pl.col("position") == 0)
    offsets = np.full(int(stop_times["trip_idx"].max()) + 1, -1, dtype=np.int64)  # type: ignore[arg-type]
    offsets[firsts["trip_idx"].to_numpy()] = firsts["row"].to_numpy()
    return offsets


def pair_table(od: pl.DataFrame) -> pl.DataFrame:
    """origin_zone, dest_zone, trips: purposes summed, empty pairs dropped, sorted."""
    return (
        od.group_by("origin_zone", "dest_zone")
        .agg(pl.col("trips").sum())
        .filter(pl.col("trips") > 0)
        .sort("origin_zone", "dest_zone")
    )


def by_origin(pairs: pl.DataFrame) -> tuple[list[int], list[U32], list[F64]]:
    """Origins in order, with their destinations and trips (the router's batch layout)."""
    grouped = pairs.group_by("origin_zone", maintain_order=True).agg("dest_zone", "trips")
    return (
        grouped["origin_zone"].to_list(),
        [np.asarray(d, dtype=np.uint32) for d in grouped["dest_zone"].to_list()],
        [np.asarray(t, dtype=np.float64) for t in grouped["trips"].to_list()],
    )


def flows_from_totals(
    pairs: pl.DataFrame,
    order: tuple[U32, U32],
    outcomes: tuple[F64, F64, F64],
    totals: F64,
    boardings: F64,
    alightings: F64,
    gates: tuple[U32, U32, F64],
) -> AonFlows:
    """Assemble flows from the router's per-pair results.

    ``order`` (origin, destination per row) must match ``pairs``; ``outcomes`` are transit,
    walked and unreached trips; ``totals`` the ``(pairs, 6)`` trip-weighted sums.
    """
    origin, dest = order
    if not (
        np.array_equal(origin, pairs["origin_zone"].to_numpy())
        and np.array_equal(dest, pairs["dest_zone"].to_numpy())
    ):
        raise AssignmentError("the router returned pairs in a different order")
    transit, walked, unreached = outcomes
    sums = {f"_{name}": totals[:, i] for i, name in enumerate(JOURNEY_COLUMNS)}

    def per_trip(name: str, scale: float) -> pl.Expr:
        return (
            pl.when(pl.col("transit") > 0)
            .then(pl.col(f"_{name}") / pl.col("transit") / scale)
            .otherwise(None)
        )

    od = (
        pairs.with_columns(
            pl.Series("transit", transit, dtype=pl.Float64),
            pl.Series("walked", walked, dtype=pl.Float64),
            pl.Series("unreached", unreached, dtype=pl.Float64),
            *(pl.Series(k, v, dtype=pl.Float64) for k, v in sums.items()),
        )
        .with_columns(
            *(per_trip(name, 60.0).alias(f"{name}_min") for name in JOURNEY_COLUMNS[:4]),
            per_trip("vehicles", 1.0).alias("vehicles"),
            pl.col("_ridden").alias("ridden"),
        )
        .drop(list(sums))
    )
    entry, exit_, trips = gates
    gate_table = pl.DataFrame(
        {"entry_station": entry, "exit_station": exit_, "trips": trips},
        schema={"entry_station": pl.UInt32, "exit_station": pl.UInt32, "trips": pl.Float64},
    ).sort("entry_station", "exit_station")
    return AonFlows(od=od, boardings=boardings, alightings=alightings, gates=gate_table)


def assign_od(
    router: Router,
    walks: ZoneWalks,
    od: pl.DataFrame,
    stop_times: pl.DataFrame,
    window: AssignmentWindow,
    max_travel_time_s: int,
    metro_trip: npt.NDArray[np.uint8],
    station: U32,
    *,
    on_chunk: Callable[[int, int], None] | None = None,
) -> AonFlows:
    """Assign ``od`` (origin_zone, dest_zone, trips; purposes are summed) onto the trips.

    ``stop_times`` must be sorted by trip_idx and position, as the canonical table is.
    ``metro_trip`` (by trip_idx) and ``station`` (by stop_idx) define the metro's fare gates.
    """
    routing: Routing = router.routing
    pairs = pair_table(od)
    origins, dests, trips = by_origin(pairs)
    departures = np.array(window.departures(), dtype=np.uint32)
    weights = np.array(window.weights(), dtype=np.float64)
    offsets = _row_offsets(stop_times)
    boardings = np.zeros(stop_times.height, dtype=np.float64)
    alightings = np.zeros(stop_times.height, dtype=np.float64)
    columns: list[list[npt.NDArray[np.generic]]] = [[] for _ in range(6)]
    gates: dict[tuple[int, int], float] = {}
    for start in range(0, len(origins), CHUNK_ORIGINS):
        chunk = range(start, min(start + CHUNK_ORIGINS, len(origins)))
        batch = [
            (*walks.access[origins[k]], *walks.walk_only[origins[k]], dests[k], trips[k])
            for k in chunk
        ]
        (o, zone, transit, walked, unreached), totals, rides, passes = (
            router.timetable.zone_assign_many(
                batch,
                departures,
                weights,
                len(walks.access),
                *walks.egress,
                metro_trip,
                station,
                max_travel_time_s,
                routing.max_rounds,
                routing.min_transfer_time_s,
                walks.rides([origins[k] for k in chunk]),
            )
        )
        trip, board, alight, passengers = rides
        base = offsets[trip]
        if (base < 0).any():
            raise AssignmentError("a ride references a trip missing from stop_times")
        # Sequential, in origin order: the float sums are the same on every run.
        np.add.at(boardings, base + board, passengers)
        np.add.at(alightings, base + alight, passengers)
        for entry, exit_, n in zip(*passes, strict=True):
            key = (int(entry), int(exit_))
            gates[key] = gates.get(key, 0.0) + float(n)
        ids = np.asarray([origins[k] for k in chunk], dtype=np.uint32)
        parts: list[npt.NDArray[np.generic]] = [ids[o], zone, transit, walked, unreached, totals]
        for column, values in zip(columns, parts, strict=True):
            column.append(values)
        if on_chunk is not None:
            on_chunk(chunk.stop, len(origins))
    if not columns[0]:
        empty_u32, empty = np.zeros(0, np.uint32), np.zeros(0)
        columns = [[empty_u32], [empty_u32], [empty], [empty], [empty], [np.zeros((0, 6))]]
    o_all, z_all, t_all, w_all, u_all, totals_all = (np.concatenate(c) for c in columns)
    keys = sorted(gates)
    return flows_from_totals(
        pairs,
        (o_all.astype(np.uint32), z_all.astype(np.uint32)),
        (t_all, w_all, u_all),
        totals_all,
        boardings,
        alightings,
        (
            np.array([k[0] for k in keys], dtype=np.uint32),
            np.array([k[1] for k in keys], dtype=np.uint32),
            np.array([gates[k] for k in keys], dtype=np.float64),
        ),
    )


def trip_vehicles(routes: pl.DataFrame, trips: pl.DataFrame, capacity: Capacity) -> pl.DataFrame:
    """trip_idx, vehicle, seats, standing_area_m2, capacity, crush_capacity per trip.

    Standees are whole people: ``floor(density x standing area)``.
    """
    trips = trips.select("trip_idx", "route_idx").join(
        routes.select("route_idx", "mode", "short_name", "route_number"), on="route_idx"
    )
    missing = sorted(set(trips["mode"].unique().to_list()) - {v.mode for v in capacity.vehicles})
    if missing:
        raise AssignmentError(f"assignment.toml has no vehicle for modes: {', '.join(missing)}")
    vehicle = pl.lit(None, dtype=pl.String)
    for v in reversed([v for v in capacity.vehicles if v.is_default]):
        vehicle = pl.when(pl.col("mode") == v.mode).then(pl.lit(v.name)).otherwise(vehicle)
    # Filtered vehicles override the default; the first match in the file wins.
    for v in reversed([v for v in capacity.vehicles if not v.is_default]):
        match = pl.col("short_name").is_in(v.route_short_names)
        for prefix in v.route_prefixes:
            match = match | pl.col("route_number").fill_null("").str.starts_with(prefix)
        vehicle = (
            pl.when((pl.col("mode") == v.mode) & match).then(pl.lit(v.name)).otherwise(vehicle)
        )
    sizes = pl.DataFrame(
        {
            "vehicle": [v.name for v in capacity.vehicles],
            "seats": [v.seats for v in capacity.vehicles],
            "standing_area_m2": [v.standing_area_m2 for v in capacity.vehicles],
            "capacity": [
                v.seats + int(capacity.design_standing_per_m2 * v.standing_area_m2)
                for v in capacity.vehicles
            ],
            "crush_capacity": [
                v.seats + int(capacity.crush_standing_per_m2 * v.standing_area_m2)
                for v in capacity.vehicles
            ],
        },
        schema={
            "vehicle": pl.String,
            "seats": pl.UInt32,
            "standing_area_m2": pl.Float64,
            "capacity": pl.UInt32,
            "crush_capacity": pl.UInt32,
        },
    )
    return (
        trips.select("trip_idx", vehicle.alias("vehicle"))
        .join(sizes, on="vehicle", how="left")
        .sort("trip_idx")
    )


def segment_loads(
    stop_times: pl.DataFrame, flows: AonFlows, vehicles: pl.DataFrame
) -> pl.DataFrame:
    """Passengers on board between each stop and the next, per trip (the last stop has none)."""
    table = (
        stop_times.select("trip_idx", "position", "stop_idx", "arrival", "departure")
        .with_columns(
            pl.Series("boardings", flows.boardings), pl.Series("alightings", flows.alightings)
        )
        .with_columns(
            (pl.col("boardings") - pl.col("alightings")).cum_sum().over("trip_idx").alias("load"),
            pl.col("stop_idx").shift(-1).over("trip_idx").alias("to_stop_idx"),
            pl.col("arrival").shift(-1).over("trip_idx").alias("to_arrival"),
        )
    )
    last = table.filter(pl.col("to_stop_idx").is_null())
    if not np.allclose(last["load"].to_numpy(), 0.0, atol=1e-6):
        raise AssignmentError("passengers are still on board at the end of a trip")
    return (
        table.filter(pl.col("to_stop_idx").is_not_null())
        .join(vehicles, on="trip_idx", how="left")
        .with_columns(
            pl.col("load").clip(lower_bound=0.0),  # rounding noise of the running sum
        )
        .with_columns(
            (pl.col("load") / pl.col("capacity")).alias("load_factor"),
            (pl.col("load") / pl.col("crush_capacity")).alias("crush_factor"),
        )
        .select(
            "trip_idx",
            "position",
            pl.col("stop_idx").alias("from_stop_idx"),
            pl.col("to_stop_idx").cast(pl.UInt32),
            "departure",
            pl.col("to_arrival").cast(pl.UInt32).alias("arrival"),
            "boardings",
            "alightings",
            "load",
            "vehicle",
            "seats",
            "capacity",
            "crush_capacity",
            "load_factor",
            "crush_factor",
        )
        .sort("trip_idx", "position")
    )


def stop_flows(stop_times: pl.DataFrame, flows: AonFlows) -> pl.DataFrame:
    """stop_idx, boardings, alightings: every trip calling at the stop, summed."""
    return (
        stop_times.select("stop_idx")
        .with_columns(
            pl.Series("boardings", flows.boardings), pl.Series("alightings", flows.alightings)
        )
        .group_by("stop_idx")
        .agg(pl.col("boardings").sum(), pl.col("alightings").sum())
        .filter((pl.col("boardings") > 0) | (pl.col("alightings") > 0))
        .sort("stop_idx")
    )


# --- checks and summary ---------------------------------------------------------------------


class AonStats(BaseModel):
    trips: float  # OD trips (Estimated)
    trips_transit: float
    trips_walked: float  # walking all the way is at least as fast
    trips_unreached: float  # no departure in the window arrives within the limit
    boardings: float  # Σ boardings = Σ alightings; above trips_transit by the transfers
    transfers_per_transit_trip: float
    passenger_hours: float  # in vehicles, Σ load x segment time
    peak_segments: int  # segments leaving a stop in the report window
    peak_segments_over_capacity: int
    peak_segments_over_crush: int


def check_and_summarise(
    flows: AonFlows, loads: pl.DataFrame, report_window: tuple[int, int]
) -> AonStats:
    """Conservation checks; raises :class:`AssignmentError` if demand leaked anywhere."""
    od = flows.od
    trips = od["trips"].to_numpy()
    accounted = (od["transit"] + od["walked"] + od["unreached"]).to_numpy()
    if not np.allclose(accounted, trips, rtol=CONSERVATION_RTOL, atol=1e-12):
        raise AssignmentError("transit + walked + unreached trips differ from the OD trips")
    boardings, alightings = float(flows.boardings.sum()), float(flows.alightings.sum())
    if not np.isclose(boardings, alightings, rtol=CONSERVATION_RTOL):
        raise AssignmentError(f"boardings {boardings} differ from alightings {alightings}")
    transit = float(od["transit"].sum())
    start, end = report_window
    peak = loads.filter((pl.col("departure") >= start) & (pl.col("departure") < end))
    seconds = (loads["arrival"].cast(pl.Int64) - loads["departure"].cast(pl.Int64)).to_numpy()
    return AonStats(
        trips=float(trips.sum()),
        trips_transit=transit,
        trips_walked=float(od["walked"].sum()),
        trips_unreached=float(od["unreached"].sum()),
        boardings=boardings,
        transfers_per_transit_trip=boardings / transit - 1.0 if transit > 0 else 0.0,
        passenger_hours=float((loads["load"].to_numpy() * seconds).sum() / 3600),
        peak_segments=peak.height,
        peak_segments_over_capacity=peak.filter(pl.col("load_factor") > 1).height,
        peak_segments_over_crush=peak.filter(pl.col("crush_factor") > 1).height,
    )
