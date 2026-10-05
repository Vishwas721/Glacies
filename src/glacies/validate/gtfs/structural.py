"""Structural GTFS checks: files, fields, keys, references, orphans and duplicates."""

from __future__ import annotations

import polars as pl

from glacies.validate.gtfs.common import Collector, haversine_m, line_numbers, to_float
from glacies.validate.gtfs.loader import Feed
from glacies.validate.gtfs.report import Severity, Thresholds

ERR, WARN, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO

REQUIRED_FILES = ("agency", "stops", "routes", "trips", "stop_times")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "agency": ("agency_name", "agency_url", "agency_timezone"),
    "stops": ("stop_id",),
    "routes": ("route_id", "route_type"),
    "trips": ("route_id", "service_id", "trip_id"),
    "stop_times": ("trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"),
    "calendar": ("service_id", *WEEKDAYS, "start_date", "end_date"),
    "calendar_dates": ("service_id", "date", "exception_type"),
    "shapes": ("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"),
    "frequencies": ("trip_id", "start_time", "end_time", "headway_secs"),
}

# Columns that must be present *and* non-empty on every row (times may be blank mid-trip).
NON_NULL_COLUMNS: dict[str, tuple[str, ...]] = {
    **REQUIRED_COLUMNS,
    "stop_times": ("trip_id", "stop_id", "stop_sequence"),
}

PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "stops": ("stop_id",),
    "routes": ("route_id",),
    "trips": ("trip_id",),
    "calendar": ("service_id",),
    "calendar_dates": ("service_id", "date"),
    "stop_times": ("trip_id", "stop_sequence"),
    "shapes": ("shape_id", "shape_pt_sequence"),
}

# Stop location types that are boarding points: 0 = stop/platform (blank means 0).
_IS_BOARDING_POINT = pl.col("location_type").is_null() | (pl.col("location_type") == "0")


def check_structure(feed: Feed, out: Collector, thresholds: Thresholds) -> None:
    _files(feed, out)
    _columns(feed, out)
    _primary_keys(feed, out)
    _references(feed, out)
    _orphans(feed, out)
    _near_duplicate_stops(feed, out, thresholds.near_duplicate_stop_m)


def _files(feed: Feed, out: Collector) -> None:
    for name, message in sorted(feed.unreadable.items()):
        out.add("unreadable_file", ERR, f"{name}.txt", f"could not be parsed: {message}", count=1)
    missing = [f"{name}.txt" for name in REQUIRED_FILES if not feed.has(name)]
    out.add("missing_required_file", ERR, None, "required file is missing", examples=missing)
    if not (feed.has("calendar") or feed.has("calendar_dates")):
        out.add(
            "missing_calendar",
            ERR,
            None,
            "neither calendar.txt nor calendar_dates.txt is present",
            count=1,
        )


def _columns(feed: Feed, out: Collector) -> None:
    for name, columns in REQUIRED_COLUMNS.items():
        if not feed.has(name):
            continue
        frame = feed[name]
        missing = [c for c in columns if c not in frame.columns]
        out.add(
            "missing_required_column",
            ERR,
            f"{name}.txt",
            "required column is missing",
            examples=missing,
        )
        for column in NON_NULL_COLUMNS[name]:
            if column in frame.columns:
                out.add(
                    "missing_value",
                    ERR,
                    f"{name}.txt",
                    f"`{column}` is empty",
                    examples=line_numbers(frame, pl.col(column).is_null()),
                )
    if feed.has("routes"):
        routes = feed["routes"]
        names = [c for c in ("route_short_name", "route_long_name") if c in routes.columns]
        if not names:
            out.add(
                "missing_route_name",
                ERR,
                "routes.txt",
                "neither route_short_name nor route_long_name column exists",
                count=1,
            )
        else:
            unnamed = pl.all_horizontal(pl.col(c).is_null() for c in names)
            out.add(
                "missing_route_name",
                ERR,
                "routes.txt",
                "route has neither a short nor a long name",
                examples=routes.filter(unnamed)["route_id"]
                if "route_id" in routes.columns
                else line_numbers(routes, unnamed),
            )


def _primary_keys(feed: Feed, out: Collector) -> None:
    for name, keys in PRIMARY_KEYS.items():
        if not feed.has_columns(name, *keys):
            continue
        frame = feed[name].filter(pl.all_horizontal(pl.col(k).is_not_null() for k in keys))
        duplicated = frame.filter(pl.struct(keys).is_duplicated())
        label = pl.concat_str([pl.col(k) for k in keys], separator=":")
        out.add(
            "duplicate_key",
            ERR,
            f"{name}.txt",
            f"duplicate ({', '.join(keys)})",
            examples=duplicated.select(label).to_series(),
        )


def _missing_refs(
    feed: Feed,
    out: Collector,
    rule: str,
    child: str,
    column: str,
    parent_ids: pl.Series,
    message: str,
    severity: Severity = ERR,
) -> None:
    if not feed.has_columns(child, column):
        return
    values = feed[child][column].drop_nulls()
    missing = values.filter(~values.is_in(parent_ids.implode()))
    out.add(rule, severity, f"{child}.txt", message, examples=missing)


def _service_ids(feed: Feed) -> pl.Series:
    parts = [
        feed[name]["service_id"]
        for name in ("calendar", "calendar_dates")
        if feed.has_columns(name, "service_id")
    ]
    return pl.concat(parts).drop_nulls().unique() if parts else pl.Series([], dtype=pl.String)


def _references(feed: Feed, out: Collector) -> None:
    if feed.has_columns("routes", "route_id"):
        _missing_refs(
            feed,
            out,
            "unknown_route",
            "trips",
            "route_id",
            feed["routes"]["route_id"],
            "trip references a route_id not in routes.txt",
        )
    if feed.has("calendar") or feed.has("calendar_dates"):
        _missing_refs(
            feed,
            out,
            "unknown_service",
            "trips",
            "service_id",
            _service_ids(feed),
            "trip references a service_id not in calendar.txt or calendar_dates.txt",
        )
    if feed.has_columns("trips", "trip_id"):
        trip_ids = feed["trips"]["trip_id"]
        _missing_refs(
            feed,
            out,
            "unknown_trip",
            "stop_times",
            "trip_id",
            trip_ids,
            "stop time references a trip_id not in trips.txt",
        )
        _missing_refs(
            feed,
            out,
            "unknown_trip",
            "frequencies",
            "trip_id",
            trip_ids,
            "frequency references a trip_id not in trips.txt",
        )
    if feed.has_columns("stops", "stop_id"):
        stop_ids = feed["stops"]["stop_id"]
        _missing_refs(
            feed,
            out,
            "unknown_stop",
            "stop_times",
            "stop_id",
            stop_ids,
            "stop time references a stop_id not in stops.txt",
        )
        _missing_refs(
            feed,
            out,
            "unknown_parent_station",
            "stops",
            "parent_station",
            stop_ids,
            "parent_station is not a stop_id in stops.txt",
        )
    if feed.has_columns("trips", "shape_id"):
        shape_ids = (
            feed["shapes"]["shape_id"]
            if feed.has_columns("shapes", "shape_id")
            else pl.Series([], dtype=pl.String)
        )
        _missing_refs(
            feed,
            out,
            "unknown_shape",
            "trips",
            "shape_id",
            shape_ids,
            "trip references a shape_id not in shapes.txt",
        )
    if feed.has_columns("agency", "agency_id") and feed.has_columns("routes", "agency_id"):
        _missing_refs(
            feed,
            out,
            "unknown_agency",
            "routes",
            "agency_id",
            feed["agency"]["agency_id"],
            "route references an agency_id not in agency.txt",
        )


def _orphans(feed: Feed, out: Collector) -> None:
    if feed.has_columns("stops", "stop_id") and feed.has_columns("stop_times", "stop_id"):
        stops = feed["stops"]
        boarding = stops.filter(_IS_BOARDING_POINT) if "location_type" in stops.columns else stops
        served = feed["stop_times"]["stop_id"].unique()
        unused = boarding.filter(~pl.col("stop_id").is_in(served.implode()))["stop_id"]
        out.add("unused_stop", WARN, "stops.txt", "stop is not served by any trip", examples=unused)

    if feed.has_columns("routes", "route_id") and feed.has_columns("trips", "route_id"):
        used = feed["trips"]["route_id"].unique()
        routes = feed["routes"]
        out.add(
            "route_without_trips",
            WARN,
            "routes.txt",
            "route has no trips",
            examples=routes.filter(~pl.col("route_id").is_in(used.implode()))["route_id"],
        )

    if feed.has_columns("trips", "trip_id") and feed.has_columns("stop_times", "trip_id"):
        sizes = feed["stop_times"].group_by("trip_id").len()
        trips = feed["trips"].join(sizes, on="trip_id", how="left")
        out.add(
            "trip_without_stop_times",
            WARN,
            "trips.txt",
            "trip has no stop times",
            examples=trips.filter(pl.col("len").is_null())["trip_id"],
        )
        out.add(
            "trip_with_one_stop",
            WARN,
            "trips.txt",
            "trip visits only one stop",
            examples=trips.filter(pl.col("len") == 1)["trip_id"],
        )

    if feed.has_columns("shapes", "shape_id"):
        used_shapes = (
            feed["trips"]["shape_id"].drop_nulls().unique()
            if feed.has_columns("trips", "shape_id")
            else pl.Series([], dtype=pl.String)
        )
        shape_ids = feed["shapes"]["shape_id"].drop_nulls().unique()
        out.add(
            "unused_shape",
            INFO,
            "shapes.txt",
            "shape is not used by any trip",
            examples=shape_ids.filter(~shape_ids.is_in(used_shapes.implode())),
        )


def _near_duplicate_stops(feed: Feed, out: Collector, max_distance_m: float) -> None:
    if not feed.has_columns("stops", "stop_id", "stop_name", "stop_lat", "stop_lon"):
        return
    stops = feed["stops"]
    if "location_type" in stops.columns:
        stops = stops.filter(_IS_BOARDING_POINT)
    parent = pl.col("parent_station") if "parent_station" in stops.columns else pl.lit(None)
    points = stops.select(
        "stop_id",
        pl.col("stop_name").str.to_lowercase().alias("name_key"),
        to_float("stop_lat").alias("lat"),
        to_float("stop_lon").alias("lon"),
        parent.cast(pl.String).alias("parent"),
    ).drop_nulls(["stop_id", "name_key", "lat", "lon"])
    # Platforms of one station legitimately share a name and position.
    same_station = pl.col("parent").is_not_null() & (pl.col("parent") == pl.col("parent_b"))
    pairs = (
        points.join(points, on="name_key", suffix="_b")
        .filter(pl.col("stop_id") < pl.col("stop_id_b"))
        .filter(~same_station.fill_null(False))
        .filter(
            haversine_m(pl.col("lat"), pl.col("lon"), pl.col("lat_b"), pl.col("lon_b"))
            < max_distance_m
        )
    )
    out.add(
        "near_duplicate_stops",
        WARN,
        "stops.txt",
        f"stops with the same name less than {max_distance_m:g} m apart",
        examples=pairs.select(pl.concat_str(["stop_id", "stop_id_b"], separator="~")).to_series(),
    )
