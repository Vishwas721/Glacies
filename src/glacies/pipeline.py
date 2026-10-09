"""Pipeline stages shared by the CLI commands and ``glacies build-city``.

Each stage reads archived or already-built inputs, writes one output directory under
``data/processed/<city>/`` and returns its manifest. Stages raise ``PipelineError`` with a
message meant for the user.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import psycopg
from pydantic import BaseModel

from glacies import __version__
from glacies.analytics.accessibility import (
    AccessibilityError,
    AccessibilityInput,
    AccessibilityManifest,
    build_accessibility,
    write_accessibility,
)
from glacies.analytics.report import ReportResult, build_report
from glacies.analytics.travel_times import (
    MatrixError,
    MatrixInput,
    MatrixResult,
    Reuse,
    ZoneWalks,
    build_matrix,
    zone_points,
    zone_walks,
)
from glacies.cities import CityConfig, CityConfigError, DemandConfig, load_demand
from glacies.config import Settings
from glacies.db import postgis
from glacies.demand.attraction import (
    AttractionBuild,
    AttractionError,
    AttractionManifest,
    build_attraction,
    employment_score,
    read_hubs,
    write_attraction,
)
from glacies.demand.metro import (
    ACCESS_NAME,
    PATHS_NAME,
    REACH_NAME,
    STATIONS_NAME,
    MetroInput,
    MetroManifest,
    PathsManifest,
    metro_network,
    metro_paths,
    path_shares,
    station_flows,
    walk_pairs,
    write_paths,
    write_station_flows,
)
from glacies.demand.od import DemandBuild, DemandInput, DemandManifest, build_demand, write_demand
from glacies.demand.production import DemandError, candidate_pairs
from glacies.demand.ridership import RidershipManifest, read_ridership, write_ridership
from glacies.demand.stations import check_calibration_names, network_stations
from glacies.ingest import archive
from glacies.model.transit.build import FeedInput, TransitBuildError, build_transit
from glacies.model.transit.writer import MANIFEST_NAME as TRANSIT_MANIFEST
from glacies.model.transit.writer import TransitManifest, write_transit
from glacies.model.walk.build import WalkBuild, build_walk
from glacies.model.walk.extract import extract_walk_segments
from glacies.model.walk.writer import WalkManifest, write_walk
from glacies.model.zones.build import MANIFEST_NAME as ZONES_MANIFEST
from glacies.model.zones.build import (
    InputRef,
    ZoneInputs,
    ZonesBuild,
    ZonesManifest,
    build_zones,
    stop_modes,
    write_zones,
)
from glacies.provenance import DatasetManifest, sha256_file
from glacies.routing.network import RouterError, load_router
from glacies.validate.gtfs.report import Severity, Thresholds, ValidationReport
from glacies.validate.gtfs.validator import ValidationOptions, validate_feed

BUILD_NAME = "BUILD.json"


class PipelineError(Exception):
    """A stage cannot run; the message says what to do."""


# --- locating inputs ------------------------------------------------------------------------


def city_dir(settings: Settings, config: CityConfig) -> Path:
    return settings.processed_dir / config.city.id


def newest(snapshots: list[DatasetManifest]) -> DatasetManifest:
    return max(snapshots, key=lambda m: (m.archived_at, m.snapshot))


def gtfs_snapshot(
    settings: Settings, config: CityConfig, dataset: str, snapshot: str | None = None
) -> tuple[DatasetManifest, Path]:
    """The requested (or most recently archived) snapshot of a GTFS source, and its data dir."""
    try:
        source = config.source(dataset)
    except CityConfigError as exc:
        raise PipelineError(str(exc)) from None
    if source.kind != "gtfs":
        raise PipelineError(f"{dataset!r} is a {source.kind!r} source, not GTFS")
    snapshots = archive.list_snapshots(settings.raw_dir, config.city.id, dataset)
    if snapshot is not None:
        snapshots = [m for m in snapshots if m.snapshot == snapshot]
    if not snapshots:
        raise PipelineError(
            f"no archived snapshot of {dataset!r}; run `glacies ingest register` first"
        )
    manifest = newest(snapshots)
    snapshot_dir = (
        archive.dataset_dir(settings.raw_dir, config.city.id, dataset) / manifest.snapshot
    )
    return manifest, snapshot_dir / archive.DATA_DIR_NAME


def single_file_snapshot(
    settings: Settings, config: CityConfig, name: str
) -> tuple[DatasetManifest, Path]:
    """Newest snapshot of a single-file source and the path of that file."""
    snapshots = archive.list_snapshots(settings.raw_dir, config.city.id, name)
    if not snapshots:
        raise PipelineError(
            f"no archived snapshot of {name!r}; run `glacies ingest register` first"
        )
    manifest = newest(snapshots)
    files = [f.path for f in manifest.files]
    if len(files) != 1:
        raise PipelineError(
            f"expected exactly one file in {name} @ {manifest.snapshot}, found {files}"
        )
    data_dir = archive.dataset_dir(settings.raw_dir, config.city.id, name) / manifest.snapshot
    return manifest, data_dir / archive.DATA_DIR_NAME / files[0]


def source_of_kind(config: CityConfig, kind: str, chosen: str | None = None) -> str:
    names = sorted(n for n, s in config.sources.items() if s.kind == kind)
    if chosen is not None:
        if chosen not in names:
            raise PipelineError(f"{chosen!r} is not a {kind} source; choose from {names}")
        return chosen
    if len(names) != 1:
        raise PipelineError(
            f"expected exactly one {kind!r} source in city.toml, found {names or 'none'}"
        )
    return names[0]


def transit_manifest(settings: Settings, config: CityConfig) -> tuple[TransitManifest, Path]:
    transit_dir = city_dir(settings, config) / "transit"
    if not (transit_dir / TRANSIT_MANIFEST).is_file():
        raise PipelineError("no canonical transit network; run `glacies build transit` first")
    manifest = TransitManifest.model_validate_json(
        (transit_dir / TRANSIT_MANIFEST).read_text(encoding="utf-8")
    )
    return manifest, transit_dir


def _feed_ref(dataset: str, snapshot: str, checksum: str) -> InputRef:
    return InputRef(dataset=dataset, snapshot=snapshot, checksum_sha256=checksum)


def _ref(name: str, manifest: DatasetManifest) -> InputRef:
    return InputRef(
        dataset=name, snapshot=manifest.snapshot, checksum_sha256=manifest.checksum_sha256
    )


# --- stages ---------------------------------------------------------------------------------


def validate_gtfs(
    settings: Settings, config: CityConfig, dataset: str, snapshot: str | None = None
) -> tuple[ValidationReport, Path]:
    manifest, data_dir = gtfs_snapshot(settings, config, dataset, snapshot)
    source = config.source(dataset)
    report = validate_feed(
        data_dir,
        ValidationOptions(
            dataset=dataset,
            city=config.city.id,
            snapshot=manifest.snapshot,
            input_checksum=manifest.checksum_sha256,
            bbox=config.city.bbox,
            route_number_pattern=source.route_number_pattern,
            coverage_reference=source.coverage_reference,
        ),
    )
    out_dir = city_dir(settings, config) / "reports" / dataset / manifest.snapshot
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gtfs_validation.json").write_text(report.to_json(), encoding="utf-8")
    (out_dir / "gtfs_validation.md").write_text(report.to_markdown(), encoding="utf-8")
    return report, out_dir


def run_transit(
    settings: Settings,
    config: CityConfig,
    *,
    force: bool = False,
    reports: dict[str, ValidationReport] | None = None,
) -> tuple[TransitManifest, Path]:
    """Build the canonical network; refuses feeds with validation errors unless ``force``."""
    network = config.network
    if network is None:
        raise PipelineError(f"city {config.city.id!r} has no [network] section in city.toml")
    inputs: list[FeedInput] = []
    for dataset in network.feeds:
        snapshot, data_dir = gtfs_snapshot(settings, config, dataset)
        report = (reports or {}).get(dataset) or validate_gtfs(settings, config, dataset)[0]
        if report.errors and not force:
            rules = ", ".join(sorted({f.rule for f in report.errors}))
            raise PipelineError(
                f"{dataset} @ {snapshot.snapshot} has validation errors ({rules}); "
                "fix them or pass --force"
            )
        source = config.source(dataset)
        inputs.append(
            FeedInput(
                dataset=dataset,
                snapshot=snapshot.snapshot,
                checksum_sha256=snapshot.checksum_sha256,
                directory=data_dir,
                route_number_pattern=source.route_number_pattern,
                exclude_route_pattern=source.exclude_route_pattern,
            )
        )
    thresholds = Thresholds()
    try:
        result = build_transit(
            inputs,
            service_date=network.service_date,
            bbox=config.city.bbox,
            thresholds=thresholds,
            drop_implausible_speed_trips=network.drop_implausible_speed_trips,
        )
    except TransitBuildError as exc:
        raise PipelineError(str(exc)) from None
    out_dir = city_dir(settings, config) / "transit"
    manifest = write_transit(
        result,
        out_dir,
        city=config.city.id,
        service_date=network.service_date.isoformat(),
        bbox=config.city.bbox,
        drop_implausible_speed_trips=network.drop_implausible_speed_trips,
        exclude_route_patterns={d: config.source(d).exclude_route_pattern for d in network.feeds},
        thresholds=thresholds,
    )
    return manifest, out_dir


def run_walk(
    settings: Settings, config: CityConfig, *, source: str | None = None
) -> tuple[WalkManifest, WalkBuild, Path]:
    name = source_of_kind(config, "osm_pbf", source)
    osm, osm_file = single_file_snapshot(settings, config, name)
    transit, transit_dir = transit_manifest(settings, config)
    stops = pl.read_parquet(transit_dir / "stops.parquet")
    boarding = stops.filter(pl.col("location_type") == 0)
    segments, extract_stats = extract_walk_segments(osm_file, config.city.bbox, config.walk)
    result = build_walk(segments, boarding, config.walk, config.city.crs_projected)
    out_dir = city_dir(settings, config) / "walk"
    manifest = write_walk(
        result,
        extract_stats,
        out_dir,
        city=config.city.id,
        bbox=config.city.bbox,
        osm_snapshot=osm.snapshot,
        osm_checksum_sha256=osm.checksum_sha256,
        transit_stops_sha256=transit.outputs["stops.parquet"],
        walk=config.walk,
        stop_names=stops.select("stop_idx", "source_stop_id", "name"),
    )
    return manifest, result, out_dir


def run_zones(settings: Settings, config: CityConfig) -> tuple[ZonesManifest, ZonesBuild, Path]:
    refs: list[InputRef] = []
    paths: dict[str, Path] = {}
    for kind in ("population_raster", "landcover_raster", "buildings", "osm_pbf"):
        name = source_of_kind(config, kind)
        snapshot, path = single_file_snapshot(settings, config, name)
        refs.append(_ref(name, snapshot))
        paths[kind] = path
    transit, transit_dir = transit_manifest(settings, config)
    tables = {
        name: pl.read_parquet(transit_dir / f"{name}.parquet")
        for name in ("stops", "stop_times", "trips", "routes")
    }
    zoning = config.zoning
    result = build_zones(
        ZoneInputs(
            population_raster=paths["population_raster"],
            landcover_raster=paths["landcover_raster"],
            buildings_csv=paths["buildings"],
            osm_file=paths["osm_pbf"],
            transit_stops=tables["stops"],
            transit_stop_modes=stop_modes(tables),
        ),
        bbox=config.city.bbox,
        resolution=zoning.resolution,
        thresholds=zoning.building_confidence_thresholds,
    )
    out_dir = city_dir(settings, config) / "zones"
    manifest = write_zones(
        result,
        out_dir,
        city=config.city.id,
        bbox=config.city.bbox,
        resolution=zoning.resolution,
        thresholds=zoning.building_confidence_thresholds,
        inputs=refs,
        transit_stops_sha256=transit.outputs["stops.parquet"],
    )
    return manifest, result, out_dir


def run_attraction(
    settings: Settings, config: CityConfig
) -> tuple[AttractionManifest, AttractionBuild, Path]:
    """Employment proxy per zone from the processed zones (Phase 3 M1)."""
    params = config.attraction
    if params is None:
        raise PipelineError(f"city {config.city.id!r} has no [attraction] section in city.toml")
    zones_dir = city_dir(settings, config) / "zones"
    zones_path = zones_dir / "zones.parquet"
    if not zones_path.is_file():
        raise PipelineError(f"missing {zones_path}; run `glacies build zones` first")
    hubs_path = (
        settings.cities_dir / config.city.id / params.validation_hubs
        if params.validation_hubs
        else None
    )
    try:
        hubs = read_hubs(hubs_path) if hubs_path else None
        result = build_attraction(pl.read_parquet(zones_path), params, hubs)
    except AttractionError as exc:
        raise PipelineError(str(exc)) from exc
    out_dir = city_dir(settings, config) / "attraction"
    manifest = write_attraction(
        result,
        out_dir,
        city=config.city.id,
        params=params,
        zones_manifest_sha256=sha256_file(zones_dir / ZONES_MANIFEST),
        hubs_path=hubs_path,
        hub_names=[name for name, _ in hubs or []],
    )
    return manifest, result, out_dir


def run_matrix(
    settings: Settings,
    config: CityConfig,
    *,
    scenario: str = "baseline",
    transit_dir: Path | None = None,
    out_dir: Path | None = None,
    walks: ZoneWalks | None = None,
    reuse: Reuse | None = None,
    on_chunk: Callable[[int, int], None] | None = None,
) -> MatrixResult:
    """Zone-to-zone travel-time percentiles over the departure window (Phase 3 M2).

    ``transit_dir`` and ``out_dir`` default to the city's own network and
    ``tt_matrix/<scenario>``; scenario runs point them at their result directory.
    """
    base = city_dir(settings, config)
    transit = transit_dir or base / "transit"
    stage_dirs = {"transit": transit, "walk": base / "walk", "zones": base / "zones"}
    zones_path = base / "zones" / "zones.parquet"
    if not zones_path.is_file():
        raise PipelineError(f"missing {zones_path}; run `glacies build zones` first")
    try:
        router = load_router(base, config.routing, config.city.crs_projected, transit_dir=transit)
        return build_matrix(
            router,
            pl.read_parquet(zones_path),
            base / "walk",
            config.accessibility,
            out_dir or base / "tt_matrix" / scenario,
            city=config.city.id,
            scenario=scenario,
            inputs=[
                MatrixInput(stage=stage, manifest_sha256=sha256_file(directory / "manifest.json"))
                for stage, directory in stage_dirs.items()
            ],
            walks=walks,
            reuse=reuse,
            on_chunk=on_chunk,
        )
    except (RouterError, MatrixError) as exc:
        raise PipelineError(str(exc)) from exc


def run_accessibility(
    settings: Settings,
    config: CityConfig,
    *,
    scenario: str = "baseline",
    tt_dir: Path | None = None,
    out_dir: Path | None = None,
) -> tuple[AccessibilityManifest, Path]:
    """Cumulative accessibility per zone and city summaries (Phase 3 M3)."""
    if config.attraction is None:
        raise PipelineError(f"city {config.city.id!r} has no [attraction] section in city.toml")
    base = city_dir(settings, config)
    stages = {
        "zones": base / "zones",
        "attraction": base / "attraction",
        "tt_matrix": tt_dir or base / "tt_matrix" / scenario,
    }
    commands = {"zones": "zones", "attraction": "attraction", "tt_matrix": "tt-matrix"}
    for stage, directory in stages.items():
        if not (directory / "manifest.json").is_file():
            raise PipelineError(f"missing {directory}; run `glacies build {commands[stage]}` first")
    zones = pl.read_parquet(stages["zones"] / "zones.parquet").sort("zone_idx")
    proxy = config.attraction
    try:
        alternatives = {
            w.name: employment_score(zones, w, proxy.job_poi_categories)
            for w in (proxy.baseline, *proxy.sensitivity)
        }
        result = build_accessibility(
            zones,
            pl.read_parquet(stages["attraction"] / "attraction.parquet"),
            pl.scan_parquet(stages["tt_matrix"] / "*.parquet"),
            config.accessibility,
            bbox=config.city.bbox,
            index_total=proxy.opportunity_index_total,
            alternatives=alternatives,
        )
    except (AccessibilityError, AttractionError) as exc:
        raise PipelineError(str(exc)) from exc
    out_dir = out_dir or base / "accessibility" / scenario
    manifest = write_accessibility(
        result,
        out_dir,
        city=config.city.id,
        scenario=scenario,
        settings=config.accessibility,
        index_total=config.attraction.opportunity_index_total,
        inputs=[
            AccessibilityInput(
                stage=stage, manifest_sha256=sha256_file(directory / "manifest.json")
            )
            for stage, directory in stages.items()
        ],
    )
    return manifest, out_dir


def _demand_settings(settings: Settings, config: CityConfig) -> tuple[DemandConfig, str]:
    """The city's demand.toml and the mode its calibration ridership counts."""
    try:
        demand = load_demand(settings.demand_config_path)
        mode = config.source(demand.calibration.dataset).mode
    except CityConfigError as exc:
        raise PipelineError(str(exc)) from exc
    if mode is None:
        raise PipelineError(f"source {demand.calibration.dataset!r} has no mode")
    return demand, mode


def _require(stages: dict[str, Path], commands: dict[str, str] | None = None) -> None:
    for stage, directory in stages.items():
        if not (directory / "manifest.json").is_file():
            command = (commands or {}).get(stage, stage)
            raise PipelineError(f"missing {directory}; run `glacies build {command}` first")


def _inputs(stages: dict[str, Path]) -> list[MetroInput]:
    return [
        MetroInput(stage=stage, manifest_sha256=sha256_file(directory / "manifest.json"))
        for stage, directory in stages.items()
    ]


def run_paths(
    settings: Settings,
    config: CityConfig,
    *,
    scenario: str = "baseline",
    on_chunk: Callable[[int, int], None] | None = None,
) -> tuple[PathsManifest, Path]:
    """How the fastest journeys between transit-served zones travel (Phase 5 M3).

    Per zone pair: departures reached, walked all the way, and using the metro; per metro
    station pair: departures. Independent of demand, so it is built once per network.
    """
    demand, mode = _demand_settings(settings, config)
    base = city_dir(settings, config)
    stages = {
        "transit": base / "transit",
        "walk": base / "walk",
        "zones": base / "zones",
        "tt_matrix": base / "tt_matrix" / scenario,
    }
    _require(stages, {"tt_matrix": "tt-matrix"})
    zones = pl.read_parquet(stages["zones"] / "zones.parquet").sort("zone_idx")
    try:
        router = load_router(base, config.routing, config.city.crs_projected)
        metro = metro_network(router, stages["transit"], mode)
        walks = zone_walks(router, base / "walk", zone_points(zones), config.accessibility)
        has_access = np.array([stops.size > 0 for stops, _ in walks.access])
        served = pl.Series(np.flatnonzero(has_access).astype(np.uint32))
        pairs = candidate_pairs(
            pl.scan_parquet(stages["tt_matrix"] / "part-*.parquet"),
            demand.cost.column,
            exclude_intrazonal=demand.exclude_intrazonal,
        ).filter(
            pl.col("origin_zone").is_in(served.implode())
            & pl.col("dest_zone").is_in(served.implode())
        )
        reach, segments = metro_paths(
            router, walks, pairs, metro, config.accessibility, on_chunk=on_chunk
        )
    except (DemandError, RouterError) as exc:
        raise PipelineError(str(exc)) from exc
    access = zones.select("zone_idx").with_columns(
        pl.Series("has_access", has_access),
        pl.Series("access_stops", [stops.size for stops, _ in walks.access], dtype=pl.UInt32),
    )
    out_dir = base / "paths" / scenario
    manifest = write_paths(
        access,
        reach,
        path_shares(reach, segments),
        metro.stations,
        out_dir,
        city=config.city.id,
        scenario=scenario,
        mode=mode,
        departures=len(config.accessibility.departures()),
        inputs=_inputs(stages),
    )
    return manifest, out_dir


def run_demand(
    settings: Settings, config: CityConfig, *, scenario: str = "baseline"
) -> tuple[DemandManifest, DemandBuild, Path]:
    """AM-peak trip ends and the balanced gravity OD matrix (Phase 5 M1-M2)."""
    demand, mode = _demand_settings(settings, config)
    base = city_dir(settings, config)
    stages = {
        "transit": base / "transit",
        "zones": base / "zones",
        "attraction": base / "attraction",
        "tt_matrix": base / "tt_matrix" / scenario,
        "paths": base / "paths" / scenario,
    }
    _require(stages, {"tt_matrix": "tt-matrix"})
    zones = pl.read_parquet(stages["zones"] / "zones.parquet").sort("zone_idx")
    attraction = pl.read_parquet(stages["attraction"] / "attraction.parquet").sort("zone_idx")
    access = pl.read_parquet(stages["paths"] / ACCESS_NAME).sort("zone_idx")
    reach = pl.read_parquet(stages["paths"] / REACH_NAME)
    try:
        check_calibration_names(stages["transit"], mode, demand.calibration)
        result = build_demand(
            zones,
            attraction["employment_score"].to_numpy(),
            access["has_access"].to_numpy(),
            pl.scan_parquet(stages["tt_matrix"] / "part-*.parquet"),
            demand,
            detour_factor=config.scenario.detour_factor,
            walk_pairs=walk_pairs(reach) if demand.exclude_walk_pairs else None,
        )
    except DemandError as exc:
        raise PipelineError(str(exc)) from exc
    out_dir = base / "demand" / scenario
    manifest = write_demand(
        result,
        out_dir,
        city=config.city.id,
        scenario=scenario,
        demand=demand,
        inputs=[
            DemandInput(stage=stage, manifest_sha256=sha256_file(directory / "manifest.json"))
            for stage, directory in stages.items()
        ],
    )
    return manifest, result, out_dir


def run_station_flows(
    settings: Settings, config: CityConfig, *, scenario: str = "baseline"
) -> tuple[MetroManifest, Path]:
    """Simulated metro entries, exits and station-pair flows of the OD matrix (Phase 5 M3)."""
    _, mode = _demand_settings(settings, config)
    base = city_dir(settings, config)
    stages = {"paths": base / "paths" / scenario, "demand": base / "demand" / scenario}
    _require(stages)
    paths_dir = stages["paths"]
    try:
        flows = station_flows(
            pl.read_parquet(stages["demand"] / "od.parquet"),
            pl.read_parquet(paths_dir / REACH_NAME),
            pl.read_parquet(paths_dir / PATHS_NAME),
            pl.read_parquet(paths_dir / STATIONS_NAME),
        )
    except DemandError as exc:
        raise PipelineError(str(exc)) from exc
    out_dir = base / "metro" / scenario
    manifest = write_station_flows(
        flows, out_dir, city=config.city.id, scenario=scenario, mode=mode, inputs=_inputs(stages)
    )
    return manifest, out_dir


def run_ridership(settings: Settings, config: CityConfig) -> tuple[RidershipManifest, Path]:
    """Validate the calibration ridership snapshot into canonical tables (Observed)."""
    demand, mode = _demand_settings(settings, config)
    dataset, snapshot = demand.calibration.dataset, demand.calibration.snapshot
    source = config.source(dataset)
    if source.format is None:
        raise PipelineError(f"source {dataset!r} has no `format` in city.toml")
    manifests = [
        m
        for m in archive.list_snapshots(settings.raw_dir, config.city.id, dataset)
        if m.snapshot == snapshot
    ]
    if not manifests:
        raise PipelineError(
            f"no archived snapshot {snapshot!r} of {dataset!r}; run `glacies ingest register`"
        )
    data_dir = (
        archive.dataset_dir(settings.raw_dir, config.city.id, dataset)
        / snapshot
        / archive.DATA_DIR_NAME
    )
    base = city_dir(settings, config)
    _require({"transit": base / "transit"})
    try:
        ridership = read_ridership(
            data_dir, source.format, network_stations(base / "transit", mode)
        )
    except DemandError as exc:
        raise PipelineError(str(exc)) from exc
    out_dir = base / "ridership" / dataset
    manifest = write_ridership(
        ridership,
        out_dir,
        city=config.city.id,
        dataset=dataset,
        snapshot=snapshot,
        checksum=manifests[0].checksum_sha256,
        fmt=source.format,
    )
    return manifest, out_dir


def run_report(
    settings: Settings, config: CityConfig, *, scenario: str = "baseline"
) -> ReportResult:
    """Maps, Markdown/HTML report and GeoParquet from the accessibility outputs (Phase 3 M4)."""
    base = city_dir(settings, config)
    needed = base / "accessibility" / scenario / "manifest.json"
    if not needed.is_file():
        raise PipelineError(f"missing {needed.parent}; run `glacies build accessibility` first")
    hubs = []
    if config.attraction is not None and config.attraction.validation_hubs:
        try:
            hubs = read_hubs(
                settings.cities_dir / config.city.id / config.attraction.validation_hubs
            )
        except AttractionError as exc:
            raise PipelineError(str(exc)) from exc
    return build_report(base, config, scenario=scenario, hubs=hubs)


def run_postgis(
    settings: Settings, config: CityConfig, *, connect_timeout: int = 10
) -> dict[str, int]:
    _, transit_dir = transit_manifest(settings, config)
    zones_path = city_dir(settings, config) / "zones" / "zones.parquet"
    if not zones_path.is_file():
        raise PipelineError("no zones; run `glacies build zones` first")
    transit = {
        name: pl.read_parquet(transit_dir / f"{name}.parquet")
        for name in ("stops", "routes", "patterns", "pattern_stops", "trips")
    }
    try:
        return postgis.load(
            settings.database_url,
            config.city.id,
            postgis.layers(transit, pl.read_parquet(zones_path)),
            connect_timeout=connect_timeout,
        )
    except psycopg.OperationalError as exc:
        where = settings.database_url.rsplit("@", 1)[-1]  # never echo credentials
        raise PipelineError(
            f"cannot connect to {where} ({str(exc).strip().splitlines()[0]}); "
            "is `docker compose up -d` running?"
        ) from None


# --- whole city -----------------------------------------------------------------------------


class StageRecord(BaseModel):
    stage: str
    directory: str  # relative to data/processed/<city>/
    manifest_sha256: str


class ValidationSummary(BaseModel):
    snapshot: str
    errors: int
    warnings: int
    info: int


class CityBuild(BaseModel):
    """``BUILD.json``: everything needed to say exactly what a processed city was built from."""

    city: str
    builder_version: str
    git_commit: str | None
    git_dirty: bool | None
    city_config_sha256: str
    inputs: list[InputRef]
    validation: dict[str, ValidationSummary]
    stages: list[StageRecord]


@dataclass(frozen=True)
class StageDone:
    stage: str
    summary: str


def git_state(repo: Path, paths: Sequence[str] = ()) -> tuple[str | None, bool | None]:
    """Commit and dirty flag of the source tree, or Nones outside a git checkout.

    With ``paths``, the commit is the last one that changed them and only they count as
    dirty; merge commits that leave them unchanged are skipped by git's history simplification.
    """
    scope = ["--", *paths] if paths else []
    head = ["log", "-1", "--format=%H", *scope] if paths else ["rev-parse", "HEAD"]
    try:
        commit = subprocess.run(
            ["git", *head], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no", *scope],
            cwd=repo, capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return None, None
    return commit or None, bool(status.strip())


def clean_city(settings: Settings, config: CityConfig) -> Path:
    """Delete data/processed/<city>/ (rebuildable output only, never raw data)."""
    target = city_dir(settings, config).resolve()
    if (
        not target.is_relative_to(settings.processed_dir.resolve())
        or target == settings.processed_dir.resolve()
    ):
        raise PipelineError(f"refusing to delete {target}: not a city directory under processed/")
    if target.exists():
        shutil.rmtree(target)
    return target


def build_city(
    settings: Settings,
    config: CityConfig,
    *,
    clean: bool = False,
    force: bool = False,
    load_postgis: bool = False,
    on_stage: Callable[[StageDone], None] | None = None,
) -> CityBuild:
    """Rebuild every processed dataset of a city from its raw archive, then write BUILD.json."""

    def done(stage: str, summary: str) -> None:
        if on_stage is not None:
            on_stage(StageDone(stage, summary))

    issues = archive.verify(settings.raw_dir, config.city.id)
    if issues:
        listed = "; ".join(f"{i.snapshot_dir.name}: {i.problem}" for i in issues[:5])
        raise PipelineError(f"raw archive failed verification ({listed}); fix it before building")
    done("verify", "raw archive matches its manifests")
    if clean:
        done("clean", f"removed {clean_city(settings, config)}")

    network = config.network
    if network is None:
        raise PipelineError(f"city {config.city.id!r} has no [network] section in city.toml")
    reports: dict[str, ValidationReport] = {}
    validation: dict[str, ValidationSummary] = {}
    for dataset in network.feeds:
        report, _ = validate_gtfs(settings, config, dataset)
        reports[dataset] = report
        validation[dataset] = ValidationSummary(
            snapshot=report.snapshot,
            errors=report.count(Severity.ERROR),
            warnings=report.count(Severity.WARNING),
            info=report.count(Severity.INFO),
        )
        done("validate", f"{dataset}: {validation[dataset].errors} errors")

    transit, transit_dir = run_transit(settings, config, force=force, reports=reports)
    done("transit", f"{transit.row_counts['trips']:,} trips")
    walk, _, walk_dir = run_walk(settings, config)
    done("walk", f"{walk.row_counts['edges']:,} edges")
    zones, _, zones_dir = run_zones(settings, config)
    done("zones", f"{zones.row_counts['zones']:,} zones")
    stage_dirs = [("transit", transit_dir), ("walk", walk_dir), ("zones", zones_dir)]
    if config.attraction is not None:
        attraction, _, attraction_dir = run_attraction(settings, config)
        check = attraction.sensitivity[0].hub_check
        done(
            "proxy",
            "employment proxy"
            + (f"; hub check {'passed' if check.passed else 'FAILED'}" if check else ""),
        )
        stage_dirs.append(("attraction", attraction_dir))
    if load_postgis:
        counts = run_postgis(settings, config)
        done("postgis", ", ".join(f"{k} {v:,}" for k, v in counts.items()))

    base = city_dir(settings, config)
    osm_name = source_of_kind(config, "osm_pbf")
    refs = [
        *(_feed_ref(i.dataset, i.snapshot, i.checksum_sha256) for i in transit.inputs),
        _feed_ref(osm_name, walk.osm_snapshot, walk.osm_checksum_sha256),
        *zones.inputs,
    ]
    inputs = {(r.dataset, r.snapshot): r for r in refs}  # OSM is used by walk and zones
    commit, dirty = git_state(Path(__file__).resolve().parents[2])
    build = CityBuild(
        city=config.city.id,
        builder_version=__version__,
        git_commit=commit,
        git_dirty=dirty,
        city_config_sha256=sha256_file(settings.city_config_path),
        inputs=[inputs[k] for k in sorted(inputs)],
        validation=validation,
        stages=[
            StageRecord(
                stage=stage,
                directory=directory.relative_to(base).as_posix(),
                manifest_sha256=sha256_file(directory / "manifest.json"),
            )
            for stage, directory in stage_dirs
        ],
    )
    (base / BUILD_NAME).write_text(build.model_dump_json(indent=2) + "\n", encoding="utf-8")
    done("build", f"wrote {base / BUILD_NAME}")
    return build
