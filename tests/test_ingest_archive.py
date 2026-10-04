import shutil
from pathlib import Path

import pytest

from glacies.cities import CityConfig, CityConfigError, load_city
from glacies.ingest.archive import (
    ArchiveError,
    SnapshotConflictError,
    list_snapshots,
    register,
    verify,
)
from glacies.provenance import AcquisitionMethod, DataNature

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def city() -> CityConfig:
    return load_city(FIXTURES / "cities" / "toyville" / "city.toml")


@pytest.fixture
def toy_gtfs(tmp_path: Path) -> Path:
    """A disposable copy of the toy feed, since register moves its input by default."""
    target = tmp_path / "downloads" / "toy_gtfs"
    shutil.copytree(FIXTURES / "toy_gtfs", target)
    return target


def test_register_moves_directory_into_snapshot_layout(
    tmp_path: Path, city: CityConfig, toy_gtfs: Path
) -> None:
    raw = tmp_path / "raw"

    result = register(
        raw_dir=raw, city=city, dataset="toy_gtfs", source_path=toy_gtfs, snapshot="20260907"
    )

    snapshot = raw / "toyville" / "toy_gtfs" / "20260907"
    assert result.status == "archived"
    assert result.snapshot_dir == snapshot
    assert not toy_gtfs.exists()
    assert sorted(p.name for p in (snapshot / "data").iterdir()) == [
        "agency.txt",
        "routes.txt",
        "stops.txt",
    ]
    manifest = result.manifest
    assert (snapshot / "manifest.json").read_text(encoding="utf-8").endswith("\n")
    assert manifest.dataset == "toy_gtfs"
    assert manifest.city == "toyville"
    assert manifest.license == "CC0-1.0"
    assert manifest.nature is DataNature.OBSERVED
    assert manifest.acquired_via is AcquisitionMethod.MANUAL
    assert [f.path for f in manifest.files] == ["agency.txt", "routes.txt", "stops.txt"]


def test_copy_leaves_source_in_place(tmp_path: Path, city: CityConfig, toy_gtfs: Path) -> None:
    register(
        raw_dir=tmp_path / "raw",
        city=city,
        dataset="toy_gtfs",
        source_path=toy_gtfs,
        snapshot="v1",
        move=False,
    )

    assert (toy_gtfs / "stops.txt").exists()


def test_register_single_file(tmp_path: Path, city: CityConfig) -> None:
    raster = tmp_path / "pop.tif"
    raster.write_bytes(b"not really a raster")

    result = register(
        raw_dir=tmp_path / "raw",
        city=city,
        dataset="toy_population",
        source_path=raster,
        snapshot="2021",
    )

    assert (result.snapshot_dir / "data" / "pop.tif").read_bytes() == b"not really a raster"
    assert result.manifest.nature is DataNature.ESTIMATED


def test_checksum_is_identical_for_identical_content(tmp_path: Path, city: CityConfig) -> None:
    first = register(
        raw_dir=tmp_path / "raw1",
        city=city,
        dataset="toy_gtfs",
        source_path=FIXTURES / "toy_gtfs",
        snapshot="v1",
        move=False,
    )
    second = register(
        raw_dir=tmp_path / "raw2",
        city=city,
        dataset="toy_gtfs",
        source_path=FIXTURES / "toy_gtfs",
        snapshot="v1",
        move=False,
    )

    assert first.manifest.checksum_sha256 == second.manifest.checksum_sha256


def test_registering_same_content_twice_is_a_no_op(
    tmp_path: Path, city: CityConfig, toy_gtfs: Path
) -> None:
    raw = tmp_path / "raw"
    first = register(
        raw_dir=raw, city=city, dataset="toy_gtfs", source_path=toy_gtfs, snapshot="v1", move=False
    )

    again = register(
        raw_dir=raw, city=city, dataset="toy_gtfs", source_path=toy_gtfs, snapshot="v2"
    )

    assert again.status == "already_archived"
    assert again.snapshot_dir == first.snapshot_dir
    assert toy_gtfs.exists(), "an already-archived source must not be moved or deleted"
    assert [m.snapshot for m in list_snapshots(raw, "toyville", "toy_gtfs")] == ["v1"]


def test_conflicting_content_for_existing_snapshot_is_rejected(
    tmp_path: Path, city: CityConfig, toy_gtfs: Path
) -> None:
    raw = tmp_path / "raw"
    register(
        raw_dir=raw, city=city, dataset="toy_gtfs", source_path=toy_gtfs, snapshot="v1", move=False
    )
    (toy_gtfs / "stops.txt").write_text("stop_id\nZ\n", encoding="utf-8")

    with pytest.raises(SnapshotConflictError, match="v1"):
        register(raw_dir=raw, city=city, dataset="toy_gtfs", source_path=toy_gtfs, snapshot="v1")
    assert toy_gtfs.exists()


def test_new_content_gets_its_own_snapshot(
    tmp_path: Path, city: CityConfig, toy_gtfs: Path
) -> None:
    raw = tmp_path / "raw"
    register(
        raw_dir=raw, city=city, dataset="toy_gtfs", source_path=toy_gtfs, snapshot="v1", move=False
    )
    (toy_gtfs / "stops.txt").write_text("stop_id\nZ\n", encoding="utf-8")

    register(raw_dir=raw, city=city, dataset="toy_gtfs", source_path=toy_gtfs, snapshot="v2")

    assert [m.snapshot for m in list_snapshots(raw, "toyville", "toy_gtfs")] == ["v1", "v2"]


@pytest.mark.parametrize("snapshot", ["", "../escape", "a/b", ".hidden", "with space"])
def test_rejects_unsafe_snapshot_names(
    tmp_path: Path, city: CityConfig, toy_gtfs: Path, snapshot: str
) -> None:
    with pytest.raises(ArchiveError, match="snapshot"):
        register(
            raw_dir=tmp_path / "raw",
            city=city,
            dataset="toy_gtfs",
            source_path=toy_gtfs,
            snapshot=snapshot,
        )


def test_rejects_unknown_dataset(tmp_path: Path, city: CityConfig, toy_gtfs: Path) -> None:
    with pytest.raises(CityConfigError, match="unknown dataset"):
        register(
            raw_dir=tmp_path / "raw", city=city, dataset="nope", source_path=toy_gtfs, snapshot="v1"
        )


def test_rejects_missing_and_empty_sources(tmp_path: Path, city: CityConfig) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(ArchiveError, match="does not exist"):
        register(
            raw_dir=tmp_path / "raw",
            city=city,
            dataset="toy_gtfs",
            source_path=tmp_path / "missing",
            snapshot="v1",
        )
    with pytest.raises(ArchiveError, match="no files"):
        register(
            raw_dir=tmp_path / "raw",
            city=city,
            dataset="toy_gtfs",
            source_path=empty,
            snapshot="v1",
        )


def test_rejects_source_inside_the_archive(tmp_path: Path, city: CityConfig) -> None:
    raw = tmp_path / "raw"
    result = register(
        raw_dir=raw,
        city=city,
        dataset="toy_gtfs",
        source_path=FIXTURES / "toy_gtfs",
        snapshot="v1",
        move=False,
    )

    with pytest.raises(ArchiveError, match="inside the archive"):
        register(
            raw_dir=raw,
            city=city,
            dataset="toy_gtfs",
            source_path=result.snapshot_dir / "data",
            snapshot="v2",
        )


def test_verify_passes_on_untouched_archive(
    tmp_path: Path, city: CityConfig, toy_gtfs: Path
) -> None:
    raw = tmp_path / "raw"
    register(raw_dir=raw, city=city, dataset="toy_gtfs", source_path=toy_gtfs, snapshot="v1")

    assert verify(raw, "toyville") == []


def test_verify_detects_modified_missing_and_extra_files(
    tmp_path: Path, city: CityConfig, toy_gtfs: Path
) -> None:
    raw = tmp_path / "raw"
    result = register(
        raw_dir=raw, city=city, dataset="toy_gtfs", source_path=toy_gtfs, snapshot="v1"
    )
    data = result.snapshot_dir / "data"
    (data / "stops.txt").write_text("tampered\n", encoding="utf-8")
    (data / "routes.txt").unlink()
    (data / "extra.txt").write_text("surprise\n", encoding="utf-8")

    problems = sorted(issue.problem for issue in verify(raw, "toyville"))

    assert problems == [
        "checksum mismatch: stops.txt",
        "missing file: routes.txt",
        "unexpected file: extra.txt",
    ]


def test_verify_flags_snapshot_without_manifest(tmp_path: Path) -> None:
    orphan = tmp_path / "raw" / "toyville" / "toy_gtfs" / "v1" / "data"
    orphan.mkdir(parents=True)

    issues = verify(tmp_path / "raw", "toyville")

    assert [i.problem for i in issues] == ["missing manifest.json"]
