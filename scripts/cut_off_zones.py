"""Zones whose point reaches no stop within the access walk although one is close by (QGIS).

Each zone joins the network at one point (population-weighted, else the cell centre;
``glacies.analytics.travel_times.zone_points``). Where that point sits behind a barrier in the
walk network (a railway, a lake, a gated layout, or a gap in OpenStreetMap), the zone reaches no
stop within the access walk even with stops a few hundred metres away in a straight line. This
lists those zones for a check in QGIS (docs/validation/travel-time-matrix.md, "Cut-off zones").

    uv run python scripts/cut_off_zones.py [--city bengaluru] [--within-m 400] [--barriers]

Writes ``data/processed/<city>/reports/cut_off_zones.geoparquet`` (one hexagon per zone),
``cut_off_zones_links.geoparquet`` (a straight line from the zone's point to its nearest stop)
and ``cut_off_zones.csv``. Population is Estimated; distances follow the walk network (Simulated).

``--barriers`` reads the archived OpenStreetMap file (a few minutes) and says what the map shows
on each straight line: a railway, water, a motorway or trunk road, a wall or fence; else whether
the point sits among private roads the walk network leaves out (a gated layout); else none:
a winding street layout, or a path missing from the map. Bridges and tunnels are not barriers.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import osmium
import polars as pl
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import transform

from glacies.analytics.report import write_geometries, write_geoparquet
from glacies.analytics.travel_times import zone_access, zone_points
from glacies.cities import load_city
from glacies.config import get_settings
from glacies.pipeline import single_file_snapshot, source_of_kind
from glacies.routing.network import load_router

SEARCH_M = 5_000.0  # how far to follow the walk network to find the nearest stop
PRIVATE_NEAR_M = 150.0  # private roads this close to a zone's point suggest a gated layout,
PRIVATE_MIN_M = 100.0  # if at least this much of them is mapped there
RAILWAYS = {"rail", "narrow_gauge"}  # light rail and metro run on viaducts or underground
WATERWAYS = {"river", "canal", "stream", "drain"}
FAST_ROADS = {"motorway", "trunk"}
WALLS = {"wall", "fence", "city_wall"}
ORDER = ["railway", "water", "motorway or trunk road", "wall or fence"]


def barrier_kind(tags: osmium.osm.TagList) -> str | None:
    """What a way blocks walking as, or None; people pass under a bridge or over a tunnel."""
    if tags.get("bridge") not in (None, "no") or tags.get("tunnel") not in (None, "no"):
        return None
    if tags.get("railway") in RAILWAYS:
        return "railway"
    if tags.get("waterway") in WATERWAYS or tags.get("natural") == "water":
        return "water"
    if tags.get("highway") in FAST_ROADS:
        return "motorway or trunk road"
    if tags.get("barrier") in WALLS:
        return "wall or fence"
    return None


def is_private_road(tags: osmium.osm.TagList) -> bool:
    private = ("private", "no")
    return tags.get("highway") is not None and (
        tags.get("access") in private or tags.get("foot") in private
    )


def classify_barriers(osm_file: Path, table: pl.DataFrame, crs: str) -> pl.DataFrame:
    """Add ``barrier`` (what the map shows between point and stop) and ``private_road_m``."""
    to_xy = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    ends = table.select("point_lon", "point_lat", "nearest_stop_lon", "nearest_stop_lat")
    links = [transform(to_xy, LineString([(a, b), (c, d)])) for a, b, c, d in ends.iter_rows()]
    around = [Point(line.coords[0]).buffer(PRIVATE_NEAR_M) for line in links]
    link_tree, around_tree = STRtree(links), STRtree(around)
    lon = ends["point_lon"].to_list() + ends["nearest_stop_lon"].to_list()
    lat = ends["point_lat"].to_list() + ends["nearest_stop_lat"].to_list()
    pad = 0.02  # degrees: keep ways that pass near the links, not only those that end there
    box = (min(lon) - pad, min(lat) - pad, max(lon) + pad, max(lat) + pad)

    crossed: list[set[str]] = [set() for _ in links]
    private_m = [0.0] * len(links)
    keys = osmium.filter.KeyFilter("railway", "waterway", "natural", "highway", "barrier")
    for obj in osmium.FileProcessor(str(osm_file)).with_locations().with_filter(keys):
        if not isinstance(obj, osmium.osm.Way):
            continue
        kind = barrier_kind(obj.tags)
        if kind is None and not is_private_road(obj.tags):
            continue
        coords = [(n.location.lon, n.location.lat) for n in obj.nodes if n.location.valid()]
        inside = any(box[0] <= x <= box[2] and box[1] <= y <= box[3] for x, y in coords)
        if len(coords) < 2 or not inside:
            continue
        way = transform(to_xy, LineString(coords))
        if kind is not None:
            for i in link_tree.query(way, predicate="intersects"):
                crossed[int(i)].add(kind)
        else:
            for i in around_tree.query(way, predicate="intersects"):
                private_m[int(i)] += way.intersection(around[int(i)]).length

    barriers = []
    for kinds, metres in zip(crossed, private_m, strict=True):
        if kinds:
            barriers.append(", ".join(k for k in ORDER if k in kinds))
        elif metres >= PRIVATE_MIN_M:
            barriers.append("private roads (gated layout?)")
        else:
            barriers.append("no barrier mapped (detour or map gap)")
    return table.with_columns(
        pl.Series("barrier", barriers),
        pl.Series("private_road_m", [round(m) for m in private_m]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city", default=None, help="city id (default: GLACIES_CITY)")
    parser.add_argument("--within-m", type=float, default=400.0, help="straight-line limit")
    parser.add_argument("--barriers", action="store_true", help="classify them from OSM")
    args = parser.parse_args()

    settings = get_settings()
    if args.city:
        settings = settings.model_copy(update={"city": args.city})
    config = load_city(settings.city_config_path)
    base = settings.processed_dir / config.city.id
    out = base / "reports"
    out.mkdir(parents=True, exist_ok=True)

    zones = pl.read_parquet(base / "zones" / "zones.parquet").sort("zone_idx")
    points = zone_points(zones)
    router = load_router(base, config.routing, config.city.crs_projected)
    reaches_none = np.array([stops.size == 0 for stops, _ in zone_access(router, points)])

    # Straight-line distance to the nearest stop (platforms and street stops, not stations).
    stops = router.stops.filter(pl.col("location_type") == 0)
    scale = np.array([111_320.0, 111_320.0 * np.cos(np.radians(points["lat"].mean()))])
    tree = cKDTree(stops.select("lat", "lon").to_numpy() * scale)
    straight_m, nearest = tree.query(points.select("lat", "lon").to_numpy() * scale)
    cut_off = reaches_none & (straight_m <= args.within_m)

    rows = []
    for i in map(int, np.flatnonzero(cut_off)):
        lat, lon = points["lat"][i], points["lon"][i]
        near = stops.row(int(nearest[i]), named=True)
        walks = router.access(lat, lon, max_m=SEARCH_M)
        walk_m = None
        if walks.stops.size:
            walk_m = float(walks.seconds.min()) * config.routing.walking_speed_m_s
        rows.append(
            {
                "h3_cell": zones["h3_cell"][i],
                "population": zones["population"][i],
                "point": points["point"][i],
                "point_lat": lat,
                "point_lon": lon,
                "nearest_stop": near["name"],
                "nearest_stop_lat": near["lat"],
                "nearest_stop_lon": near["lon"],
                "straight_m": round(float(straight_m[i])),
                "walk_to_any_stop_m": None if walk_m is None else round(walk_m),
            }
        )
    table = pl.DataFrame(rows).sort("population", descending=True, nulls_last=True)
    if args.barriers:
        _, osm_file = single_file_snapshot(settings, config, source_of_kind(config, "osm_pbf"))
        table = classify_barriers(osm_file, table, config.city.crs_projected)

    write_geoparquet(table, table["h3_cell"].to_list(), out / "cut_off_zones.geoparquet")
    links = [
        LineString(
            [(r["point_lon"], r["point_lat"]), (r["nearest_stop_lon"], r["nearest_stop_lat"])]
        )
        for r in table.iter_rows(named=True)
    ]
    write_geometries(table, links, "LineString", out / "cut_off_zones_links.geoparquet")
    table.write_csv(out / "cut_off_zones.csv")

    residents = zones["population"].fill_null(0).to_numpy()
    print(
        f"{config.city.id}: {int(reaches_none.sum()):,} of {zones.height:,} zones reach no stop "
        f"within the {config.routing.max_access_walk_m:g} m walk "
        f"({residents[reaches_none].sum():,.0f} residents, Estimated); "
        f"{table.height:,} of them have a stop within {args.within_m:g} m in a straight line "
        f"({residents[cut_off].sum():,.0f} residents) -> {out / 'cut_off_zones.geoparquet'}"
    )
    if args.barriers:
        summary = (
            table.group_by("barrier")
            .agg(pl.len().alias("zones"), pl.col("population").sum().round(0).alias("residents"))
            .sort("zones", descending=True)
        )
        print(summary)


if __name__ == "__main__":
    main()
