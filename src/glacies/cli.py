"""``glacies`` command-line interface. Stage logic lives in ``glacies.pipeline``."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import polars as pl
import psutil
import typer

from glacies import pipeline
from glacies.cities import CityConfig, CityConfigError, load_city
from glacies.config import Settings, get_settings
from glacies.ingest import archive, download
from glacies.model.transit.schema import TABLES
from glacies.model.zones.build import population_check
from glacies.pipeline import PipelineError, StageDone
from glacies.routing import bench
from glacies.routing.network import RouterError, clock, load_router, parse_clock
from glacies.routing.validate import read_pairs, report, run_pairs
from glacies.scenario.calibrate import detour_ratios, markdown
from glacies.scenario.compare import compare, format_delta, format_value
from glacies.scenario.mutations import apply
from glacies.scenario.runner import run_scenario
from glacies.scenario.schema import ScenarioError, json_schema_text, load_scenario
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
bench_app = typer.Typer(help="Measure performance on the real network.", no_args_is_help=True)
app.add_typer(bench_app, name="bench")
scenario_app = typer.Typer(help="Define and check network scenarios.", no_args_is_help=True)
app.add_typer(scenario_app, name="scenario")

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


def _peak_mb() -> float:
    """Peak memory of this process (Windows reports it; elsewhere the current size)."""
    info = psutil.Process().memory_info()
    return float(getattr(info, "peak_wset", info.rss)) / 2**20


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


@build_app.command("tt-matrix")
def build_travel_time_matrix(city: CityOption = None) -> None:
    """Zone-to-zone travel-time percentiles over the departure window (Simulated)."""
    settings, config = _load(city)
    started = time.perf_counter()

    def progress(done: int, total: int) -> None:
        elapsed = time.perf_counter() - started
        typer.echo(f"  {done:,}/{total:,} origins ({elapsed:.0f} s)")

    try:
        result = pipeline.run_matrix(settings, config, on_chunk=progress)
    except PipelineError as exc:
        _fail(str(exc))
    m = result.manifest
    typer.echo(
        f"travel-time matrix: {m.zones:,} zones x {m.departures} departures, {m.rows:,} rows "
        f"in {time.perf_counter() - started:.0f} s (peak memory {_peak_mb():,.0f} MB) "
        f"-> {result.out_dir}"
    )


@build_app.command("accessibility")
def build_zone_accessibility(city: CityOption = None) -> None:
    """Share of estimated jobs and population reachable per zone and threshold (Simulated)."""
    settings, config = _load(city)
    try:
        manifest, out_dir = pipeline.run_accessibility(settings, config)
    except PipelineError as exc:
        _fail(str(exc))
    s = manifest.settings
    typer.echo(f"accessibility -> {out_dir}")
    typer.echo(
        f"headline: residents reach on average {manifest.headline_est_jobs_share:.1%} of the "
        f"city's estimated jobs within {s.headline_threshold_min} min (p{s.headline_percentile}, "
        f"population-weighted); {manifest.edge_zones:,} edge zones flagged"
    )


@build_app.command("demand")
def build_synthetic_demand(city: CityOption = None) -> None:
    """AM-peak trip ends and a doubly constrained gravity OD matrix (Estimated)."""
    settings, config = _load(city)
    try:
        manifest, _, out_dir = pipeline.run_demand(settings, config)
    except PipelineError as exc:
        _fail(str(exc))
    s, c, t = manifest.trip_ends, manifest.convergence, manifest.trip_length
    typer.echo(f"demand (Estimated) -> {out_dir}")
    typer.echo(
        f"  {s.trips:,.0f} trips (range {s.trips_low:,.0f}-{s.trips_high:,.0f}) from "
        f"{s.origin_zones:,} to {s.destination_zones:,} zones; {manifest.od_pairs:,} pairs"
    )
    typer.echo(
        f"  Furness converged in {c.iterations} iterations (row error {c.max_row_error:.1e})"
    )
    typer.echo(
        f"  mean trip {t.mean_cost_min:.1f} min, {t.mean_km:.1f} km "
        f"({'within' if t.within_accepted_range else 'OUTSIDE'} {t.accept_km[0]:g}-"
        f"{t.accept_km[1]:g} km)"
    )


@build_app.command("station-flows")
def build_station_flows(city: CityOption = None) -> None:
    """Simulated metro entries, exits and station-pair flows of the OD matrix."""
    settings, config = _load(city)

    def progress(done: int, total: int) -> None:
        typer.echo(f"  {done:,}/{total:,} origins", err=True)

    try:
        manifest, out_dir = pipeline.run_station_flows(settings, config, on_chunk=progress)
    except PipelineError as exc:
        _fail(str(exc))
    s = manifest.stats
    typer.echo(f"{manifest.mode} station flows (Simulated) -> {out_dir}")
    typer.echo(
        f"  {s.trips:,.0f} trips: {s.trips_using_metro:,.0f} use the {manifest.mode} "
        f"({s.trips_using_metro / s.trips:.1%}), {s.entries:,.0f} station entries, "
        f"{s.trips_walked:,.0f} walk all the way, {s.trips_unreached:,.0f} not reached"
    )


@app.command("accessibility")
def accessibility_report(
    city: Annotated[
        str | None, typer.Argument(help="City id under cities/ (default: GLACIES_CITY).")
    ] = None,
) -> None:
    """Write the accessibility report: maps, Markdown/HTML and a GeoParquet for QGIS."""
    settings, config = _load(city)
    try:
        result = pipeline.run_report(settings, config)
    except PipelineError as exc:
        _fail(str(exc))
    typer.echo(
        f"report for {result.zones:,} zones with {len(result.maps)} maps -> {result.out_dir}"
    )
    typer.echo("  open report.html, or add accessibility.geoparquet as a layer in QGIS")


@build_app.command("attraction")
def build_employment_proxy(city: CityOption = None) -> None:
    """Estimate employment per zone (Phase 3 proxy) and check it against known hubs."""
    settings, config = _load(city)
    try:
        manifest, result, out_dir = pipeline.run_attraction(settings, config)
    except PipelineError as exc:
        _fail(str(exc))
    typer.echo(f"employment proxy (Estimated) for {result.table.height:,} zones -> {out_dir}")
    for row in manifest.sensitivity:
        check = row.hub_check
        if check is not None:
            typer.echo(
                f"  {row.weighting}: {check.share_in_pass_rank:.0%} of {check.hub_zones} hub "
                f"zones in top {manifest.params.hub_pass_rank:.0%}, "
                f"{check.share_in_report_rank:.0%} in top {manifest.params.hub_report_rank:.0%}, "
                f"concentration {check.concentration:.2f}x"
            )
    base = manifest.sensitivity[0].hub_check
    if base is not None:
        typer.echo(f"hub check: {'PASSED' if base.passed else 'FAILED'} (baseline)")
    if manifest.hubs_missing:
        typer.echo("hubs overlapping no zone: " + ", ".join(manifest.hubs_missing))


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


@validate_app.command("routing")
def validate_routing(
    sanity: Annotated[
        Path, typer.Option(help="CSV of reference journeys with coordinates.")
    ] = Path("docs/validation/bengaluru-sanity-set.csv"),
    out: Annotated[Path, typer.Option(help="Where to write the Markdown report.")] = Path(
        "docs/validation/routing.md"
    ),
    share: Annotated[float, typer.Option(help="Allowed relative difference.")] = 0.2,
    minutes: Annotated[int, typer.Option(help="Allowed absolute difference (minutes).")] = 5,
    city: CityOption = None,
) -> None:
    """Run reference journeys through the router and compare with their expected times."""
    settings, config = _load(city)
    try:
        router = load_router(
            pipeline.city_dir(settings, config), config.routing, config.city.crs_projected
        )
        pairs = read_pairs(sanity)
    except (RouterError, OSError, ValueError) as exc:
        _fail(str(exc))
    results = run_pairs(router, pairs)
    network = config.network
    service_day = network.service_date.isoformat() if network else "?"
    header = (
        f"City `{config.city.id}`, timetable of {service_day}, max {config.routing.max_rounds} "
        f"vehicles, {config.routing.min_transfer_time_s} s minimum transfer, walking "
        f"{config.routing.walking_speed_m_s} m/s (access ≤ {config.routing.max_access_walk_m:g} m, "
        f"transfers ≤ {config.routing.max_transfer_walk_m:g} m)."
    )
    if config.routing.station_entry_s:
        entry = ", ".join(
            f"{mode} {seconds} s"
            for mode, seconds in sorted(config.routing.station_entry_s.items())
        )
        header += f" Station entry (free when changing within a station): {entry}."
    text, passed = report(results, share=share, minutes=minutes, header=header)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")  # same bytes on every OS
    typer.echo(f"{passed} of {len(results)} pairs within tolerance -> {out}")


@bench_app.command("routing")
def bench_routing(
    samples: Annotated[int, typer.Option(help="Random stops per query type.")] = 200,
    seed: Annotated[int, typer.Option(help="Seed for the stop sample.")] = 2026,
    out: Annotated[Path, typer.Option(help="Where to write the Markdown report.")] = Path(
        "docs/validation/routing-benchmark.md"
    ),
    city: CityOption = None,
) -> None:
    """Time router build, one-to-one, one-to-all and range searches; estimate a zone matrix."""
    settings, config = _load(city)
    try:
        result = bench.run(pipeline.city_dir(settings, config), config, samples=samples, seed=seed)
    except (RouterError, OSError) as exc:
        _fail(str(exc))
    header = f"City `{config.city.id}`, {samples} seeded random stops (seed {seed})."
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(bench.markdown(result, header), encoding="utf-8", newline="\n")
    for timing in result.timings:
        typer.echo(f"{timing.name}: median {timing.median_ms} ms, p95 {timing.p95_ms} ms")
    typer.echo(
        f"all-zones 120-min matrix estimate: {result.all_zones_estimate_min} min; "
        f"peak memory {result.peak_rss_mb:,.0f} MB -> {out}"
    )


@scenario_app.command("schema")
def scenario_schema(
    out: Annotated[Path, typer.Option(help="Where to write the JSON Schema.")] = Path(
        "schemas/scenario.schema.json"
    ),
) -> None:
    """Write the JSON Schema of scenario files (for editors and other tools)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json_schema_text(), encoding="utf-8", newline="\n")
    typer.echo(f"scenario schema -> {out}")


@scenario_app.command("check")
def scenario_check(
    path: Annotated[Path, typer.Argument(help="Scenario JSON file.")],
    city: CityOption = None,
) -> None:
    """Validate a scenario, apply it to the baseline network and report what each mutation does."""
    settings, config = _load(city)
    try:
        scenario = load_scenario(path)
        _, transit_dir = pipeline.transit_manifest(settings, config)
        tables = {name: pl.read_parquet(transit_dir / f"{name}.parquet") for name in TABLES}
        applied = apply(tables, scenario, config.scenario)
    except (ScenarioError, PipelineError) as exc:
        _fail(str(exc))
    for change in applied.changes:
        typer.echo(
            f"  {change.mutation}. {change.type} {change.route_id}: "
            f"-{change.trips_removed:,} / +{change.trips_added:,} trips"
        )
    before, after = tables["trips"].height, applied.tables["trips"].height
    typer.echo(f"{scenario.scenario_id}: OK; trips {before:,} -> {after:,}")


@scenario_app.command("calibrate")
def scenario_calibrate(
    samples: Annotated[int, typer.Option(help="Consecutive-stop pairs to measure.")] = 2000,
    seed: Annotated[int, typer.Option(help="Seed for the sample.")] = 2026,
    out: Annotated[Path, typer.Option(help="Where to write the Markdown report.")] = Path(
        "docs/validation/scenario-detour.md"
    ),
    city: CityOption = None,
) -> None:
    """Measure road over straight-line distance between consecutive bus stops (detour factor)."""
    settings, config = _load(city)
    city_path = pipeline.city_dir(settings, config)
    try:
        result = detour_ratios(city_path, samples=samples, seed=seed)
    except (OSError, pl.exceptions.PolarsError) as exc:
        _fail(str(exc))
    if result.ratios.size == 0:
        _fail("no consecutive stop pairs could be measured")
    header = f"City `{config.city.id}`; current `[scenario] detour_factor` = "
    header += f"{config.scenario.detour_factor}."
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(result, header), encoding="utf-8", newline="\n")
    typer.echo(
        f"{result.ratios.size:,} pairs: median {result.percentile(50):.2f}, "
        f"mean {result.mean:.2f} -> {out}"
    )


@scenario_app.command("run")
def scenario_run(
    path: Annotated[Path, typer.Argument(help="Scenario JSON file.")],
    force: Annotated[bool, typer.Option("--force", help="Recompute even if cached.")] = False,
    full: Annotated[
        bool, typer.Option("--full", help="Recompute every origin (implies --force).")
    ] = False,
    city: CityOption = None,
) -> None:
    """Apply a scenario, then rebuild travel times and accessibility on it (cached).

    Only origins that can reach a changed trip are recomputed; the rest of the matrix is
    copied from the baseline, which gives the same result as a full recompute.
    """
    settings, config = _load(city)
    started = time.perf_counter()

    def stage(name: str) -> None:
        typer.echo(f"[{time.perf_counter() - started:5.0f} s] {name}")

    def progress(done: int, total: int) -> None:
        if done == total or done % 2048 == 0:
            typer.echo(f"  {done:,}/{total:,} origins")

    try:
        outcome = run_scenario(
            settings, config, path, force=force, full=full, on_stage=stage, on_chunk=progress
        )
    except (ScenarioError, PipelineError) as exc:
        _fail(str(exc))
    r = outcome.record
    if outcome.cached:
        typer.echo(f"cached result (computed {r.finished_at})")
    for c in r.changes:
        typer.echo(
            f"  {c.mutation}. {c.type} {c.route_id}: "
            f"-{c.trips_removed:,} / +{c.trips_added:,} trips"
        )
    if r.engine.git_dirty:
        typer.echo("note: uncommitted changes in the source tree; the cache was not read")
    typer.echo(
        f"{r.scenario_id}: headline {r.headline_est_jobs_share:.2%} of estimated jobs "
        f"(Simulated) -> {outcome.out_dir}"
    )


@scenario_app.command("compare")
def scenario_compare(
    a: Annotated[str, typer.Argument(help="`baseline` or a scenario file (A).")],
    b: Annotated[str, typer.Argument(help="`baseline` or a scenario file (B).")],
    city: CityOption = None,
) -> None:
    """Compare two run networks: metrics table, zone deltas, map and Markdown report."""
    settings, config = _load(city)
    try:
        result = compare(settings, config, a, b)
    except (ScenarioError, PipelineError) as exc:
        _fail(str(exc))
    m = result.manifest
    typer.echo(f"{m.b.label} vs {m.a.label} (Simulated)")
    for name, va, vb, unit, delta in result.metrics.select(
        "metric", "a", "b", "unit", "delta"
    ).iter_rows():
        typer.echo(
            f"  {name}: {format_value(va, unit)} -> {format_value(vb, unit)} "
            f"({format_delta(delta, unit)})"
        )
    typer.echo(f"direction check: {m.direction_check}")
    typer.echo(f"report -> {result.out_dir / 'comparison.md'}")
