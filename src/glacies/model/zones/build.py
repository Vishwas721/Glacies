"""Assemble the zones table from every spatial layer, and write it with a manifest + report."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.fsutil import rename_with_retry
from glacies.model.zones.buildings import buildings_by_zone
from glacies.model.zones.grid import assign_points, make_zones
from glacies.model.zones.pois import CATEGORIES, extract_pois
from glacies.model.zones.rasters import landcover_by_zone, population_by_zone
from glacies.provenance import DataNature, sha256_file

Bbox = tuple[float, float, float, float]
MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
TABLES = ("zones", "pois")

# Provenance label of each zones column family (PRD §56).
COLUMN_NATURE: dict[str, DataNature] = {
    "population": DataNature.ESTIMATED,  # WorldPop is a modelled raster
    "building_": DataNature.ESTIMATED,  # ML-detected footprints
    "landcover_": DataNature.ESTIMATED,  # classified imagery
    "poi_": DataNature.OBSERVED,  # mapped features (category rules are Assumed)
    "stops_": DataNature.OBSERVED,  # canonical transit network
}


@dataclass(frozen=True)
class ZoneInputs:
    population_raster: Path
    landcover_raster: Path
    buildings_csv: Path
    osm_file: Path
    transit_stops: pl.DataFrame  # stop_idx, lat, lon, location_type
    transit_stop_modes: pl.DataFrame  # stop_idx, mode (one row per mode serving the stop)


@dataclass
class ZonesBuild:
    tables: dict[str, pl.DataFrame]
    stats: dict[str, int | float] = field(default_factory=dict)
    skipped_pois: dict[str, int] = field(default_factory=dict)


def stop_modes(tables: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Which modes serve each stop, from canonical transit tables."""
    return (
        tables["stop_times"]
        .select("trip_idx", "stop_idx")
        .unique()
        .join(tables["trips"].select("trip_idx", "route_idx"), on="trip_idx")
        .join(tables["routes"].select("route_idx", "mode"), on="route_idx")
        .select("stop_idx", "mode")
        .unique()
        .sort("stop_idx", "mode")
    )


def build_zones(
    inputs: ZoneInputs, *, bbox: Bbox, resolution: int, thresholds: list[float]
) -> ZonesBuild:
    zones = make_zones(bbox, resolution)
    population, pop_stats = population_by_zone(str(inputs.population_raster), zones, bbox)
    buildings, building_stats = buildings_by_zone(
        inputs.buildings_csv, zones, resolution, thresholds
    )
    landcover = landcover_by_zone(str(inputs.landcover_raster), zones)

    pois, skipped = extract_pois(inputs.osm_file, bbox)
    pois = pois.with_columns(
        assign_points(zones, pois["lat"], pois["lon"], resolution).alias("zone_idx")
    )
    poi_counts = (
        pois.filter(pl.col("zone_idx").is_not_null())
        .group_by("zone_idx")
        .agg((pl.col("category") == c).sum().cast(pl.UInt32).alias(f"poi_{c}") for c in CATEGORIES)
    )

    stops = inputs.transit_stops.filter(pl.col("location_type") == 0)
    stops = stops.with_columns(
        assign_points(zones, stops["lat"], stops["lon"], resolution).alias("zone_idx")
    )
    modes = stops.select("stop_idx", "zone_idx").join(inputs.transit_stop_modes, on="stop_idx")
    stop_counts = modes.group_by("zone_idx").agg(
        (pl.col("mode") == "bus").sum().cast(pl.UInt32).alias("stops_bus"),
        (pl.col("mode") == "metro").sum().cast(pl.UInt32).alias("stops_metro"),
        (~pl.col("mode").is_in(["bus", "metro"])).sum().cast(pl.UInt32).alias("stops_other"),
    )

    table = (
        # Every layer has one row per zone in zone_idx order; with_columns enforces equal length.
        zones.with_columns(population, *buildings.get_columns(), *landcover.get_columns())
        .join(poi_counts, on="zone_idx", how="left")
        .join(stop_counts, on="zone_idx", how="left")
        .with_columns(pl.col("^(poi|stops)_.*$").fill_null(0).cast(pl.UInt32))
        .sort("zone_idx")
    )
    stats: dict[str, int | float] = {
        "zones": table.height,
        "zones_populated": int((table["population"] > 0).sum()),
        **pop_stats,
        **building_stats,
        "pois": pois.height,
        **{f"pois_{c}": int((pois["category"] == c).sum()) for c in CATEGORIES},
        "boarding_stops": stops.height,
        "stops_outside_zones": int(stops["zone_idx"].null_count()),
    }
    return ZonesBuild(
        tables={
            "zones": table,
            "pois": pois.select("osm_type", "osm_id", "category", "lat", "lon", "zone_idx"),
        },
        stats=stats,
        skipped_pois=skipped,
    )


class InputRef(BaseModel):
    dataset: str
    snapshot: str
    checksum_sha256: str


class ZonesManifest(BaseModel):
    city: str
    bbox: Bbox
    resolution: int
    building_confidence_thresholds: list[float]
    builder_version: str
    inputs: list[InputRef]
    transit_stops_sha256: str
    column_nature: dict[str, DataNature]
    stats: dict[str, int | float]
    skipped_pois: dict[str, int]
    row_counts: dict[str, int]
    outputs: dict[str, str]


def write_zones(
    build: ZonesBuild,
    out_dir: Path,
    *,
    city: str,
    bbox: Bbox,
    resolution: int,
    thresholds: list[float],
    inputs: list[InputRef],
    transit_stops_sha256: str,
) -> ZonesManifest:
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    outputs: dict[str, str] = {}
    for name in TABLES:
        path = staging / f"{name}.parquet"
        build.tables[name].write_parquet(path, compression="zstd", statistics=True)
        outputs[path.name] = sha256_file(path)
    manifest = ZonesManifest(
        city=city,
        bbox=bbox,
        resolution=resolution,
        building_confidence_thresholds=thresholds,
        builder_version=__version__,
        inputs=inputs,
        transit_stops_sha256=transit_stops_sha256,
        column_nature=COLUMN_NATURE,
        stats=build.stats,
        skipped_pois=build.skipped_pois,
        row_counts={name: build.tables[name].height for name in TABLES},
        outputs=outputs,
    )
    (staging / MANIFEST_NAME).write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
    (staging / REPORT_NAME).write_text(_report(manifest), "utf-8")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    rename_with_retry(staging, out_dir)
    return manifest


def population_check(stats: dict[str, int | float]) -> tuple[float, float]:
    """(conservation error, zones vs bbox ratio): pixels are neither lost nor double counted."""
    window = float(stats["population_raster_window"])
    accounted = float(stats["population_zones"]) + float(stats["population_outside_zones"])
    conservation = abs(accounted - window) / window if window else 0.0
    bbox_total = float(stats["population_bbox"])
    ratio = float(stats["population_zones"]) / bbox_total if bbox_total else 0.0
    return conservation, ratio


def _report(m: ZonesManifest) -> str:
    s = m.stats
    conservation, ratio = population_check(s)
    suffixes = [f"c{round(t * 100):02d}" for t in m.building_confidence_thresholds]
    lines = [
        f"# Zones — `{m.city}` (H3 resolution {m.resolution})",
        "",
        f"Builder {m.builder_version} · bbox `{list(m.bbox)}` · inputs: "
        + ", ".join(f"`{i.dataset}@{i.snapshot}`" for i in m.inputs),
        "",
        "## Zones",
        "",
        f"- Zones (every cell overlapping the bbox): {s['zones']:,}; populated: "
        f"{s['zones_populated']:,}",
        "",
        "## Population (Estimated, WorldPop)",
        "",
        f"- In zones: **{s['population_zones']:,.0f}** · pixel centres inside the bbox: "
        f"{s['population_bbox']:,.0f} · zones ÷ bbox = **{ratio:.2%}** (zones extend just past "
        "the bbox edge)",
        f"- Conservation: every raster pixel read is assigned to exactly one zone or to "
        f"'outside' (error {conservation:.2e})",
        "",
        "## Buildings (Estimated, Open Buildings)",
        "",
        f"- Read: {s['buildings_read']:,} · outside zones: {s['buildings_outside_zones']:,}",
        *(
            f"- Confidence ≥ {t:g}: {s[f'buildings_{x}']:,}"
            for t, x in zip(m.building_confidence_thresholds, suffixes, strict=True)
        ),
        "",
        "## Points of interest (Observed, OpenStreetMap; categories Assumed)",
        "",
        f"- Total: {s['pois']:,}",
        *(f"- {c}: {s[f'pois_{c}']:,}" for c in CATEGORIES),
        "- Skipped: " + (", ".join(f"{k} {v:,}" for k, v in m.skipped_pois.items()) or "none"),
        "",
        "## Transit stops (Observed)",
        "",
        f"- Boarding stops: {s['boarding_stops']:,} · outside zones: {s['stops_outside_zones']:,}",
        "",
        "## Column labels",
        "",
        *(f"- `{prefix}*`: {nature.value}" for prefix, nature in m.column_nature.items()),
        "",
    ]
    return "\n".join(lines)
