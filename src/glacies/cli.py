"""``glacies`` command-line interface."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from glacies.cities import CityConfig, CityConfigError, load_city
from glacies.config import Settings, get_settings
from glacies.ingest import archive, download

app = typer.Typer(help="Glacies — urban transit digital twin.", no_args_is_help=True)
ingest_app = typer.Typer(
    help="Archive raw datasets with provenance manifests.", no_args_is_help=True
)
app.add_typer(ingest_app, name="ingest")

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
