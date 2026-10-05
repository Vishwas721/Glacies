"""Stream walkable OSM ways out of a PBF/XML file as flat segment arrays.

The file is read once with pyosmium; nothing city-sized is held as Python objects except
compact typed arrays of segment endpoints.
"""

from __future__ import annotations

from array import array
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import osmium
import polars as pl

from glacies.cities import Walk

Bbox = tuple[float, float, float, float]


@dataclass
class ExtractStats:
    ways_kept: Counter[str] = field(default_factory=Counter)  # by highway
    ways_excluded: Counter[str] = field(default_factory=Counter)  # by reason
    segments_outside_bbox: int = 0
    segments_missing_location: int = 0


def _exclusion(tags: osmium.osm.TagList, walk: Walk) -> str | None:
    highway = tags.get("highway")
    if highway not in walk.highways:
        return f"highway={highway}"
    foot = tags.get("foot")
    if foot in walk.exclude_foot:
        return f"foot={foot}"
    access = tags.get("access")
    if access in walk.exclude_access and foot not in walk.allow_foot:
        return f"access={access}"
    return None


def extract_walk_segments(path: Path, bbox: Bbox, walk: Walk) -> tuple[pl.DataFrame, ExtractStats]:
    """Return one row per consecutive node pair of every walkable way, both ends inside bbox."""
    min_lon, min_lat, max_lon, max_lat = bbox

    def inside(lon: float, lat: float) -> bool:
        return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat

    stats = ExtractStats()
    way_id, position = array("q"), array("I")
    from_ref, to_ref = array("q"), array("q")
    from_lon, from_lat, to_lon, to_lat = array("d"), array("d"), array("d"), array("d")
    highways: list[str] = []

    processor = (
        osmium.FileProcessor(str(path))
        .with_locations()
        .with_filter(osmium.filter.KeyFilter("highway"))
    )
    for obj in processor:
        if not isinstance(obj, osmium.osm.Way):
            continue
        nodes = [
            (n.ref, n.location.lon, n.location.lat) if n.location.valid() else (n.ref, None, None)
            for n in obj.nodes
        ]
        touches_bbox = any(
            lon is not None and lat is not None and inside(lon, lat) for _, lon, lat in nodes
        )
        if not touches_bbox:
            continue
        reason = _exclusion(obj.tags, walk)
        if reason is not None:
            stats.ways_excluded[reason] += 1
            continue
        highway = obj.tags.get("highway") or ""
        stats.ways_kept[highway] += 1
        for i, ((ref_a, lon_a, lat_a), (ref_b, lon_b, lat_b)) in enumerate(pairwise(nodes)):
            if lon_a is None or lat_a is None or lon_b is None or lat_b is None:
                stats.segments_missing_location += 1
                continue
            if ref_a == ref_b:
                continue
            if not (inside(lon_a, lat_a) and inside(lon_b, lat_b)):
                stats.segments_outside_bbox += 1
                continue
            way_id.append(obj.id)
            position.append(i)
            from_ref.append(ref_a)
            to_ref.append(ref_b)
            from_lon.append(lon_a)
            from_lat.append(lat_a)
            to_lon.append(lon_b)
            to_lat.append(lat_b)
            highways.append(highway)

    segments = pl.DataFrame(
        {
            "osm_way_id": pl.Series(way_id, dtype=pl.Int64),
            "position": pl.Series(position, dtype=pl.UInt32),
            "from_osm_node": pl.Series(from_ref, dtype=pl.Int64),
            "to_osm_node": pl.Series(to_ref, dtype=pl.Int64),
            "from_lon": pl.Series(from_lon, dtype=pl.Float64),
            "from_lat": pl.Series(from_lat, dtype=pl.Float64),
            "to_lon": pl.Series(to_lon, dtype=pl.Float64),
            "to_lat": pl.Series(to_lat, dtype=pl.Float64),
            "highway": pl.Series(highways, dtype=pl.String),
        }
    ).sort("osm_way_id", "position")
    return segments, stats
