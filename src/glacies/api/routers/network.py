"""The baseline network and zones as map layers (PRD §40, §43).

Lines are drawn stop to stop: the canonical network keeps no GTFS shapes, so every geometry
here is a straight line between consecutive stops (Assumed) and says so in ``fields``.
Zones are sent as H3 cell ids with values; the browser builds the hexagons, so 10,661 zones
cost a few hundred kilobytes instead of a vector-tile pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import polars as pl
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from glacies.api.deps import City, CityDep, require
from glacies.api.labels import FieldInfo, Labelled, field
from glacies.api.store import Memo, query
from glacies.provenance import DataNature
from glacies.routing.network import RouterError, clock, parse_clock

router = APIRouter(prefix="/api/cities/{city}", tags=["network"])
_memo = Memo()

Coord = tuple[float, float]  # [lon, lat], GeoJSON order
DIGITS = 6  # ~0.1 m: more precision only makes the responses bigger


class Point(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: Coord


class LineString(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[Coord]


# --- routes -------------------------------------------------------------------------------


class Window(BaseModel):
    start: str = Field(description="HH:MM, inclusive.")
    end: str = Field(description="HH:MM, exclusive.")


class RouteSummary(BaseModel):
    route_idx: int
    feed: str
    route_id: str = Field(description="The feed's route_id, as used in scenario files.")
    short_name: str | None
    long_name: str | None
    mode: str
    patterns: int
    trips: int
    window_trips: int


class RouteList(Labelled):
    window: Window
    routes: list[RouteSummary]


class PatternProps(BaseModel):
    pattern_idx: int
    direction_id: int | None
    headsign: str | None
    stops: list[int] = Field(description="stop_idx in travel order.")
    trips: int
    window_trips: int


class PatternFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: LineString
    properties: PatternProps


class RouteDetail(Labelled):
    route: RouteSummary
    window: Window
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[PatternFeature]


def _route_fields() -> dict[str, FieldInfo]:
    return {
        "patterns": field(DataNature.OBSERVED, "Distinct stop sequences of the route.", "count"),
        "trips": field(DataNature.OBSERVED, "Timetabled trips on the service date.", "trips"),
        "window_trips": field(
            DataNature.OBSERVED, "Timetabled trips leaving their first stop in the window.", "trips"
        ),
    }


def _window(city: City, start: str | None, end: str | None) -> tuple[int, int]:
    acc = city.config.accessibility
    try:
        lo, hi = parse_clock(start or acc.window_start), parse_clock(end or acc.window_end)
    except RouterError as exc:
        raise HTTPException(422, str(exc)) from None
    if hi <= lo:
        raise HTTPException(422, "end must be after start")
    return lo, hi


StartQuery = Annotated[str | None, Query(description="HH:MM; default: the city's AM window.")]
EndQuery = Annotated[str | None, Query(description="HH:MM, exclusive.")]


def _transit(city: City, name: str) -> str:
    return str(require(city.data / "transit" / f"{name}.parquet", "glacies build transit"))


def _routes(city: City, lo: int, hi: int) -> pl.DataFrame:
    return query(
        """
        WITH first AS (
            SELECT trip_idx, departure FROM read_parquet($stop_times) WHERE position = 0
        ), counts AS (
            SELECT t.route_idx, count(*) AS trips,
                   count(*) FILTER (WHERE f.departure >= $lo AND f.departure < $hi) AS window_trips
            FROM read_parquet($trips) t JOIN first f USING (trip_idx)
            GROUP BY t.route_idx
        ), patterns AS (
            SELECT route_idx, count(*) AS patterns FROM read_parquet($patterns) GROUP BY route_idx
        )
        SELECT r.route_idx, f.dataset AS feed, r.source_route_id AS route_id, r.short_name,
               r.long_name, r.mode, coalesce(p.patterns, 0) AS patterns,
               coalesce(c.trips, 0) AS trips, coalesce(c.window_trips, 0) AS window_trips
        FROM read_parquet($routes) r
        JOIN read_parquet($feeds) f USING (feed_idx)
        LEFT JOIN patterns p USING (route_idx)
        LEFT JOIN counts c USING (route_idx)
        ORDER BY r.route_idx
        """,
        {
            "stop_times": _transit(city, "stop_times"),
            "trips": _transit(city, "trips"),
            "patterns": _transit(city, "patterns"),
            "routes": _transit(city, "routes"),
            "feeds": _transit(city, "feeds"),
            "lo": lo,
            "hi": hi,
        },
    )


def _transit_files(city: City) -> list[Path]:
    return [city.data / "transit" / "manifest.json"]


@router.get("/routes", response_model=RouteList)
def list_routes(
    city: CityDep,
    mode: Annotated[str | None, Query(description="Only routes of this mode.")] = None,
    start: StartQuery = None,
    end: EndQuery = None,
) -> RouteList:
    lo, hi = _window(city, start, end)
    table = _memo.get(
        ("routes", str(city.data), lo, hi), _transit_files(city), lambda: _routes(city, lo, hi)
    )
    if mode is not None:
        table = table.filter(pl.col("mode") == mode)
    return RouteList(
        fields=_route_fields(),
        window=Window(start=clock(lo), end=clock(hi)),
        routes=[RouteSummary.model_validate(row) for row in table.iter_rows(named=True)],
    )


@router.get("/routes/{route_idx}", response_model=RouteDetail)
def get_route(
    city: CityDep, route_idx: int, start: StartQuery = None, end: EndQuery = None
) -> RouteDetail:
    lo, hi = _window(city, start, end)
    routes = _memo.get(
        ("routes", str(city.data), lo, hi), _transit_files(city), lambda: _routes(city, lo, hi)
    )
    row = routes.filter(pl.col("route_idx") == route_idx)
    if row.is_empty():
        raise HTTPException(404, f"no route {route_idx}")
    stops = query(
        """
        SELECT ps.pattern_idx, ps.position, ps.stop_idx, s.lat, s.lon
        FROM read_parquet($patterns) p
        JOIN read_parquet($pattern_stops) ps USING (pattern_idx)
        JOIN read_parquet($stops) s USING (stop_idx)
        WHERE p.route_idx = $route
        ORDER BY ps.pattern_idx, ps.position
        """,
        {
            "patterns": _transit(city, "patterns"),
            "pattern_stops": _transit(city, "pattern_stops"),
            "stops": _transit(city, "stops"),
            "route": route_idx,
        },
    )
    trips = query(
        """
        SELECT t.pattern_idx, min(t.direction_id) AS direction_id, min(t.headsign) AS headsign,
               count(*) AS trips,
               count(*) FILTER (WHERE st.departure >= $lo AND st.departure < $hi) AS window_trips
        FROM read_parquet($trips) t
        JOIN read_parquet($stop_times) st ON st.trip_idx = t.trip_idx AND st.position = 0
        WHERE t.route_idx = $route
        GROUP BY t.pattern_idx
        """,
        {
            "trips": _transit(city, "trips"),
            "stop_times": _transit(city, "stop_times"),
            "route": route_idx,
            "lo": lo,
            "hi": hi,
        },
    )
    by_pattern = {r["pattern_idx"]: r for r in trips.iter_rows(named=True)}
    features = []
    for _, group in stops.group_by("pattern_idx", maintain_order=True):
        pattern_idx: int = group["pattern_idx"][0]
        meta = by_pattern.get(pattern_idx, {})
        features.append(
            PatternFeature(
                geometry=LineString(coordinates=_coords(group)),
                properties=PatternProps(
                    pattern_idx=pattern_idx,
                    direction_id=meta.get("direction_id"),
                    headsign=meta.get("headsign"),
                    stops=group["stop_idx"].to_list(),
                    trips=meta.get("trips", 0),
                    window_trips=meta.get("window_trips", 0),
                ),
            )
        )
    fields = _route_fields()
    fields["geometry"] = field(
        DataNature.ASSUMED, "Straight lines between consecutive stops (no GTFS shapes)."
    )
    return RouteDetail(
        fields=fields,
        route=RouteSummary.model_validate(row.row(0, named=True)),
        window=Window(start=clock(lo), end=clock(hi)),
        features=features,
    )


def _coords(frame: pl.DataFrame) -> list[Coord]:
    lon = frame["lon"].round(DIGITS).to_list()
    lat = frame["lat"].round(DIGITS).to_list()
    return list(zip(lon, lat, strict=True))


# --- stops --------------------------------------------------------------------------------


class StopProps(BaseModel):
    stop_idx: int
    feed: str
    stop_id: str
    name: str | None
    station: bool = Field(description="A parent station grouping platforms.")
    parent_stop_idx: int | None
    modes: list[str]
    routes: int


class StopFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: Point
    properties: StopProps


class StopCollection(Labelled):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[StopFeature]


def _stops(city: City) -> pl.DataFrame:
    return query(
        """
        WITH served AS (
            SELECT DISTINCT ps.stop_idx, p.route_idx, r.mode
            FROM read_parquet($pattern_stops) ps
            JOIN read_parquet($patterns) p USING (pattern_idx)
            JOIN read_parquet($routes) r USING (route_idx)
        ), stops AS (
            SELECT s.*, f.dataset AS feed FROM read_parquet($stops) s
            JOIN read_parquet($feeds) f USING (feed_idx)
            WHERE s.location_type IN (0, 1)
        ), keyed AS (
            -- A station is served by whatever serves its platforms.
            SELECT stop_idx AS key, route_idx, mode FROM served
            UNION
            SELECT s.parent_stop_idx AS key, v.route_idx, v.mode
            FROM served v JOIN stops s USING (stop_idx)
            WHERE s.parent_stop_idx IS NOT NULL
        )
        SELECT s.stop_idx, s.feed, s.source_stop_id AS stop_id, s.name, s.lat, s.lon,
               s.location_type = 1 AS station, s.parent_stop_idx,
               coalesce(list(DISTINCT k.mode ORDER BY k.mode)
                        FILTER (WHERE k.mode IS NOT NULL), []) AS modes,
               count(DISTINCT k.route_idx) AS routes
        FROM stops s
        LEFT JOIN keyed k ON k.key = s.stop_idx
        GROUP BY ALL
        ORDER BY s.stop_idx
        """,
        {
            "pattern_stops": _transit(city, "pattern_stops"),
            "patterns": _transit(city, "patterns"),
            "routes": _transit(city, "routes"),
            "stops": _transit(city, "stops"),
            "feeds": _transit(city, "feeds"),
        },
    )


@router.get("/stops", response_model=StopCollection)
def list_stops(city: CityDep) -> StopCollection:
    table = _memo.get(("stops", str(city.data)), _transit_files(city), lambda: _stops(city))
    features = [
        StopFeature(
            geometry=Point(coordinates=(round(r.pop("lon"), DIGITS), round(r.pop("lat"), DIGITS))),
            properties=StopProps.model_validate(r),
        )
        for r in table.iter_rows(named=True)
    ]
    return StopCollection(
        fields={
            "routes": field(DataNature.OBSERVED, "Routes calling at the stop.", "routes"),
            "geometry": field(DataNature.OBSERVED, "Stop location from the feed."),
        },
        features=features,
    )


# --- network ------------------------------------------------------------------------------


class SegmentProps(BaseModel):
    from_stop_idx: int
    to_stop_idx: int
    modes: list[str]
    routes: int
    trips: int
    window_trips: int


class SegmentFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: LineString
    properties: SegmentProps


class Network(Labelled):
    window: Window
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SegmentFeature]


def _segments(city: City, lo: int, hi: int) -> pl.DataFrame:
    return query(
        """
        WITH st AS (
            SELECT trip_idx, position, stop_idx, departure FROM read_parquet($stop_times)
        ), hops AS (
            SELECT a.stop_idx AS from_stop_idx, b.stop_idx AS to_stop_idx, t.route_idx,
                   a.departure
            FROM st a
            JOIN st b ON b.trip_idx = a.trip_idx AND b.position = a.position + 1
            JOIN read_parquet($trips) t ON t.trip_idx = a.trip_idx
        )
        SELECT h.from_stop_idx, h.to_stop_idx,
               list(DISTINCT r.mode ORDER BY r.mode) AS modes,
               count(DISTINCT h.route_idx) AS routes, count(*) AS trips,
               count(*) FILTER (WHERE h.departure >= $lo AND h.departure < $hi) AS window_trips,
               any_value(a.lon) AS from_lon, any_value(a.lat) AS from_lat,
               any_value(b.lon) AS to_lon, any_value(b.lat) AS to_lat
        FROM hops h
        JOIN read_parquet($routes) r USING (route_idx)
        JOIN read_parquet($stops) a ON a.stop_idx = h.from_stop_idx
        JOIN read_parquet($stops) b ON b.stop_idx = h.to_stop_idx
        GROUP BY h.from_stop_idx, h.to_stop_idx
        ORDER BY h.from_stop_idx, h.to_stop_idx
        """,
        {
            "stop_times": _transit(city, "stop_times"),
            "trips": _transit(city, "trips"),
            "routes": _transit(city, "routes"),
            "stops": _transit(city, "stops"),
            "lo": lo,
            "hi": hi,
        },
    )


@router.get("/network", response_model=Network)
def get_network(city: CityDep, start: StartQuery = None, end: EndQuery = None) -> Network:
    lo, hi = _window(city, start, end)
    table = _memo.get(
        ("network", str(city.data), lo, hi), _transit_files(city), lambda: _segments(city, lo, hi)
    )
    features = []
    for r in table.iter_rows(named=True):
        line = [
            (round(r.pop("from_lon"), DIGITS), round(r.pop("from_lat"), DIGITS)),
            (round(r.pop("to_lon"), DIGITS), round(r.pop("to_lat"), DIGITS)),
        ]
        features.append(
            SegmentFeature(
                geometry=LineString(coordinates=line), properties=SegmentProps.model_validate(r)
            )
        )
    return Network(
        fields={
            "routes": field(DataNature.OBSERVED, "Routes running between the two stops.", "routes"),
            "trips": field(DataNature.OBSERVED, "Timetabled trips on the service date.", "trips"),
            "window_trips": field(
                DataNature.OBSERVED, "Timetabled trips leaving from_stop in the window.", "trips"
            ),
            "geometry": field(
                DataNature.ASSUMED, "Straight line between the two stops (no GTFS shapes)."
            ),
        },
        window=Window(start=clock(lo), end=clock(hi)),
        features=features,
    )


# --- zones --------------------------------------------------------------------------------


class Zones(Labelled):
    """Columns, not rows: one array per field, all in ``zone_idx`` order."""

    resolution: int = Field(description="H3 resolution of the cells.")
    zone_idx: list[int]
    h3_cell: list[str]
    population: list[float]
    est_employment_share: list[float] | None = Field(
        description="None until `glacies build attraction` has run."
    )


@router.get("/zones", response_model=Zones)
def get_zones(city: CityDep) -> Zones:
    zones = require(city.data / "zones" / "zones.parquet", "glacies build zones")
    attraction = city.data / "attraction" / "attraction.parquet"
    if attraction.is_file():
        table = query(
            """
            SELECT z.zone_idx, z.h3_cell, z.population, a.employment_score
            FROM read_parquet($zones) z LEFT JOIN read_parquet($attraction) a USING (zone_idx)
            ORDER BY z.zone_idx
            """,
            {"zones": str(zones), "attraction": str(attraction)},
        )
    else:
        table = query(
            "SELECT zone_idx, h3_cell, population FROM read_parquet($zones) ORDER BY zone_idx",
            {"zones": str(zones)},
        )
    has_jobs = "employment_score" in table.columns
    return Zones(
        fields={
            "population": field(
                DataNature.ESTIMATED, "Residents per zone from the population raster.", "people"
            ),
            "est_employment_share": field(
                DataNature.ESTIMATED,
                "Share of the city's estimated employment (building and job-POI proxy); sums "
                "to 1. Not a job count.",
                "share",
            ),
        },
        resolution=city.config.zoning.resolution,
        zone_idx=table["zone_idx"].to_list(),
        h3_cell=table["h3_cell"].to_list(),
        population=table["population"].to_list(),
        est_employment_share=table["employment_score"].fill_null(0.0).to_list()
        if has_jobs
        else None,
    )
