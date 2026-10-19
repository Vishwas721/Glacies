"""Outputs of an assignment run: Parquet tables, manifest and report (Phase 6)."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path

import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.assignment.aon import AonStats
from glacies.assignment.metrics import CityMetrics
from glacies.cities import AssignmentWindow, Capacity
from glacies.demand.calibrate import Fit
from glacies.fsutil import rename_with_retry
from glacies.provenance import DataNature, sha256_file

MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
LOADS_NAME = "loads.parquet"
STOPS_NAME = "stop_flows.parquet"
OD_NAME = "od_assignment.parquet"
ROUTES_NAME = "routes.parquet"
STATIONS_NAME = "stations.parquet"
STATION_PAIRS_NAME = "station_pairs.parquet"

COLUMN_NATURE: dict[str, dict[str, DataNature]] = {
    LOADS_NAME: {
        "boardings": DataNature.SIMULATED,
        "alightings": DataNature.SIMULATED,
        "load": DataNature.SIMULATED,
        "capacity": DataNature.ASSUMED,
        "crush_capacity": DataNature.ASSUMED,
        "load_factor": DataNature.SIMULATED,
        "crush_factor": DataNature.SIMULATED,
        "km": DataNature.ESTIMATED,  # straight line between the stops
    },
    STOPS_NAME: {"boardings": DataNature.SIMULATED, "alightings": DataNature.SIMULATED},
    OD_NAME: {
        "trips": DataNature.ESTIMATED,
        "transit": DataNature.SIMULATED,
        "walked": DataNature.SIMULATED,
        "unreached": DataNature.SIMULATED,
        "in_vehicle_min": DataNature.SIMULATED,
        "waiting_min": DataNature.SIMULATED,
        "walking_min": DataNature.SIMULATED,
        "riding_min": DataNature.SIMULATED,
        "vehicles": DataNature.SIMULATED,
        "ridden": DataNature.SIMULATED,
    },
    ROUTES_NAME: {
        "boardings": DataNature.SIMULATED,
        "passenger_km": DataNature.SIMULATED,
        "passenger_hours": DataNature.SIMULATED,
        "peak_utilisation": DataNature.SIMULATED,
        "peak_max_load_factor": DataNature.SIMULATED,
        "peak_share_over_capacity": DataNature.SIMULATED,
    },
    STATIONS_NAME: {
        "entries": DataNature.SIMULATED,
        "exits": DataNature.SIMULATED,
        "observed": DataNature.OBSERVED,
    },
    STATION_PAIRS_NAME: {"trips": DataNature.SIMULATED},
}


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
    metrics: CityMetrics
    # Simulated gate entries against observed ones per station set (training, held_out,
    # excluded), scored like demand calibration; empty when no ridership was built.
    station_fits: dict[str, Fit] = {}
    column_nature: dict[str, dict[str, DataNature]]
    outputs: dict[str, str] = {}


def config_input(window: AssignmentWindow, capacity: Capacity) -> AssignmentInput:
    """The settings the outputs depend on (fares and crowding are not used by AON yet)."""
    text = window.model_dump_json() + capacity.model_dump_json()
    return AssignmentInput(
        stage="assignment.toml", manifest_sha256=hashlib.sha256(text.encode()).hexdigest()
    )


def write_assignment(
    tables: dict[str, pl.DataFrame],
    out_dir: Path,
    *,
    city: str,
    scenario: str,
    window: AssignmentWindow,
    inputs: list[AssignmentInput],
    stats: AonStats,
    metrics: CityMetrics,
    station_fits: dict[str, Fit],
    report: Callable[[AssignmentManifest], str],
) -> AssignmentManifest:
    """Write ``tables`` (file name -> frame), the manifest and the report, atomically."""
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
        metrics=metrics,
        station_fits=station_fits,
        column_nature={k: v for k, v in COLUMN_NATURE.items() if k in tables},
    )
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
    (staging / REPORT_NAME).write_text(report(manifest), encoding="utf-8", newline="\n")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rename_with_retry(staging, out_dir)
    return manifest
