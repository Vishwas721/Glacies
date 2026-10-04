"""Dataset provenance records (PRD §15).

Every dataset that enters the pipeline gets a manifest so that any simulation can state
exactly which inputs it was built from.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, Field

_CHUNK_SIZE = 1 << 20


class DataNature(StrEnum):
    """How a quantity was obtained (PRD §56). Shown wherever results are presented."""

    OBSERVED = "observed"
    ESTIMATED = "estimated"
    SIMULATED = "simulated"
    ASSUMED = "assumed"


class AcquisitionMethod(StrEnum):
    """How the raw files reached the archive."""

    DOWNLOAD = "download"  # fetched by `glacies ingest fetch`
    MANUAL = "manual"  # downloaded by hand, then `glacies ingest register`ed


class FileEntry(BaseModel):
    path: str = Field(description="POSIX path relative to the snapshot's data directory.")
    sha256: str
    bytes: int


class DatasetManifest(BaseModel):
    """Provenance of one archived snapshot of a dataset."""

    dataset: str = Field(description="Stable dataset identifier, e.g. 'bmtc_gtfs'.")
    city: str
    snapshot: str = Field(description="Archive folder name, e.g. the upstream feed version.")
    source: str = Field(description="Human-readable origin, e.g. 'Vonter/bmtc-gtfs'.")
    source_url: str
    license: str
    version: str | None = Field(default=None, description="Upstream version or commit.")
    nature: DataNature
    acquired_via: AcquisitionMethod
    archived_at: AwareDatetime
    files: list[FileEntry]
    checksum_sha256: str = Field(description="combined_checksum() over `files`.")
    processor_version: str


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, streaming so large rasters fit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def file_entries(root: Path) -> list[FileEntry]:
    """Hash every file under ``root`` (or ``root`` itself if it is a file), sorted by path."""
    if root.is_file():
        paths = [(root.name, root)]
    else:
        paths = [(p.relative_to(root).as_posix(), p) for p in root.rglob("*") if p.is_file()]
    return [
        FileEntry(path=rel, sha256=sha256_file(p), bytes=p.stat().st_size)
        for rel, p in sorted(paths)
    ]


def combined_checksum(entries: Iterable[FileEntry]) -> str:
    """Checksum of a file set that depends only on relative paths and contents."""
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda e: e.path):
        digest.update(f"{entry.path}\t{entry.sha256}\n".encode())
    return digest.hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)
