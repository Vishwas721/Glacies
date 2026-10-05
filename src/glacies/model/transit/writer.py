"""Write a TransitBuild to ``<dir>/*.parquet`` + ``manifest.json`` + ``BUILD_REPORT.md``.

The output directory is replaced atomically, and nothing time-dependent is written, so two
builds from the same inputs are byte-identical.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.fsutil import rename_with_retry
from glacies.model.transit.build import CleaningStep, TransitBuild
from glacies.model.transit.schema import TABLES
from glacies.provenance import DataNature, sha256_file
from glacies.validate.gtfs.report import Thresholds

MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"


class FeedRef(BaseModel):
    dataset: str
    snapshot: str
    checksum_sha256: str


class TransitManifest(BaseModel):
    city: str
    service_date: str
    bbox: tuple[float, float, float, float]
    builder_version: str
    inputs: list[FeedRef]
    drop_implausible_speed_trips: bool
    exclude_route_patterns: dict[str, str | None]
    thresholds: Thresholds
    steps: list[CleaningStep]
    dropped_by_reason: dict[str, dict[str, int]]
    stop_times_by_nature: dict[str, int]
    row_counts: dict[str, int]
    outputs: dict[str, str]  # file name -> sha256


def write_transit(
    build: TransitBuild,
    out_dir: Path,
    *,
    city: str,
    service_date: str,
    bbox: tuple[float, float, float, float],
    drop_implausible_speed_trips: bool,
    exclude_route_patterns: dict[str, str | None],
    thresholds: Thresholds,
) -> TransitManifest:
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    outputs: dict[str, str] = {}
    for name in TABLES:
        path = staging / f"{name}.parquet"
        build.tables[name].write_parquet(path, compression="zstd", statistics=True)
        outputs[path.name] = sha256_file(path)

    dropped = build.tables["dropped_trips"]
    by_reason: dict[str, dict[str, int]] = {}
    for row in dropped.group_by("dataset", "reason").len().sort("dataset", "reason").iter_rows():
        dataset, reason, count = row
        by_reason.setdefault(dataset, {})[reason] = count
    natures = build.tables["stop_times"].group_by("time_nature").len().sort("time_nature")
    feeds = build.tables["feeds"]

    manifest = TransitManifest(
        city=city,
        service_date=service_date,
        bbox=bbox,
        builder_version=__version__,
        inputs=[
            FeedRef(dataset=d, snapshot=s, checksum_sha256=c)
            for d, s, c in feeds.select("dataset", "snapshot", "checksum_sha256").iter_rows()
        ],
        drop_implausible_speed_trips=drop_implausible_speed_trips,
        exclude_route_patterns=exclude_route_patterns,
        thresholds=thresholds,
        steps=build.steps,
        dropped_by_reason=by_reason,
        stop_times_by_nature=dict(natures.iter_rows()),
        row_counts={name: build.tables[name].height for name in TABLES},
        outputs=outputs,
    )
    (staging / MANIFEST_NAME).write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
    (staging / REPORT_NAME).write_text(_report(manifest), "utf-8")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    rename_with_retry(staging, out_dir)
    return manifest


def _report(manifest: TransitManifest) -> str:
    lines = [
        f"# Canonical transit network — `{manifest.city}` on {manifest.service_date}",
        "",
        f"Builder {manifest.builder_version} · bbox `{list(manifest.bbox)}` · "
        f"inputs: " + ", ".join(f"`{i.dataset}@{i.snapshot}`" for i in manifest.inputs),
        "",
        "## Tables",
        "",
        "| Table | Rows |",
        "|---|---:|",
        *(f"| {name} | {rows:,} |" for name, rows in manifest.row_counts.items()),
        "",
        "Stop times by nature: "
        + ", ".join(f"{k} {v:,}" for k, v in manifest.stop_times_by_nature.items()),
        "",
        "## Cleaning steps",
        "",
        "| Feed | Step | Trips before | Trips after | Detail |",
        "|---|---|---:|---:|---|",
        *(
            f"| {s.dataset} | {s.step} | {s.trips_before:,} | {s.trips_after:,} | {s.detail} |"
            for s in manifest.steps
        ),
        "",
        "## Dropped trips by reason",
        "",
    ]
    if not manifest.dropped_by_reason:
        lines += ["None.", ""]
    for dataset, reasons in manifest.dropped_by_reason.items():
        lines += [f"- **{dataset}**: " + ", ".join(f"{r} {n:,}" for r, n in reasons.items())]
    lines += [
        "",
        "Every dropped trip (feed, source trip id, reason, speed, threshold, hop) is listed in "
        "`dropped_trips.parquet`.",
        "",
        "## Labels",
        "",
        f"- Timetables: {DataNature.OBSERVED.value}, except interpolated stop times "
        f"({DataNature.ESTIMATED.value}).",
        f"- Speed limits and the study-area bbox: {DataNature.ASSUMED.value}.",
        "",
    ]
    return "\n".join(lines)


def read_table(out_dir: Path, name: str) -> pl.DataFrame:
    return pl.read_parquet(out_dir / f"{name}.parquet")
