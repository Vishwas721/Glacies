"""Validated GTFS feeds -> canonical transit tables for one service day.

Every trip that is removed is recorded in ``dropped_trips`` with its reason, and every step's
trip counts are recorded in ``steps``. Raw feeds are only read, never modified.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import polars as pl
from pydantic import BaseModel

from glacies.model.transit.schema import MODE_BY_ROUTE_TYPE, OTHER_MODE, conform, empty
from glacies.provenance import DataNature
from glacies.validate.gtfs.common import gtfs_seconds, haversine_m, to_float, to_int
from glacies.validate.gtfs.loader import Feed, load_feed
from glacies.validate.gtfs.report import Thresholds
from glacies.validate.gtfs.structural import WEEKDAYS

Bbox = tuple[float, float, float, float]
_TRIP = ("trip_id",)


class TransitBuildError(Exception):
    """A feed cannot be turned into the canonical model."""


@dataclass(frozen=True)
class FeedInput:
    dataset: str
    snapshot: str
    checksum_sha256: str
    directory: Path
    route_number_pattern: str | None = None
    exclude_route_pattern: str | None = None


class CleaningStep(BaseModel):
    dataset: str
    step: str
    trips_before: int
    trips_after: int
    detail: str


@dataclass
class TransitBuild:
    tables: dict[str, pl.DataFrame]
    steps: list[CleaningStep] = field(default_factory=list)


@dataclass
class _Prepared:
    stops: pl.DataFrame
    routes: pl.DataFrame
    services: pl.DataFrame
    trips: pl.DataFrame
    stop_times: pl.DataFrame
    dropped: list[pl.DataFrame]


def build_transit(
    feeds: Sequence[FeedInput],
    *,
    service_date: date,
    bbox: Bbox,
    thresholds: Thresholds,
    drop_implausible_speed_trips: bool = True,
) -> TransitBuild:
    steps: list[CleaningStep] = []
    prepared = [
        _prepare(
            feed_idx,
            inp,
            service_date=service_date,
            bbox=bbox,
            thresholds=thresholds,
            drop_implausible_speed_trips=drop_implausible_speed_trips,
            steps=steps,
        )
        for feed_idx, inp in enumerate(feeds)
    ]
    tables = _merge(feeds, prepared)
    return TransitBuild(tables=tables, steps=steps)


# --- per-feed preparation (source-ID space) --------------------------------------------------


def _prepare(
    feed_idx: int,
    inp: FeedInput,
    *,
    service_date: date,
    bbox: Bbox,
    thresholds: Thresholds,
    drop_implausible_speed_trips: bool,
    steps: list[CleaningStep],
) -> _Prepared:
    feed = load_feed(inp.directory)
    _require(feed, inp.dataset)
    dropped: list[pl.DataFrame] = []

    def step(name: str, before: int, after: int, detail: str) -> None:
        steps.append(
            CleaningStep(
                dataset=inp.dataset,
                step=name,
                trips_before=before,
                trips_after=after,
                detail=detail,
            )
        )

    routes = feed["routes"].select(
        pl.col("route_id").alias("source_route_id"),
        _optional(feed["routes"], "route_short_name").alias("short_name"),
        _optional(feed["routes"], "route_long_name").alias("long_name"),
        to_int("route_type").alias("route_type"),
    )
    trips = feed["trips"].select(
        "trip_id",
        "route_id",
        "service_id",
        _optional(feed["trips"], "trip_headsign").alias("headsign"),
        to_int("direction_id").alias("direction_id")
        if "direction_id" in feed["trips"].columns
        else pl.lit(None, dtype=pl.Int64).alias("direction_id"),
    )
    route_info = routes.select(
        pl.col("source_route_id").alias("route_id"), "short_name", "route_type"
    )

    def drop(frame: pl.DataFrame, reason: str, detail: str = "") -> None:
        """Record trips (``trip_id`` + optional speed columns) as dropped."""
        if frame.is_empty():
            return
        info = frame.join(trips.select("trip_id", "route_id"), on="trip_id", how="left").join(
            route_info.select("route_id", "short_name"), on="route_id", how="left"
        )
        defaults = {
            "max_speed_kmh": pl.lit(None, dtype=pl.Float64),
            "threshold_kmh": pl.lit(None, dtype=pl.Float64),
            "from_stop_id": pl.lit(None, dtype=pl.String),
            "to_stop_id": pl.lit(None, dtype=pl.String),
        }
        dropped.append(
            conform(
                "dropped_trips",
                info.with_columns(
                    *(
                        expr.alias(name)
                        for name, expr in defaults.items()
                        if name not in info.columns
                    ),
                    pl.lit(inp.dataset).alias("dataset"),
                    pl.col("trip_id").alias("source_trip_id"),
                    pl.col("route_id").alias("source_route_id"),
                    pl.col("short_name").alias("route_short_name"),
                    pl.lit(reason).alias("reason"),
                    pl.lit(detail).alias("detail"),
                ),
            )
        )

    # 1. Service day.
    active = _active_services(feed, service_date)
    before = trips.height
    trips = trips.filter(pl.col("service_id").is_in(active.implode()))
    step(
        "service_date",
        before,
        trips.height,
        f"{service_date.isoformat()} ({WEEKDAYS[service_date.weekday()]}): "
        f"{active.len()} active services",
    )

    # 2. Non-revenue routes.
    if inp.exclude_route_pattern:
        pattern = inp.exclude_route_pattern
        excluded = routes.filter(
            pl.col("short_name").fill_null("").str.contains(pattern)
            | pl.col("long_name").fill_null("").str.contains(pattern)
        )["source_route_id"]
        hit = trips.filter(pl.col("route_id").is_in(excluded.implode()))
        drop(hit.select(_TRIP), "excluded_route", f"route name matches {pattern!r}")
        before = trips.height
        trips = trips.filter(~pl.col("route_id").is_in(excluded.implode()))
        step(
            "excluded_route",
            before,
            trips.height,
            f"{excluded.len()} routes match {pattern!r}",
        )

    stops = _stops(feed)
    stop_times = _stop_times(feed, trips, stops)

    # 3. Trips without stop times, or whose first or last stop has no time, cannot be placed.
    no_times = trips.filter(~pl.col("trip_id").is_in(stop_times["trip_id"].unique().implode()))
    drop(no_times.select(_TRIP), "no_stop_times")
    before = trips.height
    trips = trips.filter(~pl.col("trip_id").is_in(no_times["trip_id"].implode()))
    step("no_stop_times", before, trips.height, "trips without any stop times")
    endpoints = stop_times.group_by("trip_id").agg(
        pl.col("arr").first().is_null() | pl.col("arr").last().is_null()
    )
    untimed = endpoints.filter(pl.col("arr"))["trip_id"]
    drop(untimed.to_frame(), "missing_endpoint_time")
    before = trips.height
    trips, stop_times = _keep_trips(trips, stop_times, untimed)
    step("missing_endpoint_time", before, trips.height, "first or last stop without times")

    # 4. Interpolate intermediate stops without times (Estimated).
    stop_times = _interpolate(stop_times)
    estimated = stop_times.filter(pl.col("time_nature") == DataNature.ESTIMATED.value).height
    step(
        "interpolated_times",
        trips.height,
        trips.height,
        f"{estimated} stop times interpolated by distance (Estimated)",
    )

    # 5. Impossible speeds, checked on the full trip before clipping.
    if drop_implausible_speed_trips:
        worst = _worst_speed_hops(stop_times, trips, route_info, thresholds)
        drop(
            worst.select("trip_id", "max_speed_kmh", "threshold_kmh", "from_stop_id", "to_stop_id"),
            "implausible_speed",
            "fastest hop exceeds the Assumed speed limit for the route type",
        )
        before = trips.height
        trips, stop_times = _keep_trips(trips, stop_times, worst["trip_id"])
        step(
            "implausible_speed",
            before,
            trips.height,
            "trips with any hop above the route-type speed limit",
        )

    # 6. Exact duplicates (same route, service, stops and times): keep the lowest trip_id.
    duplicates = _duplicate_trips(trips, stop_times)
    drop(duplicates.to_frame(), "duplicate_trip", "repeats another trip exactly")
    before = trips.height
    trips, stop_times = _keep_trips(trips, stop_times, duplicates)
    step("duplicate_trip", before, trips.height, "exact duplicates removed")

    # 7. A trip needs at least two stops to carry anyone anywhere.
    sizes = stop_times.group_by("trip_id").len()
    single = sizes.filter(pl.col("len") < 2)["trip_id"]
    drop(single.to_frame(), "single_stop_trip", "trip visits only one stop")
    before = trips.height
    trips, stop_times = _keep_trips(trips, stop_times, single)
    step("single_stop_trip", before, trips.height, "trips with fewer than two stops")

    # 8. Clip to the study area, splitting trips that leave and re-enter.
    stop_times, outside, detail = _clip(stop_times, stops, bbox)
    drop(outside.to_frame(), "outside_study_area", "fewer than 2 consecutive stops inside bbox")
    before = trips.height
    trips = trips.filter(~pl.col("trip_id").is_in(outside.implode()))
    step("study_area_clip", before, trips.height, detail)

    # Assemble source-space tables for the trips that survived.
    pieces = stop_times.select("trip_id", "piece").unique()
    trips_out = trips.join(pieces, on="trip_id", how="inner").select(
        pl.col("trip_id").alias("source_trip_id"),
        "piece",
        pl.col("route_id").alias("source_route_id"),
        pl.col("service_id").alias("source_service_id"),
        "headsign",
        "direction_id",
    )
    used_stops = stop_times["stop_id"].unique()
    parents = stops.filter(pl.col("source_stop_id").is_in(used_stops.implode()))[
        "parent_station"
    ].drop_nulls()
    stops_out = stops.filter(
        pl.col("source_stop_id").is_in(used_stops.implode())
        | pl.col("source_stop_id").is_in(parents.implode())
    )
    routes_out = routes.filter(
        pl.col("source_route_id").is_in(trips_out["source_route_id"].unique().implode())
    ).with_columns(_route_number(inp.route_number_pattern))
    services_out = trips_out.select(pl.col("source_service_id")).unique().sort("source_service_id")
    stop_times_out = stop_times.select(
        pl.col("trip_id").alias("source_trip_id"),
        "piece",
        "position",
        pl.col("stop_id").alias("source_stop_id"),
        pl.col("arr").alias("arrival"),
        pl.col("dep").alias("departure"),
        "time_nature",
    )
    return _Prepared(
        stops=stops_out.with_columns(pl.lit(feed_idx).alias("feed_idx")),
        routes=routes_out.with_columns(pl.lit(feed_idx).alias("feed_idx")),
        services=services_out.with_columns(pl.lit(feed_idx).alias("feed_idx")),
        trips=trips_out.with_columns(pl.lit(feed_idx).alias("feed_idx")),
        stop_times=stop_times_out.with_columns(pl.lit(feed_idx).alias("feed_idx")),
        dropped=dropped,
    )


def _require(feed: Feed, dataset: str) -> None:
    needed = {
        "stops": ("stop_id", "stop_lat", "stop_lon"),
        "routes": ("route_id", "route_type"),
        "trips": ("trip_id", "route_id", "service_id"),
        "stop_times": ("trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"),
    }
    for name, columns in needed.items():
        if not feed.has_columns(name, *columns):
            raise TransitBuildError(f"{dataset}: {name}.txt is missing or lacks {columns}")
    if feed.has("frequencies") and feed["frequencies"].height:
        raise TransitBuildError(
            f"{dataset}: frequency-based trips (frequencies.txt) are not supported yet"
        )


def _optional(frame: pl.DataFrame, column: str) -> pl.Expr:
    return pl.col(column) if column in frame.columns else pl.lit(None, dtype=pl.String)


def _active_services(feed: Feed, day: date) -> pl.Series:
    ymd = day.strftime("%Y%m%d")
    weekday = WEEKDAYS[day.weekday()]
    base = pl.Series("service_id", [], dtype=pl.String)
    if feed.has("calendar"):
        cal = feed["calendar"]
        base = cal.filter(
            (pl.col(weekday) == "1") & (pl.col("start_date") <= ymd) & (pl.col("end_date") >= ymd)
        )["service_id"]
    added = removed = pl.Series("service_id", [], dtype=pl.String)
    if feed.has("calendar_dates"):
        today = feed["calendar_dates"].filter(pl.col("date") == ymd)
        added = today.filter(pl.col("exception_type") == "1")["service_id"]
        removed = today.filter(pl.col("exception_type") == "2")["service_id"]
    active = pl.concat([base, added]).unique()
    return active.filter(~active.is_in(removed.implode())).sort()


def _stops(feed: Feed) -> pl.DataFrame:
    raw = feed["stops"]
    return raw.select(
        pl.col("stop_id").alias("source_stop_id"),
        _optional(raw, "stop_name").alias("name"),
        to_float("stop_lat").alias("lat"),
        to_float("stop_lon").alias("lon"),
        (to_int("location_type") if "location_type" in raw.columns else pl.lit(0))
        .fill_null(0)
        .alias("location_type"),
        _optional(raw, "parent_station").alias("parent_station"),
    ).filter(pl.col("location_type").is_in([0, 1]))  # entrances, nodes, boarding areas later


def _stop_times(feed: Feed, trips: pl.DataFrame, stops: pl.DataFrame) -> pl.DataFrame:
    st = (
        feed["stop_times"]
        .join(trips.select(_TRIP), on="trip_id", how="semi")
        .select(
            "trip_id",
            "stop_id",
            to_int("stop_sequence").alias("seq"),
            gtfs_seconds("arrival_time").alias("arr"),
            gtfs_seconds("departure_time").alias("dep"),
        )
        .with_columns(
            pl.coalesce("arr", "dep").alias("arr"), pl.coalesce("dep", "arr").alias("dep")
        )
        .sort("trip_id", "seq")
    )
    coords = stops.select(pl.col("source_stop_id").alias("stop_id"), "lat", "lon")
    return st.join(coords, on="stop_id", how="left").sort("trip_id", "seq")


def _keep_trips(
    trips: pl.DataFrame, stop_times: pl.DataFrame, remove: pl.Series
) -> tuple[pl.DataFrame, pl.DataFrame]:
    ids = remove.implode()
    return (
        trips.filter(~pl.col("trip_id").is_in(ids)),
        stop_times.filter(~pl.col("trip_id").is_in(ids)),
    )


def _interpolate(st: pl.DataFrame) -> pl.DataFrame:
    hop = haversine_m(
        pl.col("lat").shift(1).over("trip_id"),
        pl.col("lon").shift(1).over("trip_id"),
        pl.col("lat"),
        pl.col("lon"),
    ).fill_null(0.0)
    st = st.with_columns(hop.cum_sum().over("trip_id").alias("_cum"))
    timed = pl.col("arr").is_not_null()
    st = st.with_columns(
        pl.when(timed).then(pl.col("dep")).forward_fill().over("trip_id").alias("_t0"),
        pl.when(timed).then(pl.col("_cum")).forward_fill().over("trip_id").alias("_c0"),
        pl.when(timed).then(pl.col("arr")).backward_fill().over("trip_id").alias("_t1"),
        pl.when(timed).then(pl.col("_cum")).backward_fill().over("trip_id").alias("_c1"),
    )
    span = pl.col("_c1") - pl.col("_c0")
    fraction = pl.when(span > 0).then((pl.col("_cum") - pl.col("_c0")) / span).otherwise(0.0)
    estimate = (pl.col("_t0") + (pl.col("_t1") - pl.col("_t0")) * fraction).floor().cast(pl.Int64)
    return st.with_columns(
        pl.when(timed).then(pl.col("arr")).otherwise(estimate).alias("arr"),
        pl.when(timed).then(pl.col("dep")).otherwise(estimate).alias("dep"),
        pl.when(timed)
        .then(pl.lit(DataNature.OBSERVED.value))
        .otherwise(pl.lit(DataNature.ESTIMATED.value))
        .alias("time_nature"),
    ).drop("_cum", "_t0", "_c0", "_t1", "_c1")


def _worst_speed_hops(
    st: pl.DataFrame,
    trips: pl.DataFrame,
    route_info: pl.DataFrame,
    thresholds: Thresholds,
) -> pl.DataFrame:
    limits = pl.DataFrame(
        {
            "route_type": [int(k) for k in thresholds.max_speed_kmh],
            "threshold_kmh": list(thresholds.max_speed_kmh.values()),
        },
        schema={"route_type": pl.Int64, "threshold_kmh": pl.Float64},
    )
    types = trips.select("trip_id", "route_id").join(
        route_info.select("route_id", "route_type"), on="route_id", how="left"
    )
    hops = (
        st.with_columns(
            pl.col("dep").shift(1).over("trip_id").alias("_prev_dep"),
            pl.col("stop_id").shift(1).over("trip_id").alias("from_stop_id"),
            haversine_m(
                pl.col("lat").shift(1).over("trip_id"),
                pl.col("lon").shift(1).over("trip_id"),
                pl.col("lat"),
                pl.col("lon"),
            ).alias("_dist"),
        )
        .filter(pl.col("_prev_dep").is_not_null() & pl.col("_dist").is_not_null())
        .with_columns((pl.col("arr") - pl.col("_prev_dep")).alias("_dt"))
        .filter(pl.col("_dt") > 0)
        .with_columns(
            (pl.col("_dist") / pl.col("_dt") * 3.6).round(1).alias("max_speed_kmh"),
            pl.col("stop_id").alias("to_stop_id"),
        )
        .join(types.select("trip_id", "route_type"), on="trip_id", how="left")
        .join(limits, on="route_type", how="left")
        .with_columns(pl.col("threshold_kmh").fill_null(thresholds.default_max_speed_kmh))
    )
    return (
        hops.filter(pl.col("max_speed_kmh") > pl.col("threshold_kmh"))
        .sort(["trip_id", "max_speed_kmh", "seq"], descending=[False, True, False])
        .unique(subset="trip_id", keep="first", maintain_order=True)
        .select("trip_id", "max_speed_kmh", "threshold_kmh", "from_stop_id", "to_stop_id")
    )


def _duplicate_trips(trips: pl.DataFrame, st: pl.DataFrame) -> pl.Series:
    signatures = st.group_by("trip_id", maintain_order=True).agg(
        pl.concat_str(
            [pl.col("stop_id"), pl.col("arr").cast(pl.String), pl.col("dep").cast(pl.String)],
            separator="|",
        )
        .str.join(";")
        .alias("_sig")
    )
    keyed = (
        trips.join(signatures, on="trip_id", how="inner")
        .sort("trip_id")
        .with_columns(pl.int_range(pl.len()).over("route_id", "service_id", "_sig").alias("_n"))
    )
    return keyed.filter(pl.col("_n") > 0)["trip_id"]


def _clip(st: pl.DataFrame, stops: pl.DataFrame, bbox: Bbox) -> tuple[pl.DataFrame, pl.Series, str]:
    min_lon, min_lat, max_lon, max_lat = bbox
    inside = (
        pl.col("lon").is_between(min_lon, max_lon) & pl.col("lat").is_between(min_lat, max_lat)
    ).fill_null(False)
    st = st.with_columns(inside.alias("_in"))
    starts = pl.col("_in") & ~pl.col("_in").shift(1).over("trip_id").fill_null(False)
    st = st.with_columns(starts.cast(pl.Int64).cum_sum().over("trip_id").alias("_piece"))
    kept = st.filter(pl.col("_in"))
    sizes = kept.group_by("trip_id", "_piece").len()
    good = sizes.filter(pl.col("len") >= 2)
    kept = kept.join(good.select("trip_id", "_piece"), on=["trip_id", "_piece"], how="semi")

    # Renumber: 0 when a trip stays in one piece, otherwise 1..k in travel order.
    counts = good.group_by("trip_id").agg(pl.len().alias("_pieces"))
    kept = (
        kept.join(counts, on="trip_id")
        .with_columns(pl.col("_piece").rank("dense").over("trip_id").cast(pl.Int64).alias("_k"))
        .with_columns(pl.when(pl.col("_pieces") > 1).then(pl.col("_k")).otherwise(0).alias("piece"))
        .sort("trip_id", "piece", "seq")
        .with_columns(pl.int_range(pl.len()).over("trip_id", "piece").alias("position"))
    )
    all_trips = st["trip_id"].unique()
    survivors = counts["trip_id"]
    outside = all_trips.filter(~all_trips.is_in(survivors.implode())).sort()
    original_sizes = st.group_by("trip_id").len()
    kept_sizes = kept.group_by("trip_id").len()
    shortened = original_sizes.join(kept_sizes, on="trip_id", suffix="_kept").filter(
        pl.col("len_kept") < pl.col("len")
    )
    split = counts.filter(pl.col("_pieces") > 1)
    detail = (
        f"{shortened.height} trips shortened, {split.height} split into "
        f"{int(split['_pieces'].sum() or 0)} pieces, {outside.len()} outside"
    )
    columns = ["trip_id", "piece", "position", "stop_id", "arr", "dep", "time_nature"]
    return kept.select(columns), outside, detail


def _route_number(pattern: str | None) -> pl.Expr:
    fallback = pl.coalesce("short_name", "long_name")
    if pattern is None:
        return fallback.alias("route_number")
    return pl.coalesce(pl.col("short_name").str.extract(pattern, 0), fallback).alias("route_number")


# --- merge feeds and assign dense indices ----------------------------------------------------


def _merge(feeds: Sequence[FeedInput], prepared: list[_Prepared]) -> dict[str, pl.DataFrame]:
    feeds_table = conform(
        "feeds",
        pl.DataFrame(
            {
                "feed_idx": list(range(len(feeds))),
                "dataset": [f.dataset for f in feeds],
                "snapshot": [f.snapshot for f in feeds],
                "checksum_sha256": [f.checksum_sha256 for f in feeds],
            }
        ),
    )
    if not prepared:
        return (
            {"feeds": feeds_table}
            | {
                name: empty(name)
                for name in ("stops", "routes", "services", "patterns", "pattern_stops", "trips")
            }
            | {"stop_times": empty("stop_times"), "dropped_trips": empty("dropped_trips")}
        )

    def concat(attr: str) -> pl.DataFrame:
        frames: list[pl.DataFrame] = [getattr(p, attr) for p in prepared]
        return pl.concat(frames, how="vertical_relaxed")

    def indexed(frame: pl.DataFrame, by: list[str], name: str) -> pl.DataFrame:
        return frame.sort(by).with_row_index(name)

    stops = indexed(concat("stops"), ["feed_idx", "source_stop_id"], "stop_idx")
    stop_key = stops.select("feed_idx", "source_stop_id", "stop_idx")
    stops = stops.join(
        stop_key.rename({"source_stop_id": "parent_station", "stop_idx": "parent_stop_idx"}),
        on=["feed_idx", "parent_station"],
        how="left",
    ).sort("stop_idx")

    routes = indexed(concat("routes"), ["feed_idx", "source_route_id"], "route_idx")
    routes = routes.with_columns(
        pl.col("route_type")
        .replace_strict(MODE_BY_ROUTE_TYPE, default=OTHER_MODE, return_dtype=pl.String)
        .alias("mode")
    )
    services = indexed(concat("services"), ["feed_idx", "source_service_id"], "service_idx")

    stop_times = concat("stop_times").join(stop_key, on=["feed_idx", "source_stop_id"])
    trip_key = ["feed_idx", "source_trip_id", "piece"]
    sequences = (
        stop_times.sort([*trip_key, "position"])
        .group_by(trip_key, maintain_order=True)
        .agg(
            pl.col("stop_idx").alias("_stops"),
            pl.col("departure").first().alias("_first_departure"),
        )
        .with_columns(
            pl.col("_stops").list.eval(pl.element().cast(pl.String)).list.join(",").alias("_key")
        )
    )
    trips = (
        concat("trips")
        .join(sequences, on=trip_key)
        .join(
            routes.select("feed_idx", "source_route_id", "route_idx"),
            on=["feed_idx", "source_route_id"],
        )
        .join(
            services.select("feed_idx", "source_service_id", "service_idx"),
            on=["feed_idx", "source_service_id"],
        )
    )
    patterns = indexed(
        trips.select("route_idx", "_key", "_stops").unique(subset=["route_idx", "_key"]),
        ["route_idx", "_key"],
        "pattern_idx",
    ).with_columns(pl.col("_stops").list.len().alias("stop_count"))
    pattern_stops = (
        patterns.select("pattern_idx", "_stops")
        .explode("_stops", empty_as_null=False)
        .with_columns(pl.int_range(pl.len()).over("pattern_idx").alias("position"))
        .rename({"_stops": "stop_idx"})
    )
    trips = indexed(
        trips.join(patterns.select("route_idx", "_key", "pattern_idx"), on=["route_idx", "_key"]),
        ["pattern_idx", "_first_departure", "feed_idx", "source_trip_id", "piece"],
        "trip_idx",
    )
    stop_times = stop_times.join(trips.select(*trip_key, "trip_idx"), on=trip_key).sort(
        "trip_idx", "position"
    )
    dropped_frames = [d for p in prepared for d in p.dropped]
    dropped = (
        pl.concat(dropped_frames).sort("dataset", "reason", "source_trip_id")
        if dropped_frames
        else empty("dropped_trips")
    )
    return {
        "feeds": feeds_table,
        "stops": conform("stops", stops),
        "routes": conform("routes", routes),
        "services": conform("services", services),
        "patterns": conform("patterns", patterns),
        "pattern_stops": conform("pattern_stops", pattern_stops),
        "trips": conform("trips", trips),
        "stop_times": conform("stop_times", stop_times),
        "dropped_trips": conform("dropped_trips", dropped),
    }
