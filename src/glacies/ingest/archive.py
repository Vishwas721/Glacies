"""Append-only raw-data archive: ``<raw>/<city>/<dataset>/<snapshot>/{data/, manifest.json}``.

A snapshot is never modified after it is written. New content gets a new snapshot; identical
content is recognised by its checksum and not archived twice.
"""

from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from glacies import __version__
from glacies.cities import CityConfig
from glacies.provenance import (
    AcquisitionMethod,
    DatasetManifest,
    combined_checksum,
    file_entries,
    utc_now,
)

MANIFEST_NAME = "manifest.json"
DATA_DIR_NAME = "data"

# Snapshot names become directory names, so keep them to a portable, traversal-free charset.
_SNAPSHOT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

# On Windows, antivirus or the search indexer can hold a freshly moved large file open for a
# few seconds, making the final directory rename fail with "Access is denied".
_RENAME_ATTEMPTS = 10
_RENAME_DELAY_SECONDS = 1.0


class ArchiveError(Exception):
    """The archive operation cannot be performed."""


class SnapshotConflictError(ArchiveError):
    """A snapshot with this name exists with different content."""


@dataclass(frozen=True)
class RegisterResult:
    status: Literal["archived", "already_archived"]
    snapshot_dir: Path
    manifest: DatasetManifest


@dataclass(frozen=True)
class VerifyIssue:
    snapshot_dir: Path
    problem: str


def dataset_dir(raw_dir: Path, city_id: str, dataset: str) -> Path:
    return raw_dir / city_id / dataset


def read_manifest(snapshot_dir: Path) -> DatasetManifest:
    text = (snapshot_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    return DatasetManifest.model_validate_json(text)


def _snapshot_dirs(directory: Path) -> list[Path]:
    # Dot-prefixed entries are staging/incoming areas, not snapshots.
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_dir() and not p.name.startswith("."))


def list_snapshots(raw_dir: Path, city_id: str, dataset: str) -> list[DatasetManifest]:
    """Manifests of all archived snapshots of a dataset, sorted by snapshot name."""
    return [
        read_manifest(p)
        for p in _snapshot_dirs(dataset_dir(raw_dir, city_id, dataset))
        if (p / MANIFEST_NAME).is_file()
    ]


def register(
    *,
    raw_dir: Path,
    city: CityConfig,
    dataset: str,
    source_path: Path,
    snapshot: str,
    move: bool = True,
    acquired_via: AcquisitionMethod = AcquisitionMethod.MANUAL,
    version: str | None = None,
) -> RegisterResult:
    """Archive a local file or directory as a new snapshot of ``dataset``.

    ``move=True`` renames the source into the archive (instant on the same drive); otherwise it
    is copied and the copy re-verified. If identical content is already archived, nothing is
    touched and the existing snapshot is returned.
    """
    source = city.source(dataset)
    if not _SNAPSHOT_RE.fullmatch(snapshot):
        raise ArchiveError(
            f"invalid snapshot name {snapshot!r}: use letters, digits, '.', '_' or '-'"
        )
    if not source_path.exists():
        raise ArchiveError(f"source path does not exist: {source_path}")
    archive_root = dataset_dir(raw_dir, city.city.id, dataset).resolve()
    if source_path.resolve().is_relative_to(archive_root):
        raise ArchiveError(f"source path is already inside the archive: {source_path}")

    entries = file_entries(source_path)
    if not entries:
        raise ArchiveError(f"source path contains no files: {source_path}")
    checksum = combined_checksum(entries)

    for existing in list_snapshots(raw_dir, city.city.id, dataset):
        if existing.checksum_sha256 == checksum:
            return RegisterResult(
                status="already_archived",
                snapshot_dir=dataset_dir(raw_dir, city.city.id, dataset) / existing.snapshot,
                manifest=existing,
            )

    target = dataset_dir(raw_dir, city.city.id, dataset) / snapshot
    if target.exists():
        raise SnapshotConflictError(
            f"snapshot {snapshot!r} of {dataset!r} already exists with different content; "
            "choose a new snapshot name"
        )

    staging = target.with_name(f".{snapshot}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    data_dir = staging / DATA_DIR_NAME
    try:
        _transfer(source_path, data_dir, move=move)
        if not move and combined_checksum(file_entries(data_dir)) != checksum:
            raise ArchiveError(f"copy of {source_path} does not match the source checksum")
        manifest = DatasetManifest(
            dataset=dataset,
            city=city.city.id,
            snapshot=snapshot,
            source=source.source,
            source_url=source.url,
            license=source.license,
            version=version,
            nature=source.nature,
            acquired_via=acquired_via,
            archived_at=utc_now(),
            files=entries,
            checksum_sha256=checksum,
            processor_version=__version__,
        )
        (staging / MANIFEST_NAME).write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    except BaseException:
        if not move:
            shutil.rmtree(staging, ignore_errors=True)
        # After a failed move the files may already sit in staging; leave them for inspection.
        raise
    _rename_with_retry(staging, target)
    return RegisterResult(status="archived", snapshot_dir=target, manifest=manifest)


def _rename_with_retry(source: Path, target: Path) -> None:
    for attempt in range(1, _RENAME_ATTEMPTS + 1):
        try:
            source.rename(target)
            return
        except PermissionError as exc:
            if attempt == _RENAME_ATTEMPTS:
                raise ArchiveError(
                    f"could not rename {source} to {target} (file locked, e.g. by antivirus); "
                    "the data and manifest are complete in the staging directory, "
                    "rename it by hand once the lock is released"
                ) from exc
            time.sleep(_RENAME_DELAY_SECONDS)


def _transfer(source: Path, data_dir: Path, *, move: bool) -> None:
    if source.is_file():
        data_dir.mkdir()
        destination = data_dir / source.name
        if move:
            shutil.move(source, destination)
        else:
            shutil.copy2(source, destination)
    elif move:
        shutil.move(source, data_dir)
    else:
        shutil.copytree(source, data_dir)


def verify(raw_dir: Path, city_id: str) -> list[VerifyIssue]:
    """Re-hash every archived snapshot of a city and report anything that changed."""
    issues: list[VerifyIssue] = []
    for dataset in _snapshot_dirs(raw_dir / city_id):
        for snapshot_dir in _snapshot_dirs(dataset):
            if not (snapshot_dir / MANIFEST_NAME).is_file():
                issues.append(VerifyIssue(snapshot_dir, f"missing {MANIFEST_NAME}"))
                continue
            expected = {f.path: f.sha256 for f in read_manifest(snapshot_dir).files}
            actual = {f.path: f.sha256 for f in file_entries(snapshot_dir / DATA_DIR_NAME)}
            issues.extend(
                VerifyIssue(snapshot_dir, f"missing file: {path}")
                for path in sorted(expected.keys() - actual.keys())
            )
            issues.extend(
                VerifyIssue(snapshot_dir, f"unexpected file: {path}")
                for path in sorted(actual.keys() - expected.keys())
            )
            issues.extend(
                VerifyIssue(snapshot_dir, f"checksum mismatch: {path}")
                for path in sorted(expected.keys() & actual.keys())
                if expected[path] != actual[path]
            )
    return issues
