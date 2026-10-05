"""Walk segments -> node/edge tables, connected components, and stops snapped onto edges."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl
import shapely
from pyproj import Transformer
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from glacies.cities import Walk
from glacies.validate.gtfs.common import haversine_m

SCHEMAS: dict[str, dict[str, pl.DataType]] = {
    "nodes": {
        "node_idx": pl.UInt32(),
        "osm_node_id": pl.Int64(),
        "lat": pl.Float64(),
        "lon": pl.Float64(),
        "component": pl.UInt32(),  # 0 is the largest connected component
    },
    "edges": {
        "edge_idx": pl.UInt32(),
        "from_node": pl.UInt32(),  # walking is bidirectional; from < to by node_idx
        "to_node": pl.UInt32(),
        "length_m": pl.Float64(),
        "osm_way_id": pl.Int64(),
        "highway": pl.String(),
    },
    "stop_links": {
        "stop_idx": pl.UInt32(),  # boarding points from the canonical transit network
        "edge_idx": pl.UInt32(),
        "fraction": pl.Float64(),  # position along the edge from from_node, 0..1
        "snap_lat": pl.Float64(),
        "snap_lon": pl.Float64(),
        "distance_m": pl.Float64(),  # stop to snapped point, straight line
        "flagged": pl.Boolean(),  # distance_m above walk.max_snap_m
    },
}
TABLES = tuple(SCHEMAS)


@dataclass
class WalkBuild:
    tables: dict[str, pl.DataFrame]
    stats: dict[str, int | float] = field(default_factory=dict)


def _conform(name: str, frame: pl.DataFrame) -> pl.DataFrame:
    return frame.select(pl.col(c).cast(t) for c, t in SCHEMAS[name].items())


def build_walk(
    segments: pl.DataFrame, stops: pl.DataFrame, walk: Walk, crs_projected: str
) -> WalkBuild:
    """``stops`` needs ``stop_idx``, ``lat``, ``lon`` for the boarding points to snap."""
    endpoints = pl.concat(
        [
            segments.select(
                pl.col("from_osm_node").alias("osm_node_id"),
                pl.col("from_lat").alias("lat"),
                pl.col("from_lon").alias("lon"),
            ),
            segments.select(
                pl.col("to_osm_node").alias("osm_node_id"),
                pl.col("to_lat").alias("lat"),
                pl.col("to_lon").alias("lon"),
            ),
        ]
    )
    nodes = endpoints.unique("osm_node_id").sort("osm_node_id").with_row_index("node_idx")
    ids = nodes.select("osm_node_id", "node_idx")

    edges = (
        segments.join(
            ids.rename({"osm_node_id": "from_osm_node", "node_idx": "_a"}), on="from_osm_node"
        )
        .join(ids.rename({"osm_node_id": "to_osm_node", "node_idx": "_b"}), on="to_osm_node")
        .with_columns(
            pl.min_horizontal("_a", "_b").alias("from_node"),
            pl.max_horizontal("_a", "_b").alias("to_node"),
            haversine_m(
                pl.col("from_lat"), pl.col("from_lon"), pl.col("to_lat"), pl.col("to_lon")
            ).alias("length_m"),
        )
        .sort("osm_way_id", "position")
    )
    before_dedup = edges.height
    # Overlapping ways can repeat a node pair; keep the first by way id.
    edges = (
        edges.unique(["from_node", "to_node"], keep="first", maintain_order=True)
        .sort("from_node", "to_node")
        .with_row_index("edge_idx")
    )

    component = _components(nodes.height, edges)
    nodes = nodes.with_columns(pl.Series("component", component, dtype=pl.UInt32))
    links = _snap(nodes, edges, stops, walk, crs_projected)

    largest = int((component == 0).sum()) if component.size else 0
    distances = links["distance_m"]
    stats: dict[str, int | float] = {
        "segments": segments.height,
        "duplicate_segments": before_dedup - edges.height,
        "nodes": nodes.height,
        "edges": edges.height,
        "network_length_km": round(float(edges["length_m"].sum()) / 1000, 1),
        "components": int(component.max()) + 1 if component.size else 0,
        "largest_component_nodes": largest,
        "largest_component_share": round(largest / nodes.height, 4) if nodes.height else 0.0,
        "stops_snapped": links.height,
        "stops_flagged": int(links["flagged"].sum()),
    }
    if links.height:
        for q in (0.5, 0.9, 0.99):
            stats[f"snap_p{int(q * 100)}_m"] = round(
                float(distances.quantile(q, "nearest") or 0), 1
            )
        stats["snap_max_m"] = round(float(distances.max() or 0), 1)  # type: ignore[arg-type]
    return WalkBuild(
        tables={
            "nodes": _conform("nodes", nodes),
            "edges": _conform("edges", edges),
            "stop_links": _conform("stop_links", links),
        },
        stats=stats,
    )


def _components(n_nodes: int, edges: pl.DataFrame) -> np.ndarray:
    """Component label per node, renumbered so 0 is the largest (ties: lowest node index)."""
    if n_nodes == 0:
        return np.zeros(0, dtype=np.int64)
    a = edges["from_node"].to_numpy()
    b = edges["to_node"].to_numpy()
    graph = coo_matrix((np.ones(a.size, dtype=np.int8), (a, b)), shape=(n_nodes, n_nodes))
    _, labels = connected_components(graph, directed=False)
    sizes = np.bincount(labels)
    first_node = np.full(sizes.size, n_nodes, dtype=np.int64)
    np.minimum.at(first_node, labels, np.arange(n_nodes))
    order = np.lexsort((first_node, -sizes))  # biggest first, then earliest node
    rank = np.empty_like(order)
    rank[order] = np.arange(order.size)
    return rank[labels].astype(np.int64)


def _snap(
    nodes: pl.DataFrame,
    edges: pl.DataFrame,
    stops: pl.DataFrame,
    walk: Walk,
    crs_projected: str,
) -> pl.DataFrame:
    stops = stops.select("stop_idx", "lat", "lon").drop_nulls().sort("stop_idx")
    if stops.is_empty() or edges.is_empty():
        return pl.DataFrame(schema=SCHEMAS["stop_links"])

    candidates = edges
    if walk.snap_to_largest_component:
        main = nodes.filter(pl.col("component") == 0)["node_idx"].implode()
        candidates = edges.filter(pl.col("from_node").is_in(main))

    to_xy = Transformer.from_crs("EPSG:4326", crs_projected, always_xy=True)
    to_lonlat = Transformer.from_crs(crs_projected, "EPSG:4326", always_xy=True)
    node_x, node_y = to_xy.transform(nodes["lon"].to_numpy(), nodes["lat"].to_numpy())
    a = candidates["from_node"].to_numpy()
    b = candidates["to_node"].to_numpy()
    coords = np.stack(
        [np.column_stack([node_x[a], node_y[a]]), np.column_stack([node_x[b], node_y[b]])], axis=1
    )
    # Arrays of geometries (not per-edge Python objects in our own structures).
    lines = np.asarray(shapely.linestrings(coords), dtype=object)
    stop_x, stop_y = to_xy.transform(stops["lon"].to_numpy(), stops["lat"].to_numpy())
    points = np.asarray(shapely.points(stop_x, stop_y), dtype=object)

    tree = shapely.STRtree(lines)
    (point_i, line_i), distance = tree.query_nearest(points, return_distance=True, all_matches=True)
    # all_matches returns every equidistant edge; keep the lowest edge index for determinism.
    matches = (
        pl.DataFrame(
            {
                "_p": point_i,
                "_l": line_i,
                "_edge": candidates["edge_idx"].to_numpy()[line_i],
                "distance_m": distance,
            }
        )
        .sort("_p", "_edge")
        .unique("_p", keep="first", maintain_order=True)
    )
    p = matches["_p"].to_numpy()
    chosen = lines[matches["_l"].to_numpy()]
    fraction = shapely.line_locate_point(chosen, points[p], normalized=True)
    snapped = shapely.line_interpolate_point(chosen, fraction, normalized=True)
    snap_lon, snap_lat = to_lonlat.transform(shapely.get_x(snapped), shapely.get_y(snapped))
    return pl.DataFrame(
        {
            "stop_idx": stops["stop_idx"].to_numpy()[p],
            "edge_idx": matches["_edge"],
            "fraction": fraction,
            "snap_lat": snap_lat,
            "snap_lon": snap_lon,
            "distance_m": matches["distance_m"],
        }
    ).with_columns((pl.col("distance_m") > walk.max_snap_m).alias("flagged"))
