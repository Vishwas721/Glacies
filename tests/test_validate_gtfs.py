from pathlib import Path

import pytest

from glacies.cities import CoverageReference
from glacies.validate.gtfs.report import Finding, Severity, ValidationReport
from glacies.validate.gtfs.validator import ValidationOptions, validate_feed
from tests.gtfs_edit import append, copy_toy_feed, replace

BBOX = (77.0, 12.0, 77.1, 12.1)


@pytest.fixture
def feed(tmp_path: Path) -> Path:
    return copy_toy_feed(tmp_path / "feed")


def run(feed: Path, **overrides: object) -> ValidationReport:
    options = ValidationOptions(
        dataset="toy_gtfs",
        city="toyville",
        snapshot="v1",
        input_checksum="0" * 64,
        bbox=BBOX,
        route_number_pattern=r"^\S+",
    ).model_copy(update=overrides)
    return validate_feed(feed, options)


def finding(report: ValidationReport, rule: str, file: str | None = None) -> Finding:
    matches = [f for f in report.findings if f.rule == rule and (file is None or f.file == file)]
    assert matches, f"no {rule!r} finding; got {[(f.rule, f.file) for f in report.findings]}"
    return matches[0]


def rules(report: ValidationReport) -> set[str]:
    return {f.rule for f in report.findings}


# --- clean feed ----------------------------------------------------------------------------


def test_clean_feed_has_only_the_after_midnight_info(feed: Path) -> None:
    report = run(feed)

    assert [(f.rule, f.severity, f.examples) for f in report.findings] == [
        ("after_midnight_trips", Severity.INFO, ["T4"])
    ]
    assert report.service_range is not None
    assert (report.service_range.start_date, report.service_range.end_date) == (
        "2026-01-01",
        "2026-12-31",
    )
    assert report.row_counts["stop_times"] == 10


def test_coverage_counts_route_numbers_not_variants(feed: Path) -> None:
    reference = CoverageReference(
        route_count_min=2, route_count_max=4, source="fixture", verified=False
    )

    coverage = run(feed, coverage_reference=reference).coverage

    assert coverage.route_rows == 3
    assert coverage.distinct_route_numbers == 2  # "10" and "10 EXP" are one route number
    assert coverage.routes_by_type == {"1": 1, "3": 2}
    assert (coverage.stops_served, coverage.stops_total) == (5, 5)
    assert (coverage.ratio_min, coverage.ratio_max) == (0.5, 1.0)


def test_coverage_without_reference_is_not_measured(feed: Path) -> None:
    report = run(feed)

    assert report.coverage.ratio_min is None
    assert "Coverage ratio: **not measured**" in report.to_markdown()


def test_reports_are_deterministic(feed: Path) -> None:
    append(feed, "stops.txt", "Q,Unused,12.06,77.06,,")

    first, second = run(feed), run(feed)

    assert first.to_json() == second.to_json()
    assert first.to_markdown() == second.to_markdown()


# --- structural ----------------------------------------------------------------------------


def test_missing_required_file(feed: Path) -> None:
    (feed / "routes.txt").unlink()

    assert finding(run(feed), "missing_required_file").examples == ["routes.txt"]


def test_missing_calendar(feed: Path) -> None:
    (feed / "calendar.txt").unlink()
    (feed / "calendar_dates.txt").unlink()

    assert finding(run(feed), "missing_calendar").severity is Severity.ERROR


def test_missing_required_column(feed: Path) -> None:
    (feed / "agency.txt").write_text(
        "agency_id,agency_name,agency_timezone\ntoy,Toy,UTC\n", encoding="utf-8"
    )

    assert finding(run(feed), "missing_required_column").examples == ["agency_url"]


def test_bom_in_header_is_ignored(feed: Path) -> None:
    text = (feed / "agency.txt").read_text(encoding="utf-8")
    (feed / "agency.txt").write_text("﻿" + text, encoding="utf-8")

    assert "missing_required_column" not in rules(run(feed))


def test_missing_value(feed: Path) -> None:
    replace(feed, "stop_times.txt", "T3,09:05:00,09:05:00,C,2", "T3,09:05:00,09:05:00,,2")

    result = finding(run(feed), "missing_value", "stop_times.txt")
    assert result.examples == ["line 9"]


def test_missing_route_name(feed: Path) -> None:
    replace(feed, "routes.txt", "R3,toy,M1,Central to D,1", "R3,toy,,,1")

    assert finding(run(feed), "missing_route_name").examples == ["R3"]


def test_duplicate_keys(feed: Path) -> None:
    append(feed, "stops.txt", "A,Stop A again,12.02,77.02,,")
    append(feed, "stop_times.txt", "T1,08:06:00,08:06:00,C,3")

    report = run(feed)

    assert finding(report, "duplicate_key", "stops.txt").examples == ["A"]
    assert finding(report, "duplicate_key", "stop_times.txt").examples == ["T1:3"]


@pytest.mark.parametrize(
    ("file", "old", "new", "rule", "example"),
    [
        ("trips.txt", "R2,WE,T3,,0", "R9,WE,T3,,0", "unknown_route", "R9"),
        ("trips.txt", "R2,WE,T3,,0", "R2,XX,T3,,0", "unknown_service", "XX"),
        ("trips.txt", "R2,WE,T3,,0", "R2,WE,T3,SH9,0", "unknown_shape", "SH9"),
        ("stop_times.txt", "09:05:00,C,2", "09:05:00,Z,2", "unknown_stop", "Z"),
        ("stops.txt", "Central Station Platform 1,12.0101,77.0101,0,S1",
         "Central Station Platform 1,12.0101,77.0101,0,S9", "unknown_parent_station", "S9"),
        ("routes.txt", "R3,toy,M1", "R3,nobody,M1", "unknown_agency", "nobody"),
    ],
)  # fmt: skip
def test_broken_references(
    feed: Path, file: str, old: str, new: str, rule: str, example: str
) -> None:
    replace(feed, file, old, new)

    result = finding(run(feed), rule)
    assert result.severity is Severity.ERROR
    assert result.examples == [example]


def test_unknown_trip_in_stop_times_and_frequencies(feed: Path) -> None:
    append(feed, "stop_times.txt", "T9,10:00:00,10:00:00,A,1")
    (feed / "frequencies.txt").write_text(
        "trip_id,start_time,end_time,headway_secs\nT8,06:00:00,07:00:00,600\n", encoding="utf-8"
    )

    report = run(feed)

    assert finding(report, "unknown_trip", "stop_times.txt").examples == ["T9"]
    assert finding(report, "unknown_trip", "frequencies.txt").examples == ["T8"]


def test_orphans(feed: Path) -> None:
    append(feed, "stops.txt", "Q,Lonely,12.06,77.06,,")
    append(feed, "routes.txt", "R4,toy,99,Ghost,3")
    append(feed, "trips.txt", "R1,WK,T5,,0", "R1,WK,T6,,0")
    append(feed, "stop_times.txt", "T5,10:00:00,10:00:00,A,1")
    append(feed, "shapes.txt", "SH2,12.02,77.02,1")

    report = run(feed)

    assert finding(report, "unused_stop").examples == ["Q"]
    assert finding(report, "route_without_trips").examples == ["R4"]
    assert finding(report, "trip_with_one_stop").examples == ["T5"]
    assert finding(report, "trip_without_stop_times").examples == ["T6"]
    assert finding(report, "unused_shape").severity is Severity.INFO


def test_near_duplicate_stops_ignore_platforms_of_one_station(feed: Path) -> None:
    append(
        feed,
        "stops.txt",
        "A2,stop a,12.02001,77.02001,,",  # ~1.5 m from A, same name ignoring case
        "P2,Central Station Platform 1,12.0101,77.0101,0,S1",  # sibling platform
    )
    append(feed, "stop_times.txt", "T3,09:06:00,09:06:00,A2,3", "T3,09:07:00,09:07:00,P2,4")

    assert finding(run(feed), "near_duplicate_stops").examples == ["A~A2"]


def test_unreadable_file_is_reported(feed: Path) -> None:
    (feed / "shapes.txt").write_text('shape_id,shape_pt_lat\n"SH1,12.0\n', encoding="utf-8")

    assert finding(run(feed), "unreadable_file").file == "shapes.txt"


# --- semantic ------------------------------------------------------------------------------


def test_invalid_times(feed: Path) -> None:
    replace(feed, "stop_times.txt", "T1,08:03:00,08:03:30,B,2", "T1,8:61:00,08:03:30,B,2")

    result = finding(run(feed), "invalid_time")
    assert result.examples == ["T1:2"]


def test_arrival_after_departure_and_decreasing_time(feed: Path) -> None:
    replace(feed, "stop_times.txt", "T1,08:03:00,08:03:30,B,2", "T1,08:04:00,08:03:30,B,2")
    replace(feed, "stop_times.txt", "T2,08:16:00,08:16:00,C,3", "T2,08:12:00,08:12:00,C,3")

    report = run(feed)

    assert finding(report, "arrival_after_departure").examples == ["T1:2"]
    assert finding(report, "decreasing_time").examples == ["T2:3"]


def test_times_beyond_48_hours(feed: Path) -> None:
    replace(feed, "stop_times.txt", "T4,24:05:00,24:05:00,D,2", "T4,48:05:00,48:05:00,D,2")

    assert finding(run(feed), "time_beyond_48h").examples == ["T4:2"]


def test_untimed_stops(feed: Path) -> None:
    replace(feed, "stop_times.txt", "T1,08:03:00,08:03:30,B,2", "T1,,,B,2")
    replace(feed, "stop_times.txt", "T2,08:16:00,08:16:00,C,3", "T2,,,C,3")

    report = run(feed)

    assert finding(report, "untimed_intermediate_stops").examples == ["T1:2"]
    assert finding(report, "missing_endpoint_time").examples == ["T2:3"]


def test_invalid_stop_sequence(feed: Path) -> None:
    replace(feed, "stop_times.txt", "T3,09:05:00,09:05:00,C,2", "T3,09:05:00,09:05:00,C,two")

    assert finding(run(feed), "invalid_stop_sequence").examples == ["line 9"]


def test_implausible_speed_and_zero_time_hop(feed: Path) -> None:
    # A to C is about 3.1 km.
    replace(feed, "stop_times.txt", "T3,09:05:00,09:05:00,C,2", "T3,09:00:30,09:00:30,C,2")
    replace(feed, "stop_times.txt", "T2,08:13:00,08:13:30,B,2", "T2,08:10:00,08:13:30,B,2")

    report = run(feed)

    assert finding(report, "implausible_speed").examples == ["T3:2"]
    assert finding(report, "zero_time_hop").examples == ["T2:2"]


def test_speed_limit_depends_on_route_type(feed: Path) -> None:
    # P1 to D is about 6.2 km: 4 minutes is 93 km/h, fine for metro (type 1), too fast for bus.
    replace(feed, "stop_times.txt", "T4,24:05:00,24:05:00,D,2", "T4,24:02:30,24:02:30,D,2")
    assert "implausible_speed" not in rules(run(feed))

    replace(feed, "routes.txt", "R3,toy,M1,Central to D,1", "R3,toy,M1,Central to D,3")
    assert finding(run(feed), "implausible_speed").examples == ["T4:2"]


@pytest.mark.parametrize(
    ("old", "new", "rule"),
    [
        ("D,Stop D,12.0500,77.0500", "D,Stop D,,", "missing_coordinate"),
        ("D,Stop D,12.0500,77.0500", "D,Stop D,north,77.05", "invalid_coordinate"),
        ("D,Stop D,12.0500,77.0500", "D,Stop D,95.0,77.05", "coordinate_out_of_range"),
        ("D,Stop D,12.0500,77.0500", "D,Stop D,0,0", "zero_coordinate"),
        ("D,Stop D,12.0500,77.0500", "D,Stop D,12.5,77.05", "outside_bbox"),
    ],
)
def test_coordinates(feed: Path, old: str, new: str, rule: str) -> None:
    replace(feed, "stops.txt", old, new)

    report = run(feed)

    assert finding(report, rule).examples == ["D"]
    assert len(rules(report) & {"zero_coordinate", "outside_bbox", "coordinate_out_of_range"}) <= 1


def test_calendar_problems(feed: Path) -> None:
    append(
        feed,
        "calendar.txt",
        "BAD,1,1,1,1,1,0,0,20261301,20261231",
        "REV,1,1,1,1,1,0,0,20261231,20260101",
        "FLAG,2,0,0,0,0,0,0,20260101,20261231",
        "NEVER,0,0,0,0,0,0,0,20260101,20261231",
        "ADDED,0,0,0,0,0,0,0,20260101,20261231",
    )
    append(feed, "calendar_dates.txt", "ADDED,20260105,1", "WK,20261299,2", "WK,20261226,3")

    report = run(feed)

    assert finding(report, "invalid_date", "calendar.txt").examples == ["BAD"]
    assert finding(report, "invalid_date", "calendar_dates.txt").count == 1
    assert finding(report, "start_after_end").examples == ["REV"]
    assert finding(report, "invalid_weekday_flag").examples == ["FLAG"]
    assert finding(report, "service_never_runs").examples == ["NEVER"]
    assert finding(report, "invalid_exception_type").count == 1


def test_invalid_frequencies(feed: Path) -> None:
    (feed / "frequencies.txt").write_text(
        "trip_id,start_time,end_time,headway_secs\n"
        "T1,06:00:00,07:00:00,600\n"
        "T2,07:00:00,06:00:00,600\n"
        "T3,06:00:00,07:00:00,0\n",
        encoding="utf-8",
    )

    assert finding(run(feed), "invalid_frequency").examples == ["T2", "T3"]


def test_shape_problems(feed: Path) -> None:
    (feed / "shapes.txt").write_text(
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence,shape_dist_traveled\n"
        "SH1,12.02,77.02,1,0\n"
        "SH1,12.03,77.03,2,1500\n"
        "SH1,12.04,77.04,3,1200\n"
        "SH1,abc,77.05,4,3000\n",
        encoding="utf-8",
    )

    report = run(feed)

    assert finding(report, "decreasing_shape_distance").examples == ["SH1"]
    assert finding(report, "invalid_shape_point").count == 1


def test_duplicate_trips(feed: Path) -> None:
    append(feed, "trips.txt", "R1,WK,T2b,SH1,0")
    append(
        feed,
        "stop_times.txt",
        "T2b,08:10:00,08:10:00,A,1",
        "T2b,08:13:00,08:13:30,B,2",
        "T2b,08:16:00,08:16:00,C,3",
    )

    assert finding(run(feed), "duplicate_trips").examples == ["T2b"]


def test_markdown_lists_findings_by_severity(feed: Path) -> None:
    replace(feed, "trips.txt", "R2,WE,T3,,0", "R9,WE,T3,,0")
    reference = CoverageReference(
        route_count_min=2, route_count_max=4, source="fixture", verified=False
    )

    markdown = run(feed, coverage_reference=reference).to_markdown()

    assert "**1 errors · 1 warnings · 1 info**" in markdown  # R2 is left without trips
    assert "### Errors (1)" in markdown
    assert "| `unknown_route` | trips.txt | 1 |" in markdown
    assert "Coverage ratio: 50% to 100%" in markdown
    assert "**unverified**" in markdown
