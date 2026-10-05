"""Coverage figures: how much of a network the feed contains (PRD Risk 1)."""

from __future__ import annotations

import polars as pl

from glacies.cities import CoverageReference
from glacies.validate.gtfs.loader import Feed
from glacies.validate.gtfs.report import Coverage


def measure_coverage(
    feed: Feed,
    route_number_pattern: str | None,
    reference: CoverageReference | None,
) -> Coverage:
    routes = feed["routes"] if feed.has_columns("routes", "route_id") else pl.DataFrame()
    trips = feed["trips"] if feed.has_columns("trips", "route_id") else pl.DataFrame()

    routes_with_trips = (
        routes.filter(pl.col("route_id").is_in(trips["route_id"].unique().implode())).height
        if routes.height and trips.height
        else 0
    )
    routes_by_type: dict[str, int] = {}
    if "route_type" in routes.columns:
        counts = routes.group_by("route_type").len().drop_nulls().sort("route_type")
        routes_by_type = dict(zip(counts["route_type"], counts["len"], strict=True))

    distinct_numbers: int | None = None
    if route_number_pattern is not None and "route_short_name" in routes.columns:
        numbers = routes["route_short_name"].str.extract(route_number_pattern, 0).drop_nulls()
        distinct_numbers = numbers.n_unique()

    stops_total = stops_served = 0
    if feed.has_columns("stops", "stop_id"):
        stops = feed["stops"]
        if "location_type" in stops.columns:
            stops = stops.filter(
                pl.col("location_type").is_null() | (pl.col("location_type") == "0")
            )
        stops_total = stops.height
        if feed.has_columns("stop_times", "stop_id"):
            served = feed["stop_times"]["stop_id"].unique().implode()
            stops_served = stops.filter(pl.col("stop_id").is_in(served)).height

    coverage = Coverage(
        route_rows=routes.height,
        routes_with_trips=routes_with_trips,
        distinct_route_numbers=distinct_numbers,
        route_number_pattern=route_number_pattern,
        routes_by_type=routes_by_type,
        stops_total=stops_total,
        stops_served=stops_served,
    )
    if reference is not None:
        coverage.reference_route_count_min = reference.route_count_min
        coverage.reference_route_count_max = reference.route_count_max
        coverage.reference_source = reference.source
        coverage.reference_verified = reference.verified
        # Compare like with like: route numbers if a pattern is configured, else route rows.
        feed_count = distinct_numbers if distinct_numbers is not None else routes_with_trips
        coverage.ratio_min = round(feed_count / reference.route_count_max, 3)
        coverage.ratio_max = round(feed_count / reference.route_count_min, 3)
    return coverage
