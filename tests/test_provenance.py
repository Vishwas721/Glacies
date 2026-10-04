import hashlib
from pathlib import Path

from glacies.provenance import (
    AcquisitionMethod,
    DataNature,
    DatasetManifest,
    FileEntry,
    combined_checksum,
    file_entries,
    sha256_file,
    utc_now,
)


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    payload = b"stop_id,stop_name\n1,Majestic\n" * 1000
    path = tmp_path / "stops.txt"
    path.write_bytes(payload)

    assert sha256_file(path) == hashlib.sha256(payload).hexdigest()


def test_file_entries_are_sorted_relative_posix_paths(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_bytes(b"bb")
    (tmp_path / "a.txt").write_bytes(b"a")

    entries = file_entries(tmp_path)

    assert [(e.path, e.bytes) for e in entries] == [("a.txt", 1), ("sub/b.txt", 2)]


def test_file_entries_of_single_file_uses_its_name(tmp_path: Path) -> None:
    path = tmp_path / "pop.tif"
    path.write_bytes(b"raster")

    assert [e.path for e in file_entries(path)] == ["pop.tif"]


def test_combined_checksum_ignores_order_but_not_content_or_names() -> None:
    a = FileEntry(path="a.txt", sha256="1" * 64, bytes=1)
    b = FileEntry(path="b.txt", sha256="2" * 64, bytes=1)
    renamed = FileEntry(path="c.txt", sha256="2" * 64, bytes=1)
    changed = FileEntry(path="b.txt", sha256="3" * 64, bytes=1)

    assert combined_checksum([a, b]) == combined_checksum([b, a])
    assert combined_checksum([a, b]) != combined_checksum([a, renamed])
    assert combined_checksum([a, b]) != combined_checksum([a, changed])


def test_manifest_round_trips_through_json() -> None:
    files = [FileEntry(path="stops.txt", sha256="0" * 64, bytes=10)]
    manifest = DatasetManifest(
        dataset="bmtc_gtfs",
        city="bengaluru",
        snapshot="20260907",
        source="Vonter/bmtc-gtfs",
        source_url="https://github.com/Vonter/bmtc-gtfs",
        license="ODbL-1.0",
        nature=DataNature.OBSERVED,
        acquired_via=AcquisitionMethod.MANUAL,
        archived_at=utc_now(),
        files=files,
        checksum_sha256=combined_checksum(files),
        processor_version="0.1.0",
    )

    assert DatasetManifest.model_validate_json(manifest.model_dump_json()) == manifest
