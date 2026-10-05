"""Semantic GTFS checks: times, coordinates, calendars, frequencies, shapes, speeds."""

from __future__ import annotations

import polars as pl

from glacies.validate.gtfs.common import (
    Collector,
    gtfs_seconds,
    haversine_m,
    line_numbers,
    to_float,
    to_int,
)
from glacies.validate.gtfs.loader import Feed
from glacies.validate.gtfs.report import ServiceRange, Severity, Thresholds
from glacies.validate.gtfs.structural import WEEKDAYS

ERR, WARN, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO

_TRIP_STOP = pl.concat_str(["trip_id", "stop_sequence"], separator=":")


def check_semantics(
    feed: Feed,
    out: Collector,
    thresholds: Thresholds,
    bbox: tuple[float, float, float, float],
) -> ServiceRange | None:
    _coordinates(feed, out, bbox)
    _stop_times(feed, out, thresholds)
    _frequencies(feed, out)
    _shapes(feed, out)
    _duplicate_trips(feed, out)
    return _calendars(feed, out)


def _coordinates(feed: Feed, out: Collector, bbox: tuple[float, float, float, float]) -> None:
    if not feed.has_columns("stops", "stop_id", "stop_lat", "stop_lon"):
        return
    stops = feed["stops"].with_columns(
        to_float("stop_lat").alias("_lat"), to_float("stop_lon").alias("_lon")
    )
    # Generic nodes (3) and boarding areas (4) may omit coordinates; everything else needs them.
    needs_coords = (
        pl.col("location_type").is_null() | pl.col("location_type").is_in(["0", "1", "2"])
        if "location_type" in stops.columns
        else pl.lit(True)
    )
    missing = needs_coords & (pl.col("stop_lat").is_null() | pl.col("stop_lon").is_null())
    out.add(
        "missing_coordinate",
        ERR,
        "stops.txt",
        "stop has no latitude/longitude",
        examples=stops.filter(missing)["stop_id"],
    )
    unparseable = (pl.col("stop_lat").is_not_null() & pl.col("_lat").is_null()) | (
        pl.col("stop_lon").is_not_null() & pl.col("_lon").is_null()
    )
    out.add(
        "invalid_coordinate",
        ERR,
        "stops.txt",
        "latitude/longitude is not a number",
        examples=stops.filter(unparseable)["stop_id"],
    )
    located = stops.filter(pl.col("_lat").is_not_null() & pl.col("_lon").is_not_null())
    out_of_range = (pl.col("_lat").abs() > 90) | (pl.col("_lon").abs() > 180)
    out.add(
        "coordinate_out_of_range",
        ERR,
        "stops.txt",
        "latitude/longitude outside valid range",
        examples=located.filter(out_of_range)["stop_id"],
    )
    zero = (pl.col("_lat") == 0) & (pl.col("_lon") == 0)
    out.add(
        "zero_coordinate",
        ERR,
        "stops.txt",
        "stop is at (0, 0)",
        examples=located.filter(zero)["stop_id"],
    )
    min_lon, min_lat, max_lon, max_lat = bbox
    outside = ~(
        pl.col("_lon").is_between(min_lon, max_lon) & pl.col("_lat").is_between(min_lat, max_lat)
    )
    out.add(
        "outside_bbox",
        WARN,
        "stops.txt",
        "stop lies outside the city bounding box",
        examples=located.filter(outside & ~zero & ~out_of_range)["stop_id"],
    )


def _stop_times(feed: Feed, out: Collector, thresholds: Thresholds) -> None:
    required = ("trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time")
    if not feed.has_columns("stop_times", *required):
        return
    st = feed["stop_times"].with_columns(
        gtfs_seconds("arrival_time").alias("_arr"),
        gtfs_seconds("departure_time").alias("_dep"),
        to_int("stop_sequence").alias("_seq"),
    )

    for column, parsed in (("arrival_time", "_arr"), ("departure_time", "_dep")):
        bad = pl.col(column).is_not_null() & pl.col(parsed).is_null()
        out.add(
            "invalid_time",
            ERR,
            "stop_times.txt",
            f"`{column}` is not H:MM:SS",
            examples=st.filter(bad).select(_TRIP_STOP).to_series(),
        )
    out.add(
        "invalid_stop_sequence",
        ERR,
        "stop_times.txt",
        "stop_sequence is not an integer",
        examples=line_numbers(st, pl.col("stop_sequence").is_not_null() & pl.col("_seq").is_null()),
    )
    out.add(
        "time_beyond_48h",
        WARN,
        "stop_times.txt",
        "time is 48:00:00 or later",
        examples=st.filter((pl.col("_arr") >= 48 * 3600) | (pl.col("_dep") >= 48 * 3600))
        .select(_TRIP_STOP)
        .to_series(),
    )
    out.add(
        "arrival_after_departure",
        ERR,
        "stop_times.txt",
        "arrival_time is later than departure_time at the same stop",
        examples=st.filter(pl.col("_arr") > pl.col("_dep")).select(_TRIP_STOP).to_series(),
    )

    ordered = (
        st.filter(pl.col("_seq").is_not_null())
        .sort("trip_id", "_seq")
        .with_columns(
            pl.int_range(pl.len()).over("trip_id").alias("_pos"),
            pl.len().over("trip_id").alias("_n"),
            pl.coalesce("_arr", "_dep").alias("_in"),
            pl.coalesce("_dep", "_arr").alias("_out"),
        )
    )
    untimed = pl.col("_in").is_null()
    endpoint = (pl.col("_pos") == 0) | (pl.col("_pos") == pl.col("_n") - 1)
    out.add(
        "missing_endpoint_time",
        ERR,
        "stop_times.txt",
        "first or last stop of a trip has no times",
        examples=ordered.filter(untimed & endpoint).select(_TRIP_STOP).to_series(),
    )
    out.add(
        "untimed_intermediate_stops",
        INFO,
        "stop_times.txt",
        "intermediate stops without times (will be interpolated)",
        examples=ordered.filter(untimed & ~endpoint).select(_TRIP_STOP).to_series(),
    )

    # Compare each timed stop with the previous timed stop of the same trip.
    timed = ordered.filter(~untimed).with_columns(
        pl.col("_out").shift(1).over("trip_id").alias("_prev_out"),
        pl.col("stop_id").shift(1).over("trip_id").alias("_prev_stop"),
    )
    out.add(
        "decreasing_time",
        ERR,
        "stop_times.txt",
        "time goes backwards along the trip",
        examples=timed.filter(pl.col("_in") < pl.col("_prev_out")).select(_TRIP_STOP).to_series(),
    )

    after_midnight = st.filter(pl.col("_dep") >= 24 * 3600)["trip_id"].unique()
    out.add(
        "after_midnight_trips",
        INFO,
        "stop_times.txt",
        "trips running past 24:00:00 (handled as same service day)",
        examples=after_midnight,
    )
    _speeds(feed, out, thresholds, timed)


def _speeds(feed: Feed, out: Collector, thresholds: Thresholds, timed: pl.DataFrame) -> None:
    if not (
        feed.has_columns("stops", "stop_id", "stop_lat", "stop_lon")
        and feed.has_columns("trips", "trip_id", "route_id")
        and feed.has_columns("routes", "route_id", "route_type")
    ):
        return
    coords = feed["stops"].select(
        "stop_id", to_float("stop_lat").alias("_lat"), to_float("stop_lon").alias("_lon")
    )
    route_types = (
        feed["trips"]
        .select("trip_id", "route_id")
        .join(feed["routes"].select("route_id", "route_type"), on="route_id", how="left")
    )
    limits = pl.DataFrame(
        {
            "route_type": list(thresholds.max_speed_kmh),
            "_max_kmh": list(thresholds.max_speed_kmh.values()),
        },
        schema={"route_type": pl.String, "_max_kmh": pl.Float64},
    )
    hops = (
        timed.filter(pl.col("_prev_out").is_not_null())
        .join(coords, on="stop_id", how="left")
        .join(
            coords.rename({"stop_id": "_prev_stop", "_lat": "_plat", "_lon": "_plon"}),
            on="_prev_stop",
            how="left",
        )
        .join(route_types.select("trip_id", "route_type"), on="trip_id", how="left")
        .join(limits, on="route_type", how="left")
        .with_columns(
            haversine_m(pl.col("_plat"), pl.col("_plon"), pl.col("_lat"), pl.col("_lon")).alias(
                "_dist"
            ),
            (pl.col("_in") - pl.col("_prev_out")).alias("_dt"),
            pl.col("_max_kmh").fill_null(thresholds.default_max_speed_kmh),
        )
        .filter(pl.col("_dist").is_not_null())
    )
    zero_time = (pl.col("_dt") == 0) & (pl.col("_dist") > thresholds.zero_time_hop_max_m)
    out.add(
        "zero_time_hop",
        WARN,
        "stop_times.txt",
        f"consecutive stops more than {thresholds.zero_time_hop_max_m:g} m apart "
        "with zero travel time",
        examples=hops.filter(zero_time).select(_TRIP_STOP).to_series(),
    )
    too_fast = (pl.col("_dt") > 0) & (pl.col("_dist") / pl.col("_dt") * 3.6 > pl.col("_max_kmh"))
    out.add(
        "implausible_speed",
        WARN,
        "stop_times.txt",
        "speed between consecutive stops exceeds the limit for the route type",
        examples=hops.filter(too_fast).select(_TRIP_STOP).to_series(),
    )


def _calendars(feed: Feed, out: Collector) -> ServiceRange | None:
    dates: list[pl.Series] = []
    added_services = pl.Series([], dtype=pl.String)

    if feed.has_columns("calendar_dates", "service_id", "date", "exception_type"):
        cd = feed["calendar_dates"].with_columns(
            pl.col("date").str.to_date("%Y%m%d", strict=False).alias("_date")
        )
        out.add(
            "invalid_date",
            ERR,
            "calendar_dates.txt",
            "date is not a valid YYYYMMDD date",
            examples=line_numbers(cd, pl.col("date").is_not_null() & pl.col("_date").is_null()),
        )
        out.add(
            "invalid_exception_type",
            ERR,
            "calendar_dates.txt",
            "exception_type must be 1 or 2",
            examples=line_numbers(cd, ~pl.col("exception_type").is_in(["1", "2"])),
        )
        dates.append(cd["_date"])
        added_services = cd.filter(pl.col("exception_type") == "1")["service_id"]

    if feed.has_columns("calendar", "service_id", *WEEKDAYS, "start_date", "end_date"):
        cal = feed["calendar"].with_columns(
            pl.col("start_date").str.to_date("%Y%m%d", strict=False).alias("_start"),
            pl.col("end_date").str.to_date("%Y%m%d", strict=False).alias("_end"),
        )
        for column, parsed in (("start_date", "_start"), ("end_date", "_end")):
            out.add(
                "invalid_date",
                ERR,
                "calendar.txt",
                f"`{column}` is not a valid YYYYMMDD date",
                examples=cal.filter(pl.col(column).is_not_null() & pl.col(parsed).is_null())[
                    "service_id"
                ],
            )
        out.add(
            "start_after_end",
            ERR,
            "calendar.txt",
            "start_date is after end_date",
            examples=cal.filter(pl.col("_start") > pl.col("_end"))["service_id"],
        )
        bad_flag = pl.any_horizontal(~pl.col(d).is_in(["0", "1"]) for d in WEEKDAYS)
        out.add(
            "invalid_weekday_flag",
            ERR,
            "calendar.txt",
            "weekday columns must be 0 or 1",
            examples=cal.filter(bad_flag)["service_id"],
        )
        no_days = pl.all_horizontal(pl.col(d) == "0" for d in WEEKDAYS)
        never = cal.filter(no_days & ~pl.col("service_id").is_in(added_services.implode()))
        out.add(
            "service_never_runs",
            WARN,
            "calendar.txt",
            "service has no weekdays and no added dates",
            examples=never["service_id"],
        )
        dates += [cal["_start"], cal["_end"]]

    all_dates = pl.concat(dates).drop_nulls() if dates else pl.Series([], dtype=pl.Date)
    if all_dates.is_empty():
        return None
    first, last = all_dates.min(), all_dates.max()
    return ServiceRange(start_date=str(first), end_date=str(last))


def _frequencies(feed: Feed, out: Collector) -> None:
    if not feed.has_columns("frequencies", "trip_id", "start_time", "end_time", "headway_secs"):
        return
    fr = feed["frequencies"].with_columns(
        gtfs_seconds("start_time").alias("_start"),
        gtfs_seconds("end_time").alias("_end"),
        to_int("headway_secs").alias("_headway"),
    )
    out.add(
        "invalid_frequency",
        ERR,
        "frequencies.txt",
        "start/end time is not H:MM:SS, start is not before end, or headway is not positive",
        examples=fr.filter(
            pl.col("_start").is_null()
            | pl.col("_end").is_null()
            | (pl.col("_start") >= pl.col("_end"))
            | pl.col("_headway").is_null()
            | (pl.col("_headway") <= 0)
        )["trip_id"],
    )


def _shapes(feed: Feed, out: Collector) -> None:
    required = ("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence")
    if not feed.has_columns("shapes", *required):
        return
    shapes = feed["shapes"].with_columns(
        to_float("shape_pt_lat").alias("_lat"),
        to_float("shape_pt_lon").alias("_lon"),
        to_int("shape_pt_sequence").alias("_seq"),
    )
    invalid = (
        pl.col("_lat").is_null()
        | pl.col("_lon").is_null()
        | pl.col("_seq").is_null()
        | (pl.col("_lat").abs() > 90)
        | (pl.col("_lon").abs() > 180)
    )
    out.add(
        "invalid_shape_point",
        ERR,
        "shapes.txt",
        "shape point has invalid coordinates or sequence",
        examples=shapes.filter(invalid)["shape_id"],
    )
    if "shape_dist_traveled" in shapes.columns:
        ordered = (
            shapes.filter(~invalid)
            .with_columns(to_float("shape_dist_traveled").alias("_d"))
            .sort("shape_id", "_seq")
            .with_columns(pl.col("_d").shift(1).over("shape_id").alias("_prev_d"))
        )
        out.add(
            "decreasing_shape_distance",
            WARN,
            "shapes.txt",
            "shape_dist_traveled decreases along the shape",
            examples=ordered.filter(pl.col("_d") < pl.col("_prev_d"))["shape_id"],
        )


def _duplicate_trips(feed: Feed, out: Collector) -> None:
    if not (
        feed.has_columns("trips", "trip_id", "route_id", "service_id")
        and feed.has_columns(
            "stop_times", "trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"
        )
    ):
        return
    signatures = (
        feed["stop_times"]
        .with_columns(to_int("stop_sequence").alias("_seq"))
        .sort("trip_id", "_seq")
        .group_by("trip_id", maintain_order=True)
        .agg(
            pl.concat_str(
                [pl.col("stop_id"), pl.col("arrival_time"), pl.col("departure_time")],
                separator="|",
                ignore_nulls=True,
            )
            .str.join(";")
            .alias("_signature")
        )
    )
    trips = feed["trips"].join(signatures, on="trip_id", how="inner")
    group = ("route_id", "service_id", "_signature")
    # The first trip (by id) of each identical group is the original; the rest are redundant.
    keyed = trips.sort("trip_id").with_columns(pl.int_range(pl.len()).over(group).alias("_rank"))
    redundant = keyed.filter(pl.col("_rank") > 0)
    out.add(
        "duplicate_trips",
        WARN,
        "trips.txt",
        "trip repeats another trip of the same route and service (same stops and times)",
        examples=redundant["trip_id"],
    )
