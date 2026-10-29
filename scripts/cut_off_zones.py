"""Zones whose point reaches no stop within the access walk although one is close by (QGIS).

Each zone joins the network at one point (population-weighted, else the cell centre;
``glacies.analytics.travel_times.zone_points``). Where that point sits behind a barrier in the
walk network (a railway, a lake, a gated layout, or a gap in OpenStreetMap), the zone reaches no
stop within the access walk even with stops a few hundred metres away in a straight line. This
lists those zones for a check in QGIS (docs/validation/travel-time-matrix.md, "Cut-off zones").

    uv run python scripts/cut_off_zones.py [--city bengaluru] [--within-m 400]

Writes ``data/processed/<city>/reports/cut_off_zones.geoparquet`` (one hexagon per zone),
``cut_off_zones_links.geoparquet`` (a straight line from the zone's point to its nearest stop)
and ``cut_off_zones.csv``. Population is Estimated; distances follow the walk network (Simulated).
"""

from __future__ import annotations

import argparse

import numpy as np
import polars as pl
from scipy.spatial import cKDTree
from shapely.geometry import LineString

from glacies.analytics.report import write_geometries, write_geoparquet
from glacies.analytics.travel_times import zone_access, zone_points
from glacies.cities import load_city
from glacies.config import get_settings
from glacies.routing.network import load_router

SEARCH_M = 5_000.0  # how far to follow the walk network to find the nearest stop


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city", default=None, help="city id (default: GLACIES_CITY)")
    parser.add_argument("--within-m", type=float, default=400.0, help="straight-line limit")
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


if __name__ == "__main__":
    main()
