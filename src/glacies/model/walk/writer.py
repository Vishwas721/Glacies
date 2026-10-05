"""Write a WalkBuild to ``<dir>/*.parquet`` + ``manifest.json`` + ``BUILD_REPORT.md``."""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.cities import Walk
from glacies.fsutil import rename_with_retry
from glacies.model.walk.build import TABLES, WalkBuild
from glacies.model.walk.extract import ExtractStats
from glacies.provenance import DataNature, sha256_file

MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"


class WalkManifest(BaseModel):
    city: str
    bbox: tuple[float, float, float, float]
    builder_version: str
    osm_snapshot: str
    osm_checksum_sha256: str
    transit_stops_sha256: str
    settings: Walk
    ways_kept: dict[str, int]
    ways_excluded: dict[str, int]
    segments_outside_bbox: int
    segments_missing_location: int
    stats: dict[str, int | float]
    row_counts: dict[str, int]
    outputs: dict[str, str]


def write_walk(
    build: WalkBuild,
    extract_stats: ExtractStats,
    out_dir: Path,
    *,
    city: str,
    bbox: tuple[float, float, float, float],
    osm_snapshot: str,
    osm_checksum_sha256: str,
    transit_stops_sha256: str,
    walk: Walk,
    stop_names: pl.DataFrame,
) -> WalkManifest:
    """``stop_names`` (stop_idx, source_stop_id, name) is used only to label flagged stops."""
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    outputs: dict[str, str] = {}
    for name in TABLES:
        path = staging / f"{name}.parquet"
        build.tables[name].write_parquet(path, compression="zstd", statistics=True)
        outputs[path.name] = sha256_file(path)

    manifest = WalkManifest(
        city=city,
        bbox=bbox,
        builder_version=__version__,
        osm_snapshot=osm_snapshot,
        osm_checksum_sha256=osm_checksum_sha256,
        transit_stops_sha256=transit_stops_sha256,
        settings=walk,
        ways_kept=dict(sorted(extract_stats.ways_kept.items())),
        ways_excluded=dict(sorted(extract_stats.ways_excluded.items())),
        segments_outside_bbox=extract_stats.segments_outside_bbox,
        segments_missing_location=extract_stats.segments_missing_location,
        stats=build.stats,
        row_counts={name: build.tables[name].height for name in TABLES},
        outputs=outputs,
    )
    (staging / MANIFEST_NAME).write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
    flagged = (
        build.tables["stop_links"]
        .filter(pl.col("flagged"))
        .join(stop_names, on="stop_idx", how="left")
        .sort("distance_m", "stop_idx", descending=[True, False])
    )
    (staging / REPORT_NAME).write_text(_report(manifest, flagged), "utf-8")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    rename_with_retry(staging, out_dir)
    return manifest


def _report(m: WalkManifest, flagged: pl.DataFrame) -> str:
    s = m.stats
    lines = [
        f"# Walk network — `{m.city}`",
        "",
        f"Builder {m.builder_version} · OSM snapshot `{m.osm_snapshot}` · bbox `{list(m.bbox)}`",
        "",
        "## Network",
        "",
        f"- Nodes: {s['nodes']:,} · edges: {s['edges']:,} · length: {s['network_length_km']:,} km",
        f"- Connected components: {s['components']:,}; the largest holds "
        f"{s['largest_component_share']:.1%} of nodes",
        f"- Duplicate segments merged: {s['duplicate_segments']:,} · segments clipped at the bbox: "
        f"{m.segments_outside_bbox:,} · segments with missing node locations: "
        f"{m.segments_missing_location:,}",
        "",
        "| Kept ways by highway | Count |",
        "|---|---:|",
        *(f"| {k} | {v:,} |" for k, v in sorted(m.ways_kept.items(), key=lambda kv: -kv[1])),
        "",
        "| Excluded ways by reason | Count |",
        "|---|---:|",
        *(f"| {k} | {v:,} |" for k, v in sorted(m.ways_excluded.items(), key=lambda kv: -kv[1])),
        "",
        "## Stop snapping",
        "",
        f"- Boarding stops snapped: {s['stops_snapped']:,}"
        + (" (largest component only)" if m.settings.snap_to_largest_component else ""),
    ]
    if s["stops_snapped"]:
        lines.append(
            f"- Snap distance: median {s['snap_p50_m']} m · p90 {s['snap_p90_m']} m · "
            f"p99 {s['snap_p99_m']} m · max {s['snap_max_m']} m"
        )
    lines += [
        f"- **Flagged (> {m.settings.max_snap_m:g} m): {s['stops_flagged']:,}**",
        "",
    ]
    if flagged.height:
        lines += ["| stop_idx | Source stop | Name | Distance (m) |", "|---:|---|---|---:|"]
        lines += [
            f"| {r['stop_idx']} | {r['source_stop_id']} | {r['name'] or ''} | "
            f"{r['distance_m']:,.0f} |"
            for r in flagged.iter_rows(named=True)
        ]
        lines.append("")
    lines += [
        "## Labels",
        "",
        f"- Network geometry: {DataNature.OBSERVED.value} (OpenStreetMap).",
        f"- Walkable-way rules, snap limit and component rule: {DataNature.ASSUMED.value}.",
        "",
    ]
    return "\n".join(lines)
