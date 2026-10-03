"""Dataset provenance records (PRD §15).

Every dataset that enters the pipeline gets a manifest so that any simulation can state
exactly which inputs it was built from.
"""

from __future__ import annotations

import hashlib
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


class DatasetManifest(BaseModel):
    """Provenance of one downloaded or derived dataset."""

    dataset: str = Field(description="Stable dataset identifier, e.g. 'bmtc_gtfs'.")
    source: str = Field(description="Human-readable origin, e.g. 'Vonter/bmtc-gtfs'.")
    source_url: str
    license: str
    version: str | None = Field(default=None, description="Upstream version or commit.")
    downloaded_at: AwareDatetime
    checksum_sha256: str
    processor_version: str
    nature: DataNature = DataNature.OBSERVED


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, streaming so large rasters fit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)
