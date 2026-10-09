"""Stations and lines of the calibration mode in the canonical network (Phase 5).

Ridership data names stations, not GTFS IDs, so the held-out stations and excluded lines in
``demand.toml`` are checked against the network's station names before anything uses them: a
misspelt name would otherwise silently move a station from the held-out set into training.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from glacies.cities import DemandCalibration
from glacies.demand.production import DemandError


def stations_and_lines(transit_dir: Path, mode: str) -> tuple[list[str], list[str]]:
    """Sorted station names (parent stations where they exist) and line names of ``mode``."""
    routes = pl.read_parquet(transit_dir / "routes.parquet").filter(pl.col("mode") == mode)
    stops = pl.read_parquet(transit_dir / "stops.parquet")
    used = (
        pl.read_parquet(transit_dir / "pattern_stops.parquet")
        .join(pl.read_parquet(transit_dir / "patterns.parquet"), on="pattern_idx")
        .join(routes.select("route_idx"), on="route_idx")
        .join(stops.select("stop_idx", "parent_stop_idx"), on="stop_idx")
        .select(pl.coalesce("parent_stop_idx", "stop_idx").alias("stop_idx"))
        .unique()
        .join(stops.select("stop_idx", "name"), on="stop_idx")
    )
    return sorted(set(used["name"].to_list())), sorted(set(routes["short_name"].to_list()))


def check_calibration_names(transit_dir: Path, mode: str, calibration: DemandCalibration) -> None:
    stations, lines = stations_and_lines(transit_dir, mode)
    problems = []
    unknown = sorted(set(calibration.held_out_stations) - set(stations))
    if unknown:
        problems.append(f"held-out stations not in the {mode} network: {', '.join(unknown)}")
    unknown = sorted(set(calibration.exclude_lines) - set(lines))
    if unknown:
        problems.append(
            f"excluded lines not in the {mode} network: {', '.join(unknown)} "
            f"(lines: {', '.join(lines)})"
        )
    if problems:
        raise DemandError("; ".join(problems))
