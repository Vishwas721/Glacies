"""All-or-nothing transit assignment of the OD matrix onto scheduled trips (Phase 6 M1).

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

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.analytics.travel_times import ZoneWalks
from glacies.cities import AssignmentWindow, Capacity, Routing
from glacies.fsutil import rename_with_retry
from glacies.provenance import DataNature, sha256_file
from glacies.routing.network import Router

F64 = npt.NDArray[np.float64]
CHUNK_ORIGINS = 256
MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
LOADS_NAME = "loads.parquet"
STOPS_NAME = "stop_flows.parquet"
OD_NAME = "od_assignment.parquet"
# Relative tolerance of the conservation checks (sums of many fractional trips).
CONSERVATION_RTOL = 1e-9

COLUMN_NATURE: dict[str, dict[str, DataNature]] = {
    LOADS_NAME: {
        "boardings": DataNature.SIMULATED,
        "alightings": DataNature.SIMULATED,
        "load": DataNature.SIMULATED,
        "capacity": DataNature.ASSUMED,
        "crush_capacity": DataNature.ASSUMED,
        "load_factor": DataNature.SIMULATED,
        "crush_factor": DataNature.SIMULATED,
    },
    STOPS_NAME: {"boardings": DataNature.SIMULATED, "alightings": DataNature.SIMULATED},
    OD_NAME: {
        "trips": DataNature.ESTIMATED,
        "transit": DataNature.SIMULATED,
        "walked": DataNature.SIMULATED,
        "unreached": DataNature.SIMULATED,
    },
}


class AssignmentError(ValueError):
    """The assignment cannot run or its results fail a conservation check."""


@dataclass(frozen=True)
class AonFlows:
    od: pl.DataFrame  # origin_zone, dest_zone, trips, transit, walked, unreached
    boardings: F64  # per stop_times row (trip_idx, position order)
    alightings: F64


def _row_offsets(stop_times: pl.DataFrame) -> npt.NDArray[np.int64]:
    """Index of each trip's first stop_times row, by trip_idx (rows sorted by trip, position)."""
    firsts = stop_times.with_row_index("row").filter(pl.col("position") == 0)
    offsets = np.full(int(stop_times["trip_idx"].max()) + 1, -1, dtype=np.int64)  # type: ignore[arg-type]
    offsets[firsts["trip_idx"].to_numpy()] = firsts["row"].to_numpy()
    return offsets


def assign_od(
    router: Router,
    walks: ZoneWalks,
    od: pl.DataFrame,
    stop_times: pl.DataFrame,
    window: AssignmentWindow,
    max_travel_time_s: int,
    *,
    on_chunk: Callable[[int, int], None] | None = None,
) -> AonFlows:
    """Assign ``od`` (origin_zone, dest_zone, trips; purposes are summed) onto the trips.

    ``stop_times`` must be sorted by trip_idx and position, as the canonical table is.
    """
    routing: Routing = router.routing
    pairs = (
        od.group_by("origin_zone", "dest_zone")
        .agg(pl.col("trips").sum())
        .filter(pl.col("trips") > 0)
        .sort("origin_zone", "dest_zone")
    )
    grouped = pairs.group_by("origin_zone", maintain_order=True).agg("dest_zone", "trips")
    origins = grouped["origin_zone"].to_list()
    dests = [np.asarray(d, dtype=np.uint32) for d in grouped["dest_zone"].to_list()]
    trips = [np.asarray(t, dtype=np.float64) for t in grouped["trips"].to_list()]
    departures = np.array(window.departures(), dtype=np.uint32)
    weights = np.array(window.weights(), dtype=np.float64)
    offsets = _row_offsets(stop_times)
    boardings = np.zeros(stop_times.height, dtype=np.float64)
    alightings = np.zeros(stop_times.height, dtype=np.float64)
    parts = []
    for start in range(0, len(origins), CHUNK_ORIGINS):
        chunk = range(start, min(start + CHUNK_ORIGINS, len(origins)))
        batch = [
            (*walks.access[origins[k]], *walks.walk_only[origins[k]], dests[k], trips[k])
            for k in chunk
        ]
        (o, zone, transit, walked, unreached), (trip, board, alight, passengers) = (
            router.timetable.zone_assign_many(
                batch,
                departures,
                weights,
                len(walks.access),
                *walks.egress,
                max_travel_time_s,
                routing.max_rounds,
                routing.min_transfer_time_s,
                walks.rides([origins[k] for k in chunk]),
            )
        )
        base = offsets[trip]
        if (base < 0).any():
            raise AssignmentError("a ride references a trip missing from stop_times")
        # Sequential, in origin order: the float sums are the same on every run.
        np.add.at(boardings, base + board, passengers)
        np.add.at(alightings, base + alight, passengers)
        ids = np.asarray([origins[k] for k in chunk], dtype=np.uint32)
        parts.append(
            pl.DataFrame(
                {
                    "origin_zone": ids[o],
                    "dest_zone": zone,
                    "transit": transit,
                    "walked": walked,
                    "unreached": unreached,
                }
            )
        )
        if on_chunk is not None:
            on_chunk(chunk.stop, len(origins))
    columns = ["origin_zone", "dest_zone", "transit", "walked", "unreached"]
    assigned = (
        pl.concat(parts) if parts else pl.DataFrame(schema=dict.fromkeys(columns, pl.Float64))
    )
    result = pairs.join(
        assigned, on=["origin_zone", "dest_zone"], how="left", maintain_order="left"
    )
    return AonFlows(od=result, boardings=boardings, alightings=alightings)


def trip_vehicles(routes: pl.DataFrame, trips: pl.DataFrame, capacity: Capacity) -> pl.DataFrame:
    """trip_idx, vehicle, seats, capacity, crush_capacity for every trip in ``trips``.

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


# --- outputs ----------------------------------------------------------------------------------


class AssignmentInput(BaseModel):
    stage: str
    manifest_sha256: str


class AssignmentManifest(BaseModel):
    city: str
    scenario: str
    builder_version: str
    nature: DataNature
    method: str
    window: str
    report_window: str
    departures: int
    inputs: list[AssignmentInput]
    stats: AonStats
    column_nature: dict[str, dict[str, DataNature]]
    outputs: dict[str, str] = {}


def write_assignment(
    flows: AonFlows,
    loads: pl.DataFrame,
    stops: pl.DataFrame,
    stats: AonStats,
    out_dir: Path,
    *,
    city: str,
    scenario: str,
    window: AssignmentWindow,
    inputs: list[AssignmentInput],
    report: Callable[[AssignmentManifest], str],
) -> AssignmentManifest:
    manifest = AssignmentManifest(
        city=city,
        scenario=scenario,
        builder_version=__version__,
        nature=DataNature.SIMULATED,
        method="all-or-nothing, fastest journey per departure, expected flows",
        window=f"{window.window_start}-{window.window_end}",
        report_window=f"{window.report_start}-{window.report_end}",
        departures=len(window.departures()),
        inputs=inputs,
        stats=stats,
        column_nature=COLUMN_NATURE,
    )
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    outputs = {}
    for name, frame in ((LOADS_NAME, loads), (STOPS_NAME, stops), (OD_NAME, flows.od)):
        # Rechunk so the bytes depend only on the rows (one row group per chunk otherwise).
        frame.rechunk().write_parquet(staging / name, compression="zstd", statistics=True)
        outputs[name] = sha256_file(staging / name)
    manifest = manifest.model_copy(update={"outputs": outputs})
    (staging / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (staging / REPORT_NAME).write_text(report(manifest), encoding="utf-8", newline="\n")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rename_with_retry(staging, out_dir)
    return manifest


def config_input(window: AssignmentWindow, capacity: Capacity) -> AssignmentInput:
    """The settings the outputs depend on (fares and crowding are not used by AON yet)."""
    text = window.model_dump_json() + capacity.model_dump_json()
    return AssignmentInput(
        stage="assignment.toml", manifest_sha256=hashlib.sha256(text.encode()).hexdigest()
    )
