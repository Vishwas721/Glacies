"""``glacies`` command-line interface."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import polars as pl
import psycopg
import typer

from glacies.cities import CityConfig, CityConfigError, load_city
from glacies.config import Settings, get_settings
from glacies.db import postgis
from glacies.ingest import archive, download
from glacies.model.transit.build import FeedInput, TransitBuildError, build_transit
from glacies.model.transit.writer import MANIFEST_NAME as TRANSIT_MANIFEST
from glacies.model.transit.writer import TransitManifest, write_transit
from glacies.model.walk.build import build_walk
from glacies.model.walk.extract import extract_walk_segments
from glacies.model.walk.writer import write_walk
from glacies.model.zones.build import (
    InputRef,
    ZoneInputs,
    build_zones,
    population_check,
    stop_modes,
    write_zones,
)
from glacies.provenance import DatasetManifest
from glacies.validate.gtfs.report import Severity, Thresholds, ValidationReport
from glacies.validate.gtfs.validator import ValidationOptions, validate_feed

app = typer.Typer(help="Glacies — urban transit digital twin.", no_args_is_help=True)
ingest_app = typer.Typer(
    help="Archive raw datasets with provenance manifests.", no_args_is_help=True
)
app.add_typer(ingest_app, name="ingest")
validate_app = typer.Typer(help="Validate archived datasets.", no_args_is_help=True)
app.add_typer(validate_app, name="validate")
build_app = typer.Typer(help="Build canonical datasets from archived inputs.", no_args_is_help=True)
app.add_typer(build_app, name="build")
load_app = typer.Typer(help="Copy canonical layers into databases.", no_args_is_help=True)
app.add_typer(load_app, name="load")

CityOption = Annotated[
    str | None, typer.Option("--city", help="City id under cities/ (default: GLACIES_CITY).")
]


def _fail(message: str) -> NoReturn:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _load(city: str | None) -> tuple[Settings, CityConfig]:
    settings = get_settings()
    if city:
        settings = settings.model_copy(update={"city": city})
    try:
        return settings, load_city(settings.city_config_path)
    except CityConfigError as exc:
        _fail(str(exc))


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


@ingest_app.command("list")
def list_sources(city: CityOption = None) -> None:
    """Show every source in city.toml and its archived snapshots."""
    settings, config = _load(city)
    for name in sorted(config.sources):
        source = config.sources[name]
        snapshots = archive.list_snapshots(settings.raw_dir, config.city.id, name)
        typer.echo(
            f"{name:<24} {source.kind:<18} {source.nature.value:<9} "
            f"{'verified' if source.verified else 'UNVERIFIED':<10} "
            f"{'fetch' if source.download_url else 'manual':<6} "
            f"{', '.join(m.snapshot for m in snapshots) or '-'}"
        )


@ingest_app.command()
def register(
    dataset: Annotated[str, typer.Argument(help="Source id from city.toml.")],
    path: Annotated[Path, typer.Argument(help="Downloaded file or directory to archive.")],
    snapshot: Annotated[
        str, typer.Option(help="Snapshot name, e.g. the feed version or download date.")
    ],
    copy: Annotated[
        bool, typer.Option("--copy", help="Copy instead of moving the source.")
    ] = False,
    version: Annotated[str | None, typer.Option(help="Upstream version, if known.")] = None,
    city: CityOption = None,
) -> None:
    """Archive files you downloaded manually (moved into data/raw by default)."""
    settings, config = _load(city)
    try:
        result = archive.register(
            raw_dir=settings.raw_dir,
            city=config,
            dataset=dataset,
            source_path=path,
            snapshot=snapshot,
            move=not copy,
            version=version,
        )
    except (archive.ArchiveError, CityConfigError, OSError) as exc:
        _fail(str(exc))
    _report(result, path)


@ingest_app.command()
def fetch(
    dataset: Annotated[str, typer.Argument(help="Source id from city.toml.")],
    snapshot: Annotated[
        str | None, typer.Option(help="Snapshot name (default: today's UTC date).")
    ] = None,
    city: CityOption = None,
) -> None:
    """Download a source with a download_url and archive it."""
    settings, config = _load(city)
    try:
        result = download.fetch(
            raw_dir=settings.raw_dir,
            city=config,
            dataset=dataset,
            snapshot=snapshot or datetime.now(UTC).strftime("%Y-%m-%d"),
        )
    except (archive.ArchiveError, CityConfigError, OSError) as exc:
        _fail(str(exc))
    _report(result, None)


def _report(result: archive.RegisterResult, source: Path | None) -> None:
    if result.status == "already_archived":
        typer.echo(f"already archived as {result.snapshot_dir} (identical content); nothing moved.")
        if source is not None:
            typer.echo(f"{source} is a duplicate of the archive and can be deleted.")
        return
    files = result.manifest.files
    size = _human_size(sum(f.bytes for f in files))
    typer.echo(f"archived {len(files)} files ({size}) -> {result.snapshot_dir}")


@ingest_app.command()
def verify(city: CityOption = None) -> None:
    """Re-hash archived snapshots and report anything that changed."""
    settings, config = _load(city)
    issues = archive.verify(settings.raw_dir, config.city.id)
    for issue in issues:
        typer.secho(f"{issue.snapshot_dir}: {issue.problem}", fg=typer.colors.RED)
    if issues:
        raise typer.Exit(1)
    count = len(list((settings.raw_dir / config.city.id).glob(f"*/*/{archive.MANIFEST_NAME}")))
    typer.echo(f"{count} snapshot(s) OK")


class FailOn(StrEnum):
    NEVER = "never"
    ERROR = "error"
    WARNING = "warning"


def _gtfs_snapshot(
    settings: Settings, config: CityConfig, dataset: str, snapshot: str | None
) -> tuple[DatasetManifest, Path]:
    """The requested (or most recently archived) snapshot of a GTFS source, and its data dir."""
    try:
        source = config.source(dataset)
    except CityConfigError as exc:
        _fail(str(exc))
    if source.kind != "gtfs":
        _fail(f"{dataset!r} is a {source.kind!r} source, not GTFS")
    snapshots = archive.list_snapshots(settings.raw_dir, config.city.id, dataset)
    if snapshot is not None:
        snapshots = [m for m in snapshots if m.snapshot == snapshot]
    if not snapshots:
        _fail(f"no archived snapshot of {dataset!r}; run `glacies ingest register` first")
    manifest = max(snapshots, key=lambda m: (m.archived_at, m.snapshot))
    snapshot_dir = (
        archive.dataset_dir(settings.raw_dir, config.city.id, dataset) / manifest.snapshot
    )
    return manifest, snapshot_dir / archive.DATA_DIR_NAME


def _validate(
    config: CityConfig, dataset: str, manifest: DatasetManifest, data_dir: Path
) -> ValidationReport:
    source = config.source(dataset)
    return validate_feed(
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


@validate_app.command("gtfs")
def validate_gtfs(
    dataset: Annotated[str, typer.Argument(help="GTFS source id from city.toml.")],
    snapshot: Annotated[
        str | None, typer.Option(help="Snapshot to validate (default: most recently archived).")
    ] = None,
    fail_on: Annotated[
        FailOn, typer.Option(help="Exit with status 1 if findings of this severity exist.")
    ] = FailOn.NEVER,
    city: CityOption = None,
) -> None:
    """Validate an archived GTFS snapshot and write JSON + Markdown reports."""
    settings, config = _load(city)
    manifest, data_dir = _gtfs_snapshot(settings, config, dataset, snapshot)
    report = _validate(config, dataset, manifest, data_dir)
    out_dir = settings.processed_dir / config.city.id / "reports" / dataset / manifest.snapshot
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gtfs_validation.json").write_text(report.to_json(), encoding="utf-8")
    (out_dir / "gtfs_validation.md").write_text(report.to_markdown(), encoding="utf-8")

    errors, warnings = report.count(Severity.ERROR), report.count(Severity.WARNING)
    typer.echo(
        f"{dataset} @ {manifest.snapshot}: {errors} errors, {warnings} warnings, "
        f"{report.count(Severity.INFO)} info -> {out_dir}"
    )
    cov = report.coverage
    if cov.ratio_min is not None and cov.ratio_max is not None:
        typer.echo(f"coverage ratio vs reference: {cov.ratio_min:.0%} to {cov.ratio_max:.0%}")
    if (fail_on is FailOn.ERROR and errors) or (fail_on is FailOn.WARNING and errors + warnings):
        raise typer.Exit(1)


@build_app.command("transit")
def build_transit_network(
    force: Annotated[
        bool, typer.Option("--force", help="Build even if a feed has validation errors.")
    ] = False,
    city: CityOption = None,
) -> None:
    """Build the canonical transit network from the feeds in city.toml [network]."""
    settings, config = _load(city)
    network = config.network
    if network is None:
        _fail(f"city {config.city.id!r} has no [network] section in city.toml")

    inputs: list[FeedInput] = []
    for dataset in network.feeds:
        snapshot, data_dir = _gtfs_snapshot(settings, config, dataset, None)
        errors = _validate(config, dataset, snapshot, data_dir).errors
        if errors and not force:
            rules = ", ".join(sorted({f.rule for f in errors}))
            _fail(
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
        _fail(str(exc))
    out_dir = settings.processed_dir / config.city.id / "transit"
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
    counts = manifest.row_counts
    typer.echo(
        f"transit network for {network.service_date.isoformat()}: {counts['stops']:,} stops, "
        f"{counts['routes']:,} routes, {counts['patterns']:,} patterns, {counts['trips']:,} trips, "
        f"{counts['stop_times']:,} stop times -> {out_dir}"
    )
    for dataset, reasons in manifest.dropped_by_reason.items():
        typer.echo(
            f"dropped from {dataset}: " + ", ".join(f"{r} {n:,}" for r, n in reasons.items())
        )


def _single_file_snapshot(
    settings: Settings, config: CityConfig, kind: str
) -> tuple[str, DatasetManifest, Path]:
    """(source id, newest snapshot, its only file) of the single source of ``kind``."""
    names = sorted(n for n, s in config.sources.items() if s.kind == kind)
    if len(names) != 1:
        _fail(f"expected exactly one {kind!r} source in city.toml, found {names or 'none'}")
    name = names[0]
    snapshots = archive.list_snapshots(settings.raw_dir, config.city.id, name)
    if not snapshots:
        _fail(f"no archived snapshot of {name!r}; run `glacies ingest register` first")
    manifest = max(snapshots, key=lambda m: (m.archived_at, m.snapshot))
    files = [f.path for f in manifest.files]
    if len(files) != 1:
        _fail(f"expected exactly one file in {name} @ {manifest.snapshot}, found {files}")
    data_dir = archive.dataset_dir(settings.raw_dir, config.city.id, name) / manifest.snapshot
    return name, manifest, data_dir / archive.DATA_DIR_NAME / files[0]


def _transit_tables(settings: Settings, config: CityConfig) -> tuple[TransitManifest, Path]:
    transit_dir = settings.processed_dir / config.city.id / "transit"
    if not (transit_dir / TRANSIT_MANIFEST).is_file():
        _fail("no canonical transit network; run `glacies build transit` first")
    manifest = TransitManifest.model_validate_json(
        (transit_dir / TRANSIT_MANIFEST).read_text(encoding="utf-8")
    )
    return manifest, transit_dir


@build_app.command("zones")
def build_zone_layers(city: CityOption = None) -> None:
    """Build H3 zones with population, buildings, land cover, POIs and stop counts."""
    settings, config = _load(city)
    inputs: list[InputRef] = []
    paths: dict[str, Path] = {}
    for kind in ("population_raster", "landcover_raster", "buildings", "osm_pbf"):
        name, manifest, path = _single_file_snapshot(settings, config, kind)
        inputs.append(
            InputRef(
                dataset=name, snapshot=manifest.snapshot, checksum_sha256=manifest.checksum_sha256
            )
        )
        paths[kind] = path
    transit, transit_dir = _transit_tables(settings, config)
    tables = {
        name: pl.read_parquet(transit_dir / f"{name}.parquet")
        for name in ("stops", "stop_times", "trips", "routes")
    }
    zoning = config.zoning
    typer.echo("aggregating population, land cover, buildings and POIs ...")
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
    out_dir = settings.processed_dir / config.city.id / "zones"
    write_zones(
        result,
        out_dir,
        city=config.city.id,
        bbox=config.city.bbox,
        resolution=zoning.resolution,
        thresholds=zoning.building_confidence_thresholds,
        inputs=inputs,
        transit_stops_sha256=transit.outputs["stops.parquet"],
    )
    s = result.stats
    conservation, ratio = population_check(s)
    typer.echo(
        f"zones: {s['zones']:,} ({s['zones_populated']:,} populated); population "
        f"{s['population_zones']:,.0f} (zones / bbox {ratio:.2%}, conservation error "
        f"{conservation:.1e}); buildings {s['buildings_read']:,}; POIs {s['pois']:,} -> {out_dir}"
    )


@build_app.command("walk")
def build_walk_network(
    source: Annotated[
        str | None, typer.Option(help="OSM source id (default: the only osm_pbf source).")
    ] = None,
    city: CityOption = None,
) -> None:
    """Build the pedestrian network from OSM and snap the transit stops onto it."""
    settings, config = _load(city)
    osm_sources = sorted(n for n, s in config.sources.items() if s.kind == "osm_pbf")
    if source is None:
        if len(osm_sources) != 1:
            _fail(f"pass --source; osm_pbf sources in city.toml: {osm_sources or 'none'}")
        source = osm_sources[0]
    elif source not in osm_sources:
        _fail(f"{source!r} is not an osm_pbf source; choose from {osm_sources}")

    snapshots = archive.list_snapshots(settings.raw_dir, config.city.id, source)
    if not snapshots:
        _fail(f"no archived snapshot of {source!r}; run `glacies ingest register` first")
    osm = max(snapshots, key=lambda m: (m.archived_at, m.snapshot))
    data_dir = archive.dataset_dir(settings.raw_dir, config.city.id, source) / osm.snapshot
    files = [f.path for f in osm.files]
    if len(files) != 1:
        _fail(f"expected exactly one OSM file in {source} @ {osm.snapshot}, found {files}")
    osm_file = data_dir / archive.DATA_DIR_NAME / files[0]

    transit_dir = settings.processed_dir / config.city.id / "transit"
    if not (transit_dir / TRANSIT_MANIFEST).is_file():
        _fail("no canonical transit network; run `glacies build transit` first")
    transit = TransitManifest.model_validate_json(
        (transit_dir / TRANSIT_MANIFEST).read_text(encoding="utf-8")
    )
    stops = pl.read_parquet(transit_dir / "stops.parquet")
    boarding = stops.filter(pl.col("location_type") == 0)

    typer.echo(f"reading {osm_file.name} ...")
    segments, extract_stats = extract_walk_segments(osm_file, config.city.bbox, config.walk)
    result = build_walk(segments, boarding, config.walk, config.city.crs_projected)
    out_dir = settings.processed_dir / config.city.id / "walk"
    write_walk(
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
    s = result.stats
    typer.echo(
        f"walk network: {s['nodes']:,} nodes, {s['edges']:,} edges, "
        f"{s['network_length_km']:,} km; largest component {s['largest_component_share']:.1%}"
    )
    typer.echo(
        f"stops snapped: {s['stops_snapped']:,}, flagged > {config.walk.max_snap_m:g} m: "
        f"{s['stops_flagged']:,} -> {out_dir}"
    )


@load_app.command("postgis")
def load_postgis(
    connect_timeout: Annotated[int, typer.Option(help="Seconds to wait for the database.")] = 10,
    city: CityOption = None,
) -> None:
    """Load zones, stops and route pattern lines into PostGIS (schema = city id)."""
    settings, config = _load(city)
    _, transit_dir = _transit_tables(settings, config)
    zones_path = settings.processed_dir / config.city.id / "zones" / "zones.parquet"
    if not zones_path.is_file():
        _fail("no zones; run `glacies build zones` first")
    transit = {
        name: pl.read_parquet(transit_dir / f"{name}.parquet")
        for name in ("stops", "routes", "patterns", "pattern_stops", "trips")
    }
    try:
        counts = postgis.load(
            settings.database_url,
            config.city.id,
            postgis.layers(transit, pl.read_parquet(zones_path)),
            connect_timeout=connect_timeout,
        )
    except psycopg.OperationalError as exc:
        _fail(
            f"cannot connect to {settings.database_url.rsplit('@', 1)[-1]} "
            f"({str(exc).strip().splitlines()[0]}); is `docker compose up -d` running?"
        )
    typer.echo(
        "loaded into schema "
        f"{config.city.id!r}: " + ", ".join(f"{name} {n:,}" for name, n in counts.items())
    )
