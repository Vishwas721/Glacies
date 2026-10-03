import hashlib
from pathlib import Path

from glacies.provenance import DataNature, DatasetManifest, sha256_file, utc_now


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    payload = b"stop_id,stop_name\n1,Majestic\n" * 1000
    path = tmp_path / "stops.txt"
    path.write_bytes(payload)

    assert sha256_file(path) == hashlib.sha256(payload).hexdigest()


def test_manifest_round_trips_through_json() -> None:
    manifest = DatasetManifest(
        dataset="bmtc_gtfs",
        source="Vonter/bmtc-gtfs",
        source_url="https://github.com/Vonter/bmtc-gtfs",
        license="ODbL-1.0",
        downloaded_at=utc_now(),
        checksum_sha256="0" * 64,
        processor_version="0.1.0",
    )

    restored = DatasetManifest.model_validate_json(manifest.model_dump_json())

    assert restored == manifest
    assert restored.nature is DataNature.OBSERVED
