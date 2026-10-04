from pathlib import Path

import pytest

from glacies.cities import CityConfig, load_city
from glacies.ingest.archive import ArchiveError
from glacies.ingest.download import fetch
from glacies.provenance import AcquisitionMethod

FIXTURES = Path(__file__).parent / "fixtures"


def _city_with_download_url(url: str) -> CityConfig:
    city = load_city(FIXTURES / "cities" / "toyville" / "city.toml")
    source = city.sources["toy_population"].model_copy(update={"download_url": url})
    return city.model_copy(update={"sources": {**city.sources, "toy_population": source}})


def test_fetch_archives_downloaded_file(tmp_path: Path) -> None:
    remote = tmp_path / "remote" / "pop v1.tif"
    remote.parent.mkdir()
    remote.write_bytes(b"raster bytes")
    city = _city_with_download_url(remote.as_uri())
    raw = tmp_path / "raw"

    result = fetch(raw_dir=raw, city=city, dataset="toy_population", snapshot="2021")

    assert result.status == "archived"
    assert (result.snapshot_dir / "data" / "pop v1.tif").read_bytes() == b"raster bytes"
    assert result.manifest.acquired_via is AcquisitionMethod.DOWNLOAD
    assert remote.exists(), "the remote file must not be touched"
    assert not (raw / "toyville" / ".incoming" / "toy_population").exists()


def test_fetch_twice_does_not_duplicate(tmp_path: Path) -> None:
    remote = tmp_path / "pop.tif"
    remote.write_bytes(b"raster bytes")
    city = _city_with_download_url(remote.as_uri())
    raw = tmp_path / "raw"

    fetch(raw_dir=raw, city=city, dataset="toy_population", snapshot="2021")
    again = fetch(raw_dir=raw, city=city, dataset="toy_population", snapshot="2021-b")

    assert again.status == "already_archived"
    assert again.manifest.snapshot == "2021"


def test_fetch_requires_download_url(tmp_path: Path) -> None:
    city = load_city(FIXTURES / "cities" / "toyville" / "city.toml")

    with pytest.raises(ArchiveError, match="register"):
        fetch(raw_dir=tmp_path / "raw", city=city, dataset="toy_gtfs", snapshot="v1")


def test_fetch_rejects_unsupported_schemes(tmp_path: Path) -> None:
    city = _city_with_download_url("ftp://example.invalid/pop.tif")

    with pytest.raises(ArchiveError, match="scheme"):
        fetch(raw_dir=tmp_path / "raw", city=city, dataset="toy_population", snapshot="v1")
