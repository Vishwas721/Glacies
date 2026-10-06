"""Load the canonical transit and walk networks into the Rust router (Phase 2 M7).

Inputs are the Phase 1 outputs in ``data/processed/<city>/{transit,walk}``. Transfers between
stops are the shortest walks on the pedestrian network up to ``routing.max_transfer_walk_m``;
journeys and travel times produced here are Simulated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import glacies_raptor as gr
import numpy as np
import numpy.typing as npt
import polars as pl
from pyproj import Transformer
from scipy.spatial import cKDTree

from glacies.cities import Routing

U32 = npt.NDArray[np.uint32]


class RouterError(ValueError):
    """The router cannot be built or cannot answer a query."""


def walk_seconds(metres: npt.NDArray[np.float64], speed_m_s: float) -> U32:
    """Whole seconds needed to walk ``metres`` (rounded up, so walks are never too short)."""
    return np.ceil(metres / speed_m_s).astype(np.uint32)


@dataclass(frozen=True)
class Access:
    """Stops reachable on foot from a point, with walking seconds."""

    stops: U32
    seconds: U32
    snap_m: float  # point to the walk network (straight line)


@dataclass
class Router:
    timetable: gr.Timetable
    walk: gr.WalkGraph
    routing: Routing
    stops: pl.DataFrame
    routes: pl.DataFrame
    trips: pl.DataFrame
    transfer_count: int
    _tree: cKDTree
    _node_edge: U32
    _node_fraction: npt.NDArray[np.float64]
    _to_xy: Transformer

    # --- points ---------------------------------------------------------------------------

    def access(self, lat: float, lon: float, max_m: float | None = None) -> Access:
        """Stops within ``max_m`` (default: max access walk) of a point, via the walk network."""
        limit = self.routing.max_access_walk_m if max_m is None else max_m
        x, y = self._to_xy.transform(lon, lat)
        snap_m, nearest = self._tree.query([x, y])
        node = int(nearest)
        stops, metres = self.walk.stops_within(
            int(self._node_edge[node]), float(self._node_fraction[node]), float(snap_m), limit
        )
        return Access(stops, walk_seconds(metres, self.routing.walking_speed_m_s), float(snap_m))

    def plan(
        self, origin: tuple[float, float], destination: tuple[float, float], departure: int
    ) -> list[gr.Journey]:
        """Pareto-optimal journeys between two (lat, lon) points leaving at ``departure``."""
        start, end = self.access(*origin), self.access(*destination)
        if start.stops.size == 0:
            raise RouterError(f"no stop within {self.routing.max_access_walk_m:g} m of {origin}")
        if end.stops.size == 0:
            raise RouterError(
                f"no stop within {self.routing.max_access_walk_m:g} m of {destination}"
            )
        return self.timetable.plan(
            start.stops,
            start.seconds,
            departure,
            end.stops,
            end.seconds,
            self.routing.max_rounds,
            self.routing.min_transfer_time_s,
        )

    # --- presentation ---------------------------------------------------------------------

    def describe(self, journey: gr.Journey) -> list[str]:
        """One human-readable line per leg."""
        names = dict(self.stops.select("stop_idx", "name").iter_rows())
        trip_route = dict(self.trips.select("trip_idx", "route_idx").iter_rows())
        route_name = dict(
            self.routes.select("route_idx", pl.col("route_number").fill_null("?")).iter_rows()
        )
        lines = []
        for leg in journey.legs:
            minutes = math.ceil(leg.duration / 60)
            if leg.kind == "ride":
                if leg.trip_id is None or leg.board is None or leg.alight is None:
                    raise RouterError(f"incomplete ride leg {leg!r}")
                route = route_name[trip_route[leg.trip_id]]
                lines.append(
                    f"{clock(leg.board)} ride {route} from {names[leg.from_stop]} "
                    f"to {names[leg.to_stop]}, arrive {clock(leg.alight)}"
                )
            elif leg.kind == "access":
                lines.append(f"walk {minutes} min to {names[leg.to_stop]}")
            elif leg.kind == "egress":
                lines.append(f"walk {minutes} min from {names[leg.from_stop]} to destination")
            else:
                lines.append(
                    f"walk {minutes} min from {names[leg.from_stop]} to {names[leg.to_stop]}"
                )
        return lines


def clock(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def parse_clock(text: str) -> int:
    """``HH:MM`` or ``HH:MM:SS`` (hours may exceed 24) to seconds since midnight."""
    parts = text.split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        raise RouterError(f"invalid time {text!r}; use HH:MM")
    h, m, s = (int(p) for p in [*parts, "0"][:3])
    if m >= 60 or s >= 60:
        raise RouterError(f"invalid time {text!r}")
    return h * 3600 + m * 60 + s


def _timetable(transit: Path, footpaths: tuple[U32, U32, U32]) -> gr.Timetable:
    stop_count = pl.read_parquet(transit / "stops.parquet", columns=["stop_idx"]).height
    stop_times = pl.read_parquet(transit / "stop_times.parquet").sort("trip_idx", "position")
    sizes = stop_times.group_by("trip_idx", maintain_order=True).len()
    starts = np.zeros(sizes.height + 1, dtype=np.uint32)
    np.cumsum(sizes["len"].to_numpy(), out=starts[1:])
    return gr.Timetable.build(
        stop_count,
        sizes["trip_idx"].to_numpy().astype(np.uint32),
        starts,
        stop_times["stop_idx"].to_numpy().astype(np.uint32),
        stop_times["arrival"].to_numpy().astype(np.uint32),
        stop_times["departure"].to_numpy().astype(np.uint32),
        *footpaths,
    )


def load_router(city_dir: Path, routing: Routing, crs_projected: str) -> Router:
    """Build the router from ``data/processed/<city>``."""
    transit, walk_dir = city_dir / "transit", city_dir / "walk"
    for needed in (transit / "stop_times.parquet", walk_dir / "edges.parquet"):
        if not needed.is_file():
            raise RouterError(f"missing {needed}; run `glacies build-city` first")

    nodes = pl.read_parquet(walk_dir / "nodes.parquet")
    edges = pl.read_parquet(walk_dir / "edges.parquet")
    links = pl.read_parquet(walk_dir / "stop_links.parquet")
    walk = gr.WalkGraph(
        nodes.height,
        edges["from_node"].to_numpy().astype(np.uint32),
        edges["to_node"].to_numpy().astype(np.uint32),
        edges["length_m"].to_numpy().astype(np.float64),
    )
    walk.attach_stops(
        links["stop_idx"].to_numpy().astype(np.uint32),
        links["edge_idx"].to_numpy().astype(np.uint32),
        links["fraction"].to_numpy().astype(np.float64),
        links["distance_m"].to_numpy().astype(np.float64),
    )
    pair_from, pair_to, metres = walk.stop_to_stop(routing.max_transfer_walk_m)
    footpaths = (pair_from, pair_to, walk_seconds(metres, routing.walking_speed_m_s))
    timetable = _timetable(transit, footpaths)

    # Points attach to the nearest node of the main walk component; OSM nodes are dense
    # (tens of metres apart), so this costs a few metres at most.
    main = nodes.filter(pl.col("component") == 0)
    to_xy = Transformer.from_crs("EPSG:4326", crs_projected, always_xy=True)
    x, y = to_xy.transform(main["lon"].to_numpy(), main["lat"].to_numpy())
    incident = (
        pl.concat(
            [
                edges.select(pl.col("from_node").alias("node"), "edge_idx", pl.lit(0.0).alias("f")),
                edges.select(pl.col("to_node").alias("node"), "edge_idx", pl.lit(1.0).alias("f")),
            ]
        )
        .sort("node", "edge_idx")
        .unique("node", keep="first", maintain_order=True)
    )
    attach = main.select(pl.col("node_idx").alias("node")).join(
        incident, on="node", how="left", maintain_order="left"
    )
    return Router(
        timetable=timetable,
        walk=walk,
        routing=routing,
        stops=pl.read_parquet(transit / "stops.parquet"),
        routes=pl.read_parquet(transit / "routes.parquet"),
        trips=pl.read_parquet(transit / "trips.parquet", columns=["trip_idx", "route_idx"]),
        transfer_count=int(pair_from.size),
        _tree=cKDTree(np.column_stack([x, y])),
        _node_edge=attach["edge_idx"].to_numpy().astype(np.uint32),
        _node_fraction=attach["f"].to_numpy().astype(np.float64),
        _to_xy=to_xy,
    )
