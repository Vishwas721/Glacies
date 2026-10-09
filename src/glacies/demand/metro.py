"""Simulated metro station flows from the OD matrix (Phase 5 M3).

BMRCL counts people at fare gates, so the model is compared with it at the same place: each
OD pair's trips are spread evenly over the departures in the window that reach the
destination within the limit, each departure follows its fastest journey (ties to fewer
vehicles; walking all the way wins if it is as fast), and every metro *segment* of that
journey counts one entry at its first station and one exit at its last. Changing lines
inside a station is not a new entry. This is all-or-nothing on the fastest journey, with no
crowding; Phase 6 replaces it.

The path table (per OD pair: departures reached, departures walked, and departures per
station pair) depends on the network and the zones only, not on how many trips the pair
has. It is computed once and turned into flows for any OD matrix with a join, which is what
β calibration needs. Flows are **Simulated** (they come from routing Estimated demand).
"""

from __future__ import annotations

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
from glacies.cities import Accessibility
from glacies.demand.production import DemandError
from glacies.fsutil import rename_with_retry
from glacies.provenance import DataNature, sha256_file
from glacies.routing.network import Router

U32 = npt.NDArray[np.uint32]
CHUNK_ORIGINS = 256
MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
PATHS_NAME = "metro_paths.parquet"
REACH_NAME = "od_reach.parquet"
FLOWS_NAME = "station_pairs.parquet"
STATIONS_NAME = "stations.parquet"
ACCESS_NAME = "zone_access.parquet"

COLUMN_NATURE: dict[str, dict[str, DataNature]] = {
    PATHS_NAME: {"departures": DataNature.SIMULATED, "share": DataNature.SIMULATED},
    REACH_NAME: {
        "reached": DataNature.SIMULATED,
        "walked": DataNature.SIMULATED,
        "metro": DataNature.SIMULATED,
    },
    FLOWS_NAME: {"trips": DataNature.SIMULATED},
    STATIONS_NAME: {"entries": DataNature.SIMULATED, "exits": DataNature.SIMULATED},
}


@dataclass(frozen=True)
class MetroNetwork:
    metro_trip: npt.NDArray[np.uint8]  # by trip_idx: 1 = runs on a metro route
    station: U32  # by stop_idx: parent station (or the stop itself)
    stations: pl.DataFrame  # station_idx, name, lines: the stations metro trips serve


def metro_network(router: Router, transit_dir: Path, mode: str) -> MetroNetwork:
    """Metro trips and stations of ``mode`` in the canonical network."""
    routes = router.routes.filter(pl.col("mode") == mode).select("route_idx", "short_name")
    if routes.height == 0:
        raise DemandError(f"the network has no {mode} routes")
    trips = router.trips.join(routes, on="route_idx")
    metro_trip = np.zeros(int(router.trips["trip_idx"].to_numpy().max()) + 1, dtype=np.uint8)
    metro_trip[trips["trip_idx"].to_numpy()] = 1
    stops = router.stops.select(
        "stop_idx", pl.coalesce("parent_stop_idx", "stop_idx").alias("station_idx")
    ).sort("stop_idx")
    if not np.array_equal(stops["stop_idx"].to_numpy(), np.arange(stops.height)):
        raise DemandError("stop_idx must be 0..n-1")
    served = (
        pl.read_parquet(transit_dir / "stop_times.parquet", columns=["trip_idx", "stop_idx"])
        .join(trips.select("trip_idx", "short_name"), on="trip_idx")
        .join(stops, on="stop_idx")
        .group_by("station_idx")
        .agg(pl.col("short_name").unique().sort().str.join("+").alias("lines"))
        .join(
            router.stops.select(pl.col("stop_idx").alias("station_idx"), "name"), on="station_idx"
        )
        .select("station_idx", "name", "lines")
        .sort("station_idx")
    )
    return MetroNetwork(
        metro_trip=metro_trip,
        station=stops["station_idx"].to_numpy().astype(np.uint32),
        stations=served,
    )


def metro_paths(
    router: Router,
    walks: ZoneWalks,
    pairs: pl.DataFrame,
    metro: MetroNetwork,
    settings: Accessibility,
    *,
    on_chunk: Callable[[int, int], None] | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(reach, segments) for every (origin_zone, dest_zone) in ``pairs``.

    reach: origin_zone, dest_zone, reached, walked, metro (departures). segments: origin_zone,
    dest_zone, entry_station, exit_station, departures.
    """
    routing = router.routing
    departures = np.array(settings.departures(), dtype=np.uint32)
    targets = pairs.select("origin_zone", "dest_zone").sort("origin_zone", "dest_zone")
    grouped = targets.group_by("origin_zone", maintain_order=True).agg("dest_zone")
    origins = grouped["origin_zone"].to_list()
    dests = [np.asarray(d, dtype=np.uint32) for d in grouped["dest_zone"].to_list()]
    reach_parts, segment_parts = [], []
    for start in range(0, len(origins), CHUNK_ORIGINS):
        chunk = range(start, min(start + CHUNK_ORIGINS, len(origins)))
        batch = [(*walks.access[origins[k]], *walks.walk_only[origins[k]], dests[k]) for k in chunk]
        (o, z, reached, walked, used), (so, sz, entry, exit_, count) = (
            router.timetable.zone_paths_many(
                batch,
                departures,
                len(walks.access),
                *walks.egress,
                metro.metro_trip,
                metro.station,
                settings.max_travel_time_min * 60,
                routing.max_rounds,
                routing.min_transfer_time_s,
            )
        )
        ids = np.asarray([origins[k] for k in chunk], dtype=np.uint32)
        reach_parts.append(
            pl.DataFrame(
                {
                    "origin_zone": ids[o],
                    "dest_zone": z,
                    "reached": reached,
                    "walked": walked,
                    "metro": used,
                }
            )
        )
        segment_parts.append(
            pl.DataFrame(
                {
                    "origin_zone": ids[so],
                    "dest_zone": sz,
                    "entry_station": entry,
                    "exit_station": exit_,
                    "departures": count,
                }
            )
        )
        if on_chunk is not None:
            on_chunk(chunk.stop, len(origins))
    reach = pl.concat(reach_parts).sort("origin_zone", "dest_zone")
    segments = pl.concat(segment_parts).sort(
        "origin_zone", "dest_zone", "entry_station", "exit_station"
    )
    return reach, segments


def walk_pairs(reach: pl.DataFrame) -> pl.DataFrame:
    """Pairs whose fastest journey is on foot at half or more of the departures reaching them."""
    return reach.filter(pl.col("walked") * 2 >= pl.col("reached")).select(
        "origin_zone", "dest_zone"
    )


def path_shares(reach: pl.DataFrame, segments: pl.DataFrame) -> pl.DataFrame:
    """Share of an OD pair's trips on each station pair (departures / departures reached)."""
    return segments.join(
        reach.select("origin_zone", "dest_zone", "reached"), on=["origin_zone", "dest_zone"]
    ).select(
        "origin_zone",
        "dest_zone",
        "entry_station",
        "exit_station",
        "departures",
        (pl.col("departures") / pl.col("reached")).alias("share"),
    )


class FlowStats(BaseModel):
    trips: float
    trips_unreached: float  # OD trips whose pair no departure reaches (should be 0)
    trips_walked: float  # walking all the way is fastest
    trips_using_metro: float  # journeys with at least one metro segment
    entries: float  # Σ segments; above trips_using_metro when a journey re-enters


@dataclass
class StationFlows:
    pairs: pl.DataFrame  # entry_station, exit_station, trips
    stations: pl.DataFrame  # station_idx, name, lines, entries, exits
    stats: FlowStats


def station_flows(
    od: pl.DataFrame, reach: pl.DataFrame, paths: pl.DataFrame, stations: pl.DataFrame
) -> StationFlows:
    """Metro entries, exits and station-pair flows implied by ``od`` (origin, dest, trips)."""
    keys = ["origin_zone", "dest_zone"]
    trips = od.select(*keys, "trips")
    joined = trips.join(reach, on=keys, how="left")
    total = float(trips["trips"].sum())
    unreached = float(joined.filter(pl.col("reached").fill_null(0) == 0)["trips"].sum())
    served = joined.filter(pl.col("reached") > 0)

    def weighted(column: str) -> float:
        return float(
            served.select(pl.col("trips") * pl.col(column) / pl.col("reached")).to_series().sum()
        )

    flows = paths.join(trips, on=keys).with_columns(
        (pl.col("trips") * pl.col("share")).alias("flow")
    )
    pairs = (
        flows.group_by("entry_station", "exit_station")
        .agg(pl.col("flow").sum().alias("trips"))
        .sort("entry_station", "exit_station")
    )
    entries = pairs.group_by(pl.col("entry_station").alias("station_idx")).agg(
        pl.col("trips").sum().alias("entries")
    )
    exits = pairs.group_by(pl.col("exit_station").alias("station_idx")).agg(
        pl.col("trips").sum().alias("exits")
    )
    stations = (
        stations.join(entries, on="station_idx", how="left")
        .join(exits, on="station_idx", how="left")
        .with_columns(pl.col("entries").fill_null(0.0), pl.col("exits").fill_null(0.0))
        .sort("station_idx")
    )
    return StationFlows(
        pairs=pairs,
        stations=stations,
        stats=FlowStats(
            trips=total,
            trips_unreached=unreached,
            trips_walked=weighted("walked"),
            trips_using_metro=weighted("metro"),
            entries=float(pairs["trips"].sum()),
        ),
    )


# --- outputs ----------------------------------------------------------------------------------


class MetroInput(BaseModel):
    stage: str
    manifest_sha256: str


def _write(
    out_dir: Path, tables: dict[str, pl.DataFrame], manifest: BaseModel, report_text: str
) -> dict[str, str]:
    """Write tables, then ``manifest`` (its ``outputs`` filled in) and the report, atomically."""
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    outputs = {}
    for name, frame in tables.items():
        # Rechunk so the bytes depend only on the rows (one row group per chunk otherwise).
        frame.rechunk().write_parquet(staging / name, compression="zstd", statistics=True)
        outputs[name] = sha256_file(staging / name)
    manifest = manifest.model_copy(update={"outputs": outputs})
    (staging / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (staging / REPORT_NAME).write_text(report_text, encoding="utf-8", newline="\n")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rename_with_retry(staging, out_dir)
    return outputs


class PathsManifest(BaseModel):
    city: str
    scenario: str
    builder_version: str
    nature: DataNature
    mode: str
    inputs: list[MetroInput]
    departures: int
    zones_with_access: int
    od_pairs: int
    walk_pairs: int
    metro_path_rows: int
    column_nature: dict[str, dict[str, DataNature]]
    outputs: dict[str, str] = {}


def write_paths(
    access: pl.DataFrame,
    reach: pl.DataFrame,
    paths: pl.DataFrame,
    stations: pl.DataFrame,
    out_dir: Path,
    *,
    city: str,
    scenario: str,
    mode: str,
    departures: int,
    inputs: list[MetroInput],
) -> PathsManifest:
    manifest = PathsManifest(
        city=city,
        scenario=scenario,
        builder_version=__version__,
        nature=DataNature.SIMULATED,
        mode=mode,
        inputs=inputs,
        departures=departures,
        zones_with_access=int(access["has_access"].sum()),
        od_pairs=reach.height,
        walk_pairs=walk_pairs(reach).height,
        metro_path_rows=paths.height,
        column_nature={k: v for k, v in COLUMN_NATURE.items() if k in (PATHS_NAME, REACH_NAME)},
    )
    lines = [
        f"# Journey paths — `{city}` / `{scenario}` (Simulated)",
        "",
        f"Builder {__version__} · {departures} departures per pair · fastest journey each "
        "(all-or-nothing)",
        "",
        f"- Zones with a stop within the access walk: {manifest.zones_with_access:,}.",
        f"- Zone pairs between them reached at the median: {manifest.od_pairs:,}; fastest on "
        f"foot at half or more of the departures: {manifest.walk_pairs:,}.",
        f"- OD-to-{mode}-station-pair rows: {manifest.metro_path_rows:,}.",
        "",
        "These tables do not depend on demand: `glacies build demand` drops the walking pairs "
        "and `glacies build station-flows` turns any OD matrix into station flows with them.",
        "",
    ]
    outputs = _write(
        out_dir,
        {ACCESS_NAME: access, REACH_NAME: reach, PATHS_NAME: paths, STATIONS_NAME: stations},
        manifest,
        "\n".join(lines),
    )
    return manifest.model_copy(update={"outputs": outputs})


class MetroManifest(BaseModel):
    city: str
    scenario: str
    builder_version: str
    nature: DataNature
    mode: str
    inputs: list[MetroInput]
    stats: FlowStats
    column_nature: dict[str, dict[str, DataNature]]
    outputs: dict[str, str] = {}


def write_station_flows(
    flows: StationFlows,
    out_dir: Path,
    *,
    city: str,
    scenario: str,
    mode: str,
    inputs: list[MetroInput],
) -> MetroManifest:
    manifest = MetroManifest(
        city=city,
        scenario=scenario,
        builder_version=__version__,
        nature=DataNature.SIMULATED,
        mode=mode,
        inputs=inputs,
        stats=flows.stats,
        column_nature={k: v for k, v in COLUMN_NATURE.items() if k in (FLOWS_NAME, STATIONS_NAME)},
    )
    outputs = _write(
        out_dir,
        {FLOWS_NAME: flows.pairs, STATIONS_NAME: flows.stations},
        manifest,
        report(manifest, flows),
    )
    return manifest.model_copy(update={"outputs": outputs})


def report(m: MetroManifest, flows: StationFlows) -> str:
    s = m.stats
    top = flows.stations.sort("entries", "station_idx", descending=[True, False]).head(15)
    pairs = (
        flows.pairs.join(
            flows.stations.select(pl.col("station_idx").alias("entry_station"), "name"),
            on="entry_station",
        )
        .join(
            flows.stations.select(
                pl.col("station_idx").alias("exit_station"), pl.col("name").alias("to")
            ),
            on="exit_station",
        )
        .sort("trips", "entry_station", "exit_station", descending=[True, False, False])
        .head(15)
    )
    return "\n".join(
        [
            f"# Simulated {m.mode} station flows — `{m.city}` / `{m.scenario}` (Simulated)",
            "",
            f"Builder {m.builder_version} · paths from `glacies build paths`",
            "",
            "Each OD pair's trips (Estimated) are spread evenly over the departures that reach "
            "it; each departure takes its fastest journey (all-or-nothing, no crowding). One "
            "metro segment = one entry and one exit; line changes inside a station are free.",
            "",
            "## Totals",
            "",
            f"- Trips: {s.trips:,.0f}; walked all the way: {s.trips_walked:,.0f} "
            f"({s.trips_walked / s.trips:.1%}); not reached: {s.trips_unreached:,.0f}.",
            f"- Trips using the {m.mode}: {s.trips_using_metro:,.0f} "
            f"({s.trips_using_metro / s.trips:.1%}); station entries: {s.entries:,.0f}.",
            "",
            "## Busiest entry stations",
            "",
            "| Station | Lines | Entries | Exits |",
            "|---|---|---:|---:|",
            *(
                f"| {r['name']} | {r['lines']} | {r['entries']:,.0f} | {r['exits']:,.0f} |"
                for r in top.iter_rows(named=True)
            ),
            "",
            "## Busiest station pairs",
            "",
            "| From | To | Trips |",
            "|---|---|---:|",
            *(
                f"| {r['name']} | {r['to']} | {r['trips']:,.0f} |"
                for r in pairs.iter_rows(named=True)
            ),
            "",
            "## Column labels",
            "",
            *(
                f"- `{table}` `{column}`: {nature.value}"
                for table, columns in m.column_nature.items()
                for column, nature in columns.items()
            ),
            "",
        ]
    )
