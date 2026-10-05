from datetime import date
from pathlib import Path

import polars as pl
import pytest

from glacies.model.transit.build import (
    FeedInput,
    TransitBuild,
    TransitBuildError,
    build_transit,
)
from glacies.model.transit.writer import read_table, write_transit
from glacies.validate.gtfs.report import Thresholds
from tests.gtfs_edit import append, copy_toy_feed, replace

TUESDAY = date(2026, 10, 13)
SATURDAY = date(2026, 10, 17)
BBOX = (77.0, 12.0, 77.1, 12.1)


@pytest.fixture
def feed(tmp_path: Path) -> Path:
    return copy_toy_feed(tmp_path / "feed")


def build(
    *feeds: Path,
    day: date = TUESDAY,
    bbox: tuple[float, float, float, float] = BBOX,
    exclude: str | None = None,
    drop_speed: bool = True,
) -> TransitBuild:
    inputs = [
        FeedInput(
            dataset=f"toy{i}",
            snapshot="v1",
            checksum_sha256=str(i) * 64,
            directory=path,
            route_number_pattern=r"^\S+",
            exclude_route_pattern=exclude,
        )
        for i, path in enumerate(feeds)
    ]
    return build_transit(
        inputs,
        service_date=day,
        bbox=bbox,
        thresholds=Thresholds(),
        drop_implausible_speed_trips=drop_speed,
    )


def source_trips(result: TransitBuild) -> list[str]:
    return sorted(result.tables["trips"]["source_trip_id"].to_list())


def dropped(result: TransitBuild, reason: str) -> pl.DataFrame:
    table = result.tables["dropped_trips"]
    return table.filter(pl.col("reason") == reason)


def times_of(result: TransitBuild, trip: str, piece: int = 0) -> list[tuple[str, int, int]]:
    t = result.tables
    trip_idx = t["trips"].filter((pl.col("source_trip_id") == trip) & (pl.col("piece") == piece))[
        "trip_idx"
    ]
    rows = (
        t["stop_times"]
        .filter(pl.col("trip_idx").is_in(trip_idx.implode()))
        .join(t["stops"].select("stop_idx", "source_stop_id"), on="stop_idx")
        .sort("position")
    )
    return list(rows.select("source_stop_id", "arrival", "departure").iter_rows())


# --- service day and tables -----------------------------------------------------------------


def test_tuesday_network(feed: Path) -> None:
    result = build(feed)
    t = result.tables

    assert source_trips(result) == ["T1", "T2", "T4"]  # T3 runs at weekends only
    assert t["routes"].select("source_route_id", "mode", "route_number").rows() == [
        ("R1", "bus", "10"),
        ("R3", "metro", "M1"),
    ]
    # T1 and T2 share one stop pattern; trips are ordered by first departure within it.
    trips = t["trips"].sort("trip_idx")
    assert trips.select("source_trip_id", "pattern_idx").rows() == [("T1", 0), ("T2", 0), ("T4", 1)]
    assert t["patterns"]["stop_count"].to_list() == [3, 2]
    assert t["dropped_trips"].is_empty()


def test_station_hierarchy_keeps_parents_and_drops_entrances(feed: Path) -> None:
    stops = build(feed).tables["stops"]

    assert "E1" not in stops["source_stop_id"].to_list()
    platform = stops.filter(pl.col("source_stop_id") == "P1").row(0, named=True)
    station = stops.filter(pl.col("source_stop_id") == "S1").row(0, named=True)
    assert platform["parent_stop_idx"] == station["stop_idx"]
    assert station["location_type"] == 1


def test_times_are_seconds_since_service_midnight(feed: Path) -> None:
    result = build(feed)

    assert times_of(result, "T4") == [("P1", 86_280, 86_310), ("D", 86_700, 86_700)]
    assert set(result.tables["stop_times"]["time_nature"]) == {"observed"}


def test_weekend_service(feed: Path) -> None:
    assert source_trips(build(feed, day=SATURDAY)) == ["T3"]


def test_calendar_exceptions(feed: Path) -> None:
    christmas = build(feed, day=date(2026, 12, 25))  # Friday, WK removed in calendar_dates
    assert source_trips(christmas) == []

    append(feed, "calendar_dates.txt", "WE,20261013,1")
    assert source_trips(build(feed)) == ["T1", "T2", "T3", "T4"]


def test_service_date_step_is_logged(feed: Path) -> None:
    step = build(feed).steps[0]

    assert (step.step, step.trips_before, step.trips_after) == ("service_date", 4, 3)
    assert "tuesday" in step.detail


# --- cleaning -------------------------------------------------------------------------------


def test_excluded_routes_are_logged(feed: Path) -> None:
    result = build(feed, day=SATURDAY, exclude=r"(?i)\bexp\b")

    assert source_trips(result) == []
    row = dropped(result, "excluded_route").row(0, named=True)
    assert (row["source_trip_id"], row["source_route_id"], row["route_short_name"]) == (
        "T3",
        "R2",
        "10 EXP",
    )


def test_intermediate_times_are_interpolated_by_distance(feed: Path) -> None:
    replace(feed, "stop_times.txt", "T1,08:03:00,08:03:30,B,2", "T1,,,B,2")

    result = build(feed)

    (_, a_dep, _), (_, b_arr, b_dep), _ = ((s, arr, dep) for s, arr, dep in times_of(result, "T1"))
    # A, B, C are evenly spaced, so B lands half way between 08:00:00 and 08:06:00.
    assert abs(b_arr - 28_980) <= 2
    assert b_arr == b_dep
    natures = result.tables["stop_times"].group_by("time_nature").len().sort("time_nature")
    assert natures.rows() == [("estimated", 1), ("observed", 7)]
    assert a_dep == 28_800


def test_missing_endpoint_time_drops_trip(feed: Path) -> None:
    replace(feed, "stop_times.txt", "T2,08:16:00,08:16:00,C,3", "T2,,,C,3")

    result = build(feed)

    assert "T2" not in source_trips(result)
    assert dropped(result, "missing_endpoint_time")["source_trip_id"].to_list() == ["T2"]


def test_trip_without_stop_times_is_logged(feed: Path) -> None:
    append(feed, "trips.txt", "R1,WK,T8,,0")

    assert dropped(build(feed), "no_stop_times")["source_trip_id"].to_list() == ["T8"]


def test_implausible_speed_drops_trip_with_audit_details(feed: Path) -> None:
    # A to B is about 1.55 km; 10 s is about 560 km/h.
    replace(feed, "stop_times.txt", "T2,08:13:00,08:13:30,B,2", "T2,08:10:10,08:13:30,B,2")

    result = build(feed)

    assert source_trips(result) == ["T1", "T4"]
    row = dropped(result, "implausible_speed").row(0, named=True)
    assert row["source_trip_id"] == "T2"
    assert row["dataset"] == "toy0"
    assert (row["from_stop_id"], row["to_stop_id"]) == ("A", "B")
    assert row["threshold_kmh"] == 80.0
    assert 500 < row["max_speed_kmh"] < 600


def test_speed_check_can_be_disabled(feed: Path) -> None:
    replace(feed, "stop_times.txt", "T2,08:13:00,08:13:30,B,2", "T2,08:10:10,08:13:30,B,2")

    assert "T2" in source_trips(build(feed, drop_speed=False))


def test_speed_is_checked_before_clipping(feed: Path) -> None:
    # The impossible hop B -> C lies partly outside a bbox that excludes C.
    replace(feed, "stop_times.txt", "T2,08:16:00,08:16:00,C,3", "T2,08:13:40,08:13:40,C,3")
    no_c = (77.0, 12.0, 77.035, 12.035)

    result = build(feed, bbox=no_c)

    assert "T2" not in source_trips(result)
    assert dropped(result, "implausible_speed")["source_trip_id"].to_list() == ["T2"]


def test_duplicate_trips_keep_the_first(feed: Path) -> None:
    append(feed, "trips.txt", "R1,WK,T2b,SH1,0")
    append(
        feed,
        "stop_times.txt",
        "T2b,08:10:00,08:10:00,A,1",
        "T2b,08:13:00,08:13:30,B,2",
        "T2b,08:16:00,08:16:00,C,3",
    )

    result = build(feed)

    assert "T2" in source_trips(result)
    assert dropped(result, "duplicate_trip")["source_trip_id"].to_list() == ["T2b"]


# --- study-area clip ------------------------------------------------------------------------


def test_clip_shortens_trips(feed: Path) -> None:
    no_c = (77.0, 12.0, 77.035, 12.035)

    result = build(feed, bbox=no_c)

    assert [s for s, _, _ in times_of(result, "T1")] == ["A", "B"]
    clip = next(s for s in result.steps if s.step == "study_area_clip")
    assert clip.detail.startswith("2 trips shortened")


def test_clip_splits_trips_that_leave_and_reenter(feed: Path) -> None:
    append(feed, "stops.txt", "X,Far away,12.5000,77.5000,,")
    append(feed, "trips.txt", "R1,WK,T7,,0")
    append(
        feed,
        "stop_times.txt",
        "T7,07:00:00,07:00:00,A,1",
        "T7,07:03:00,07:03:00,B,2",
        "T7,09:00:00,09:00:00,X,3",
        "T7,11:00:00,11:00:00,C,4",
        "T7,11:05:00,11:05:00,D,5",
    )

    result = build(feed)

    assert [s for s, _, _ in times_of(result, "T7", piece=1)] == ["A", "B"]
    assert [s for s, _, _ in times_of(result, "T7", piece=2)] == ["C", "D"]
    assert "X" not in result.tables["stops"]["source_stop_id"].to_list()
    clip = next(s for s in result.steps if s.step == "study_area_clip")
    assert "1 split into 2 pieces" in clip.detail


def test_trips_entirely_outside_are_dropped(feed: Path) -> None:
    elsewhere = (77.06, 12.06, 77.1, 12.1)

    result = build(feed, bbox=elsewhere)

    assert source_trips(result) == []
    assert dropped(result, "outside_study_area")["source_trip_id"].to_list() == ["T1", "T2", "T4"]


def test_frequency_based_feeds_are_rejected(feed: Path) -> None:
    (feed / "frequencies.txt").write_text(
        "trip_id,start_time,end_time,headway_secs\nT1,06:00:00,07:00:00,600\n", encoding="utf-8"
    )

    with pytest.raises(TransitBuildError, match="frequencies"):
        build(feed)


# --- merging and output ---------------------------------------------------------------------


def test_two_feeds_get_distinct_indices(tmp_path: Path) -> None:
    first = copy_toy_feed(tmp_path / "a")
    second = copy_toy_feed(tmp_path / "b")

    t = build(first, second).tables

    assert t["feeds"]["dataset"].to_list() == ["toy0", "toy1"]
    assert t["stops"].height == 12
    assert t["stops"]["stop_idx"].to_list() == list(range(12))
    assert t["trips"].group_by("feed_idx").len().sort("feed_idx")["len"].to_list() == [3, 3]
    assert t["patterns"].height == 4
    # Every stop time points at a stop of its own feed.
    joined = (
        t["stop_times"]
        .join(t["trips"].select("trip_idx", "feed_idx"), on="trip_idx")
        .join(t["stops"].select("stop_idx", pl.col("feed_idx").alias("stop_feed")), on="stop_idx")
    )
    assert (joined["feed_idx"] == joined["stop_feed"]).all()


def test_empty_day_still_writes_valid_tables(feed: Path, tmp_path: Path) -> None:
    result = build(feed, day=date(2026, 12, 25))

    manifest = write_transit(
        result, tmp_path / "out", city="toyville", service_date="2026-12-25", bbox=BBOX,
        drop_implausible_speed_trips=True, exclude_route_patterns={}, thresholds=Thresholds(),
    )  # fmt: skip

    assert manifest.row_counts["trips"] == 0
    assert read_table(tmp_path / "out", "stop_times").is_empty()


def write(result: TransitBuild, out: Path) -> str:
    manifest = write_transit(
        result, out, city="toyville", service_date="2026-10-13", bbox=BBOX,
        drop_implausible_speed_trips=True, exclude_route_patterns={"toy0": None},
        thresholds=Thresholds(),
    )  # fmt: skip
    return manifest.model_dump_json()


def test_output_is_byte_identical_across_builds(feed: Path, tmp_path: Path) -> None:
    replace(feed, "stop_times.txt", "T1,08:03:00,08:03:30,B,2", "T1,,,B,2")

    first = write(build(feed), tmp_path / "one")
    second = write(build(feed), tmp_path / "two")

    assert first == second
    for path in sorted((tmp_path / "one").iterdir()):
        assert path.read_bytes() == (tmp_path / "two" / path.name).read_bytes(), path.name


def test_writer_records_audit_trail_and_replaces_old_output(feed: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.parquet").write_bytes(b"old")
    replace(feed, "stop_times.txt", "T2,08:13:00,08:13:30,B,2", "T2,08:10:10,08:13:30,B,2")

    write(build(feed), out)

    assert not (out / "stale.parquet").exists()
    report = (out / "BUILD_REPORT.md").read_text(encoding="utf-8")
    assert "| toy0 | implausible_speed | 3 | 2 |" in report
    assert "implausible_speed 1" in report
    audit = read_table(out, "dropped_trips")
    assert audit.select("source_trip_id", "reason").rows() == [("T2", "implausible_speed")]
