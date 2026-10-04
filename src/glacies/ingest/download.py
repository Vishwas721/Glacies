"""Download a source's ``download_url`` and archive it as a snapshot."""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from glacies.cities import CityConfig
from glacies.ingest.archive import ArchiveError, RegisterResult, register
from glacies.provenance import AcquisitionMethod

_ALLOWED_SCHEMES = {"https", "http", "file"}
_CHUNK_SIZE = 1 << 20


def fetch(
    *,
    raw_dir: Path,
    city: CityConfig,
    dataset: str,
    snapshot: str,
    timeout: float = 120,
) -> RegisterResult:
    """Stream the dataset's ``download_url`` to disk, then archive it via ``register``."""
    url = city.source(dataset).download_url
    if not url:
        raise ArchiveError(
            f"{dataset!r} has no download_url in city.toml; download it manually and use "
            "`glacies ingest register`"
        )
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ArchiveError(f"unsupported URL scheme {parsed.scheme!r} in {url}")

    # Outside the dataset directory, so register() does not see it as already archived.
    incoming = raw_dir / city.city.id / ".incoming" / dataset
    incoming.mkdir(parents=True, exist_ok=True)
    download = incoming / (unquote(PurePosixPath(parsed.path).name) or "download")
    try:
        with (
            urllib.request.urlopen(url, timeout=timeout) as response,
            download.open("wb") as handle,
        ):
            shutil.copyfileobj(response, handle, _CHUNK_SIZE)
        return register(
            raw_dir=raw_dir,
            city=city,
            dataset=dataset,
            source_path=download,
            snapshot=snapshot,
            move=True,
            acquired_via=AcquisitionMethod.DOWNLOAD,
        )
    finally:
        download.unlink(missing_ok=True)
        if not any(incoming.iterdir()):
            incoming.rmdir()
