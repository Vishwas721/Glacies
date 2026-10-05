"""Load canonical layers into PostGIS for inspection in QGIS (PRD §48).

PostGIS holds geometry and metadata only; Parquet stays the source of truth. Each load replaces
the city's tables, so it can be re-run at any time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import h3
import polars as pl
import psycopg
from psycopg import sql

_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")
_PG_TYPES: dict[type[pl.DataType], str] = {
    pl.Int8: "smallint", pl.Int16: "smallint", pl.Int32: "integer", pl.Int64: "bigint",
    pl.UInt8: "smallint", pl.UInt16: "integer", pl.UInt32: "bigint", pl.UInt64: "numeric",
    pl.Float32: "real", pl.Float64: "double precision",
    pl.String: "text", pl.Boolean: "boolean",
}  # fmt: skip


@dataclass(frozen=True)
class Layer:
    name: str
    frame: pl.DataFrame  # attribute columns plus a ``wkt`` column
    geometry: str  # PostGIS geometry type, e.g. "Polygon"


def pg_type(dtype: pl.DataType) -> str:
    try:
        return _PG_TYPES[type(dtype)]
    except KeyError:
        raise ValueError(f"no PostgreSQL type for polars dtype {dtype}") from None


def zone_wkt(cell: str) -> str:
    ring = [(lon, lat) for lat, lon in h3.cell_to_boundary(cell)]
    ring.append(ring[0])
    return "POLYGON((" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in ring) + "))"


def layers(transit: dict[str, pl.DataFrame], zones: pl.DataFrame) -> list[Layer]:
    """Zones (polygons), stops (points) and stop-to-stop pattern lines (schematic)."""
    zone_layer = zones.with_columns(
        pl.col("h3_cell").map_elements(zone_wkt, return_dtype=pl.String).alias("wkt")
    )
    stops = transit["stops"].with_columns(
        pl.format("POINT({} {})", pl.col("lon").round(7), pl.col("lat").round(7)).alias("wkt")
    )
    coords = transit["pattern_stops"].join(
        transit["stops"].select("stop_idx", "lat", "lon"), on="stop_idx"
    )
    lines = (
        coords.sort("pattern_idx", "position")
        .group_by("pattern_idx", maintain_order=True)
        .agg(pl.format("{} {}", pl.col("lon").round(7), pl.col("lat").round(7)).str.join(", "))
        .rename({"lon": "points"})
        .with_columns(pl.format("LINESTRING({})", pl.col("points")).alias("wkt"))
        .join(transit["patterns"], on="pattern_idx")
        .join(
            transit["routes"].select("route_idx", "short_name", "route_number", "mode"),
            on="route_idx",
        )
        .join(
            transit["trips"].group_by("pattern_idx").len().rename({"len": "trips"}),
            on="pattern_idx",
        )
        .select(
            "pattern_idx",
            "route_idx",
            "short_name",
            "route_number",
            "mode",
            "stop_count",
            "trips",
            "wkt",
        )
        .sort("pattern_idx")
    )
    return [
        Layer("zones", zone_layer, "Polygon"),
        Layer("stops", stops.drop("lat", "lon"), "Point"),
        Layer("pattern_lines", lines, "LineString"),
    ]


def load(database_url: str, schema: str, to_load: list[Layer]) -> dict[str, int]:
    """Replace ``schema.<layer>`` tables; returns row counts."""
    if not _IDENTIFIER.fullmatch(schema):
        raise ValueError(f"invalid schema name {schema!r}")
    counts: dict[str, int] = {}
    with psycopg.connect(database_url) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        for layer in to_load:
            counts[layer.name] = _load_layer(conn, schema, layer)
    return counts


def _load_layer(conn: psycopg.Connection, schema: str, layer: Layer) -> int:
    table = sql.Identifier(schema, layer.name)
    attributes = [c for c in layer.frame.columns if c != "wkt"]
    columns = sql.SQL(", ").join(
        sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(pg_type(layer.frame.schema[c])))
        for c in attributes
    )
    conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
    conn.execute(sql.SQL("CREATE TABLE {} ({}, wkt text)").format(table, columns))
    names = sql.SQL(", ").join(sql.Identifier(c) for c in [*attributes, "wkt"])
    with (
        conn.cursor() as cur,
        cur.copy(sql.SQL("COPY {} ({}) FROM STDIN").format(table, names)) as copy,
    ):
        for row in layer.frame.select(*attributes, "wkt").iter_rows():
            copy.write_row(row)
    geometry = sql.SQL(f"geometry({layer.geometry}, 4326)")
    conn.execute(sql.SQL("ALTER TABLE {} ADD COLUMN geom {}").format(table, geometry))
    conn.execute(sql.SQL("UPDATE {} SET geom = ST_GeomFromText(wkt, 4326)").format(table))
    conn.execute(sql.SQL("ALTER TABLE {} DROP COLUMN wkt").format(table))
    conn.execute(sql.SQL("CREATE INDEX ON {} USING gist (geom)").format(table))
    return layer.frame.height
