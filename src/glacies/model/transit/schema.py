"""Canonical transit tables (PRD §17): source-independent, integer-indexed, one service day.

Indices (``*_idx``) are dense and assigned in a deterministic sort order, so they can be used
directly as array offsets by the Rust router. ``source_*_id`` columns map back to the feed.
"""

from __future__ import annotations

import polars as pl

# GTFS basic route_type -> canonical mode name.
MODE_BY_ROUTE_TYPE: dict[int, str] = {
    0: "tram",
    1: "metro",
    2: "rail",
    3: "bus",
    4: "ferry",
    5: "cable_tram",
    6: "aerial_lift",
    7: "funicular",
    11: "trolleybus",
    12: "monorail",
}
OTHER_MODE = "other"

SCHEMAS: dict[str, dict[str, pl.DataType]] = {
    "feeds": {
        "feed_idx": pl.UInt16(),
        "dataset": pl.String(),
        "snapshot": pl.String(),
        "checksum_sha256": pl.String(),
    },
    "stops": {
        "stop_idx": pl.UInt32(),
        "feed_idx": pl.UInt16(),
        "source_stop_id": pl.String(),
        "name": pl.String(),
        "lat": pl.Float64(),
        "lon": pl.Float64(),
        "location_type": pl.UInt8(),  # 0 boarding point, 1 station
        "parent_stop_idx": pl.UInt32(),
    },
    "routes": {
        "route_idx": pl.UInt32(),
        "feed_idx": pl.UInt16(),
        "source_route_id": pl.String(),
        "short_name": pl.String(),
        "long_name": pl.String(),
        "route_number": pl.String(),
        "route_type": pl.UInt16(),
        "mode": pl.String(),
    },
    "services": {
        "service_idx": pl.UInt32(),
        "feed_idx": pl.UInt16(),
        "source_service_id": pl.String(),
    },
    "patterns": {
        "pattern_idx": pl.UInt32(),
        "route_idx": pl.UInt32(),
        "stop_count": pl.UInt16(),
    },
    "pattern_stops": {
        "pattern_idx": pl.UInt32(),
        "position": pl.UInt16(),
        "stop_idx": pl.UInt32(),
    },
    "trips": {
        "trip_idx": pl.UInt32(),
        "pattern_idx": pl.UInt32(),
        "route_idx": pl.UInt32(),
        "service_idx": pl.UInt32(),
        "feed_idx": pl.UInt16(),
        "source_trip_id": pl.String(),
        "piece": pl.UInt8(),  # >0 when a trip was split by the study-area clip
        "headsign": pl.String(),
        "direction_id": pl.UInt8(),
    },
    "stop_times": {
        "trip_idx": pl.UInt32(),
        "position": pl.UInt16(),
        "stop_idx": pl.UInt32(),
        "arrival": pl.UInt32(),  # seconds since service-day midnight; may exceed 86 400
        "departure": pl.UInt32(),
        "time_nature": pl.String(),  # observed (from the feed) or estimated (interpolated)
    },
    "dropped_trips": {
        "dataset": pl.String(),
        "source_trip_id": pl.String(),
        "source_route_id": pl.String(),
        "route_short_name": pl.String(),
        "reason": pl.String(),
        "max_speed_kmh": pl.Float64(),
        "threshold_kmh": pl.Float64(),
        "from_stop_id": pl.String(),
        "to_stop_id": pl.String(),
        "detail": pl.String(),
    },
}

TABLES = tuple(SCHEMAS)


def conform(name: str, frame: pl.DataFrame) -> pl.DataFrame:
    """Select and cast a frame to its canonical column order and types."""
    schema = SCHEMAS[name]
    return frame.select(pl.col(column).cast(dtype) for column, dtype in schema.items())


def empty(name: str) -> pl.DataFrame:
    return pl.DataFrame(schema=SCHEMAS[name])
