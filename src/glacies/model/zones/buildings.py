"""Open Buildings footprints aggregated to zones (count and area per confidence cut-off)."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from glacies.model.zones.grid import assign_points


def threshold_suffix(threshold: float) -> str:
    return f"c{round(threshold * 100):02d}"


def buildings_by_zone(
    path: Path, zones: pl.DataFrame, resolution: int, thresholds: list[float]
) -> tuple[pl.DataFrame, dict[str, int]]:
    """One row per zone with building_count_cXX and building_area_m2_cXX for each threshold."""
    raw = pl.read_csv(
        path,
        columns=["latitude", "longitude", "area_in_meters", "confidence"],
        schema_overrides={
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "area_in_meters": pl.Float64,
            "confidence": pl.Float64,
        },
    )
    raw = raw.with_columns(
        assign_points(zones, raw["latitude"], raw["longitude"], resolution).alias("zone_idx")
    )
    located = raw.filter(pl.col("zone_idx").is_not_null())
    aggregates = []
    for t in thresholds:
        keep = pl.col("confidence") >= t
        suffix = threshold_suffix(t)
        aggregates += [
            keep.sum().cast(pl.UInt32).alias(f"building_count_{suffix}"),
            pl.col("area_in_meters").filter(keep).sum().alias(f"building_area_m2_{suffix}"),
        ]
    per_zone = located.group_by("zone_idx").agg(aggregates)
    table = (
        zones.select("zone_idx")
        .join(per_zone, on="zone_idx", how="left")
        .sort("zone_idx")
        .fill_null(0)
        .drop("zone_idx")
    )
    stats = {
        "buildings_read": raw.height,
        "buildings_outside_zones": raw.height - located.height,
        **{
            f"buildings_{threshold_suffix(t)}": int(
                located.filter(pl.col("confidence") >= t).height
            )
            for t in thresholds
        },
    }
    return table, stats
