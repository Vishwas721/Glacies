"""``glacies`` command-line interface. Stage logic lives in ``glacies.pipeline``."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from glacies import pipeline
from glacies.cities import CityConfig, CityConfigError, load_city
from glacies.config import Settings, get_settings
from glacies.ingest import archive, download
from glacies.model.zones.build import population_check
from glacies.pipeline import PipelineError, StageDone
from glacies.routing.network import RouterError, clock, load_router, parse_clock
from glacies.validate.gtfs.report import Severity

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
    try:
        report, out_dir = pipeline.validate_gtfs(settings, config, dataset, snapshot)
    except PipelineError as exc:
        _fail(str(exc))
    errors, warnings = report.count(Severity.ERROR), report.count(Severity.WARNING)
    typer.echo(
        f"{dataset} @ {report.snapshot}: {errors} errors, {warnings} warnings, "
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
    try:
        manifest, out_dir = pipeline.run_transit(settings, config, force=force)
    except PipelineError as exc:
        _fail(str(exc))
    counts = manifest.row_counts
    typer.echo(
        f"transit network for {manifest.service_date}: {counts['stops']:,} stops, "
        f"{counts['routes']:,} routes, {counts['patterns']:,} patterns, {counts['trips']:,} trips, "
        f"{counts['stop_times']:,} stop times -> {out_dir}"
    )
    for dataset, reasons in manifest.dropped_by_reason.items():
        typer.echo(
            f"dropped from {dataset}: " + ", ".join(f"{r} {n:,}" for r, n in reasons.items())
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
    typer.echo("reading OSM ...")
    try:
        _, result, out_dir = pipeline.run_walk(settings, config, source=source)
    except PipelineError as exc:
        _fail(str(exc))
    s = result.stats
    typer.echo(
        f"walk network: {s['nodes']:,} nodes, {s['edges']:,} edges, "
        f"{s['network_length_km']:,} km; largest component {s['largest_component_share']:.1%}"
    )
    typer.echo(
        f"stops snapped: {s['stops_snapped']:,}, flagged > {config.walk.max_snap_m:g} m: "
        f"{s['stops_flagged']:,} -> {out_dir}"
    )


@build_app.command("zones")
def build_zone_layers(city: CityOption = None) -> None:
    """Build H3 zones with population, buildings, land cover, POIs and stop counts."""
    settings, config = _load(city)
    typer.echo("aggregating population, land cover, buildings and POIs ...")
    try:
        _, result, out_dir = pipeline.run_zones(settings, config)
    except PipelineError as exc:
        _fail(str(exc))
    s = result.stats
    conservation, ratio = population_check(s)
    typer.echo(
        f"zones: {s['zones']:,} ({s['zones_populated']:,} populated); population "
        f"{s['population_zones']:,.0f} (zones / bbox {ratio:.2%}, conservation error "
        f"{conservation:.1e}); buildings {s['buildings_read']:,}; POIs {s['pois']:,} -> {out_dir}"
    )


@load_app.command("postgis")
def load_postgis(
    connect_timeout: Annotated[int, typer.Option(help="Seconds to wait for the database.")] = 10,
    city: CityOption = None,
) -> None:
    """Load zones, stops and route pattern lines into PostGIS (schema = city id)."""
    settings, config = _load(city)
    try:
        counts = pipeline.run_postgis(settings, config, connect_timeout=connect_timeout)
    except PipelineError as exc:
        _fail(str(exc))
    typer.echo(
        "loaded into schema "
        f"{config.city.id!r}: " + ", ".join(f"{name} {n:,}" for name, n in counts.items())
    )


@app.command("build-city")
def build_city(
    city: Annotated[
        str | None, typer.Argument(help="City id under cities/ (default: GLACIES_CITY).")
    ] = None,
    clean: Annotated[
        bool, typer.Option("--clean", help="Delete data/processed/<city>/ first (raw is kept).")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Build even if a feed has validation errors.")
    ] = False,
    postgis: Annotated[
        bool, typer.Option("--postgis", help="Also load the layers into PostGIS.")
    ] = False,
) -> None:
    """Rebuild every processed dataset of a city from its raw archive, then write BUILD.json."""
    settings, config = _load(city)
    started = last = time.perf_counter()

    def report(stage: StageDone) -> None:
        nonlocal last
        now = time.perf_counter()
        typer.echo(f"[{stage.stage:<8}] {stage.summary} ({now - last:.1f} s)")
        last = now

    try:
        pipeline.build_city(
            settings, config, clean=clean, force=force, load_postgis=postgis, on_stage=report
        )
    except PipelineError as exc:
        _fail(str(exc))
    typer.echo(f"city {config.city.id!r} built in {time.perf_counter() - started:.0f} s")


def _point(text: str) -> tuple[float, float]:
    try:
        lat, lon = (float(part) for part in text.split(","))
    except ValueError:
        _fail(f"invalid point {text!r}; use LAT,LON e.g. 12.9766,77.5713")
    return lat, lon


@app.command()
def route(
    origin: Annotated[str, typer.Argument(help="Origin as LAT,LON.")],
    destination: Annotated[str, typer.Argument(help="Destination as LAT,LON.")],
    at: Annotated[str, typer.Option("--at", help="Departure time HH:MM on the service day.")],
    city: CityOption = None,
) -> None:
    """Plan journeys between two points on the canonical network (results are Simulated)."""
    settings, config = _load(city)
    started = time.perf_counter()
    try:
        router = load_router(
            pipeline.city_dir(settings, config), config.routing, config.city.crs_projected
        )
        built = time.perf_counter()
        journeys = router.plan(_point(origin), _point(destination), parse_clock(at))
    except RouterError as exc:
        _fail(str(exc))
    typer.echo(
        f"router: {router.timetable.route_count:,} routes, {router.timetable.trip_count:,} trips, "
        f"{router.transfer_count:,} transfer walks (built in {built - started:.1f} s)"
    )
    if not journeys:
        typer.echo("no journey found")
        return
    for journey in journeys:
        typer.echo()
        typer.echo(
            f"arrive {clock(journey.arrival)} · {journey.travel_time // 60} min · "
            f"{journey.transfers} transfer(s) · walk {journey.walking_time // 60} min · "
            f"wait {journey.waiting_time // 60} min  [Simulated]"
        )
        for line in router.describe(journey):
            typer.echo(f"  {line}")
