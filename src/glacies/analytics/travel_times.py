"""Zone-to-zone transit travel-time matrix over a departure window (Phase 3 M2).

Each zone is represented by its population-weighted point (its cell centre if nobody lives
there). From every origin zone the Rust router runs a range search over every departure in the
window, reaches destination zones through egress walks from nearby stops or on foot all the
way, and reports nearest-rank percentiles of the door-to-door time (waiting included). A zone
reaches itself in 0 s.

Results are **Simulated** and go to ``tt_matrix/<scenario>/part-*.parquet``, one row per
(origin, destination) pair whose lowest percentile is within ``max_travel_time_min``; higher
percentiles above it are null ("not reached"). Origins are processed in fixed-size chunks so
memory stays flat, and the output is identical for identical inputs.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import glacies_raptor as gr
import numpy as np
import numpy.typing as npt
import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.cities import Accessibility, Routing
from glacies.fsutil import rename_with_retry
from glacies.provenance import DataNature, sha256_file
from glacies.routing.network import Router, walk_seconds

U32 = npt.NDArray[np.uint32]
MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
CHUNK_ORIGINS = 256


class MatrixError(ValueError):
    """The travel-time matrix cannot be built from the given inputs."""


def zone_points(zones: pl.DataFrame) -> pl.DataFrame:
    """One point per zone: population-weighted where people live, else the cell centre."""
    weighted = pl.col("pop_lat").is_not_null()
    return zones.sort("zone_idx").select(
        "zone_idx",
        pl.when(weighted).then(pl.col("pop_lat")).otherwise(pl.col("lat")).alias("lat"),
        pl.when(weighted).then(pl.col("pop_lon")).otherwise(pl.col("lon")).alias("lon"),
        pl.when(weighted).then(pl.lit("population")).otherwise(pl.lit("centre")).alias("point"),
    )


@dataclass
class ZoneWalks:
    """Walks between zone points and stops, and between zone points directly."""

    access: list[tuple[U32, U32]]  # per zone: stops, seconds (also the egress walks)
    walk_only: list[tuple[U32, U32]]  # per zone: zones, seconds (including itself at 0 s)
    egress: tuple[U32, U32, U32] = field(init=False)  # (zone, stop, seconds), zone-major
    # Per zone: board-only rides to stations at the origin (glacies.demand.access); not egress.
    ride: list[tuple[U32, U32]] | None = None

    def rides(self, origins: Sequence[int]) -> list[tuple[U32, U32]] | None:
        return None if self.ride is None else [self.ride[o] for o in origins]

    def __post_init__(self) -> None:
        sizes = [stops.size for stops, _ in self.access]
        zones = np.repeat(np.arange(len(self.access), dtype=np.uint32), sizes)
        stops = np.concatenate([s for s, _ in self.access] or [np.zeros(0, np.uint32)])
        secs = np.concatenate([t for _, t in self.access] or [np.zeros(0, np.uint32)])
        self.egress = (zones, stops.astype(np.uint32), secs.astype(np.uint32))


def _flatten(per_zone: list[tuple[U32, U32]], column: str) -> pl.DataFrame:
    sizes = [ids.size for ids, _ in per_zone]
    empty = np.zeros(0, np.uint32)
    return pl.DataFrame(
        {
            "zone": np.repeat(np.arange(len(per_zone), dtype=np.uint32), sizes),
            column: np.concatenate([ids for ids, _ in per_zone] or [empty]).astype(np.uint32),
            "seconds": np.concatenate([t for _, t in per_zone] or [empty]).astype(np.uint32),
        }
    )


def _split(frame: pl.DataFrame, column: str, zones: int) -> list[tuple[U32, U32]]:
    """Inverse of ``_flatten``: rows are zone-major and keep their order within a zone."""
    zone = frame["zone"].to_numpy()
    ids = frame[column].to_numpy().astype(np.uint32)
    secs = frame["seconds"].to_numpy().astype(np.uint32)
    bounds = np.searchsorted(zone, np.arange(zones + 1), side="left")
    return [(ids[bounds[i] : bounds[i + 1]], secs[bounds[i] : bounds[i + 1]]) for i in range(zones)]


def save_walks(walks: ZoneWalks, out_dir: Path) -> None:
    """Store walks so later runs over the same walk network and zones can skip computing them."""
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    _flatten(walks.access, "stop").write_parquet(staging / "access.parquet", compression="zstd")
    _flatten(walks.walk_only, "to_zone").write_parquet(
        staging / "walk_only.parquet", compression="zstd"
    )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    rename_with_retry(staging, out_dir)


def load_walks(directory: Path, zones: int) -> ZoneWalks:
    return ZoneWalks(
        access=_split(pl.read_parquet(directory / "access.parquet"), "stop", zones),
        walk_only=_split(pl.read_parquet(directory / "walk_only.parquet"), "to_zone", zones),
    )


def zone_walks(
    router: Router, walk_dir: Path, points: pl.DataFrame, settings: Accessibility
) -> ZoneWalks:
    """Access walks to stops and zone-to-zone walks for every zone point.

    The walk network is undirected, so a zone's access walks are also its egress walks.
    """
    routing = router.routing
    edge, fraction, snap = router.attach(points["lat"].to_numpy(), points["lon"].to_numpy())
    access = _access_walks(router, edge, fraction, snap)
    nodes = pl.read_parquet(walk_dir / "nodes.parquet", columns=["node_idx"])
    edges = pl.read_parquet(walk_dir / "edges.parquet")
    zone_graph = gr.WalkGraph(
        nodes.height,
        edges["from_node"].to_numpy().astype(np.uint32),
        edges["to_node"].to_numpy().astype(np.uint32),
        edges["length_m"].to_numpy().astype(np.float64),
    )
    zone_ids = points["zone_idx"].to_numpy().astype(np.uint32)
    zone_graph.attach_stops(zone_ids, edge, fraction, snap)
    walk_only = []
    for i, own in enumerate(zone_ids):
        e, f, s = int(edge[i]), float(fraction[i]), float(snap[i])
        zones, zone_m = zone_graph.stops_within(e, f, s, settings.max_walk_only_m)
        seconds = walk_seconds(zone_m, routing.walking_speed_m_s)
        seconds[zones == own] = 0  # a zone's own opportunities are reached at once
        if not (zones == own).any():
            zones, seconds = np.append(zones, own), np.append(seconds, np.uint32(0))
        order = np.argsort(zones, kind="stable")
        walk_only.append((zones[order].astype(np.uint32), seconds[order].astype(np.uint32)))
    return ZoneWalks(access=access, walk_only=walk_only)


def _access_walks(
    router: Router, edge: U32, fraction: npt.NDArray[np.float64], snap: npt.NDArray[np.float64]
) -> list[tuple[U32, U32]]:
    routing = router.routing
    access = []
    for e, f, s in zip(edge.tolist(), fraction.tolist(), snap.tolist(), strict=True):
        stops, metres = router.walk.stops_within(e, f, s, routing.max_access_walk_m)
        access.append((stops, walk_seconds(metres, routing.walking_speed_m_s)))
    return access


def zone_access(router: Router, points: pl.DataFrame) -> list[tuple[U32, U32]]:
    """Per zone point: the stops within the access walk and the walk seconds to each.

    The same walks the matrix uses, so "has a stop" means exactly what it means there.
    """
    edge, fraction, snap = router.attach(points["lat"].to_numpy(), points["lon"].to_numpy())
    return _access_walks(router, edge, fraction, snap)


def matrix_chunk(
    router: Router,
    walks: ZoneWalks,
    origins: Sequence[int],
    departures: U32,
    settings: Accessibility,
) -> pl.DataFrame:
    """Percentile rows for ``origins`` (zone positions), sorted by origin then destination."""
    routing: Routing = router.routing
    batch = [(*walks.access[o], *walks.walk_only[o]) for o in origins]
    origin_pos, dest, times = router.timetable.zone_travel_times_many(
        batch,
        departures,
        len(walks.access),
        *walks.egress,
        np.array(settings.percentiles, dtype=np.uint8),
        settings.max_travel_time_min * 60,
        routing.max_rounds,
        routing.min_transfer_time_s,
        walks.rides(origins),
    )
    columns: dict[str, pl.Series] = {
        "origin_zone": pl.Series(np.asarray(origins, dtype=np.uint32)[origin_pos]),
        "dest_zone": pl.Series(dest),
    }
    names = [f"p{p}_s" for p in settings.percentiles]
    for j, name in enumerate(names):
        columns[name] = pl.Series(times[:, j])
    return pl.DataFrame(columns).with_columns(
        pl.when(pl.col(name) == gr.UNREACHED)
        .then(None)
        .otherwise(pl.col(name))
        .cast(pl.UInt16)
        .alias(name)
        for name in names
    )


class MatrixInput(BaseModel):
    stage: str
    manifest_sha256: str


class MatrixManifest(BaseModel):
    city: str
    scenario: str
    builder_version: str
    nature: DataNature
    inputs: list[MatrixInput]
    routing: Routing
    accessibility: Accessibility
    departures: int
    zones: int
    zone_points: dict[str, int]
    stats: dict[str, float]
    rows: int
    outputs: dict[str, str]


@dataclass(frozen=True)
class Reuse:
    """Copy rows from a baseline matrix except for the ``origins`` (zone positions) given.

    The baseline must have been built with the same settings, zones and walk network; rows of
    other origins are then identical by construction (see ``glacies.scenario.incremental``).
    """

    baseline_dir: Path
    origins: frozenset[int]


@dataclass
class MatrixResult:
    manifest: MatrixManifest
    out_dir: Path


def build_matrix(
    router: Router,
    zones: pl.DataFrame,
    walk_dir: Path,
    settings: Accessibility,
    out_dir: Path,
    *,
    city: str,
    scenario: str,
    inputs: list[MatrixInput],
    chunk: int = CHUNK_ORIGINS,
    walks: ZoneWalks | None = None,
    reuse: Reuse | None = None,
    on_chunk: Callable[[int, int], None] | None = None,
) -> MatrixResult:
    """Write the matrix for every zone as origin (``on_chunk(done, total)`` reports progress).

    ``walks`` skips recomputing walks that the caller already has; ``reuse`` recomputes only
    some origins and copies the rest from a baseline matrix with the same part layout.
    """
    if zones.height == 0:
        raise MatrixError("no zones")
    if "pop_lat" not in zones.columns:
        raise MatrixError("zones have no population-weighted points; rebuild zones")
    points = zone_points(zones)
    departures = np.array(settings.departures(), dtype=np.uint32)
    walks = walks or zone_walks(router, walk_dir, points, settings)

    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    n = points.height
    outputs: dict[str, str] = {}
    rows = 0
    p50 = f"p{settings.percentiles[len(settings.percentiles) // 2]}_s"
    reached_within: list[int] = []
    for k, start in enumerate(range(0, n, chunk)):
        origins = range(start, min(start + chunk, n))
        path = staging / f"part-{k:05d}.parquet"
        if reuse is None:
            part = matrix_chunk(router, walks, origins, departures, settings)
        else:
            part = _reused_part(router, walks, origins, departures, settings, reuse, path.name)
        write_part(part, path)
        outputs[path.name] = sha256_file(path)
        rows += part.height
        counts = (
            part.filter(pl.col(p50) <= settings.thresholds_min[-1] * 60)
            .group_by("origin_zone")
            .len()
        )
        reached_within += counts["len"].to_list()
        if on_chunk is not None:
            on_chunk(min(start + chunk, n), n)

    population = zones.sort("zone_idx")["population"].to_numpy()
    has_stop = np.array([s.size > 0 for s, _ in walks.access])
    manifest = MatrixManifest(
        city=city,
        scenario=scenario,
        builder_version=__version__,
        nature=DataNature.SIMULATED,
        inputs=inputs,
        routing=router.routing,
        accessibility=settings,
        departures=int(departures.size),
        zones=n,
        zone_points=dict(sorted(points.group_by("point").len().iter_rows())),
        stats={
            "zones_with_stop": int(has_stop.sum()),
            "population_with_stop_share": round(
                float(population[has_stop].sum() / population.sum()), 4
            ),
            "mean_zones_within_last_threshold": round(float(np.sum(reached_within) / n), 1),
        },
        rows=rows,
        outputs=outputs,
    )
    (staging / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (staging / REPORT_NAME).write_text(report(manifest), encoding="utf-8", newline="\n")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rename_with_retry(staging, out_dir)
    return MatrixResult(manifest=manifest, out_dir=out_dir)


def write_part(part: pl.DataFrame, path: Path) -> None:
    """Write one matrix part. Rechunking first makes the bytes depend only on the rows: a
    frame stitched from copied and recomputed rows would otherwise get one row group per chunk.
    """
    part.rechunk().write_parquet(path, compression="zstd", statistics=True)


def _reused_part(
    router: Router,
    walks: ZoneWalks,
    origins: range,
    departures: U32,
    settings: Accessibility,
    reuse: Reuse,
    name: str,
) -> pl.DataFrame:
    baseline = reuse.baseline_dir / name
    if not baseline.is_file():
        raise MatrixError(f"baseline matrix has no {name}")
    recompute = [o for o in origins if o in reuse.origins]
    kept = pl.read_parquet(baseline)
    if not recompute:
        return kept
    fresh = matrix_chunk(router, walks, recompute, departures, settings)
    kept = kept.filter(
        ~pl.col("origin_zone").is_in(pl.Series(recompute, dtype=pl.UInt32).implode())
    )
    return pl.concat([kept, fresh]).sort("origin_zone", "dest_zone")


def report(m: MatrixManifest) -> str:
    a, r, s = m.accessibility, m.routing, m.stats
    entry = ", ".join(f"{k} {v} s" for k, v in sorted(r.station_entry_s.items())) or "none"
    last = a.thresholds_min[-1]
    return "\n".join(
        [
            f"# Travel-time matrix — `{m.city}` / `{m.scenario}` (Simulated)",
            "",
            f"Builder {m.builder_version} · {m.zones:,} zones · {m.rows:,} origin-destination "
            f"rows in {len(m.outputs)} parts",
            "",
            "## Method (all parameters Assumed)",
            "",
            f"- Departures every {a.departure_step_s} s from {a.window_start} to before "
            f"{a.window_end} ({m.departures} departures).",
            f"- Percentiles {', '.join(f'p{p}' for p in a.percentiles)} of the door-to-door "
            "time over the departures, nearest rank; a departure that does not reach the zone "
            "counts as infinitely long.",
            f"- Pairs whose p{a.percentiles[0]} exceeds {a.max_travel_time_min} min are not "
            "stored; higher percentiles above it are null.",
            "- Zone points: "
            + ", ".join(f"{v:,} {k}" for k, v in m.zone_points.items())
            + " (population-weighted where people live, else the cell centre).",
            f"- Walks at {r.walking_speed_m_s} m/s: to and from stops ≤ "
            f"{r.max_access_walk_m:g} m, between stops ≤ {r.max_transfer_walk_m:g} m, zone to "
            f"zone without transit ≤ {a.max_walk_only_m:g} m; a zone reaches itself in 0 s.",
            f"- Router: ≤ {r.max_rounds} vehicles, {r.min_transfer_time_s} s minimum transfer, "
            f"station entry {entry}.",
            "",
            "## Coverage",
            "",
            f"- Zones with a stop within {r.max_access_walk_m:g} m walk: "
            f"{int(s['zones_with_stop']):,} of {m.zones:,}, holding "
            f"{s['population_with_stop_share']:.1%} of the population (Estimated). The others "
            "reach only zones within walking distance.",
            f"- Mean destination zones reached within {last} min at the median: "
            f"{s['mean_zones_within_last_threshold']:,.1f}.",
            "",
        ]
    )
