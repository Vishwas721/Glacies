"""OSM points of interest by category, for the employment proxy (Phase 3).

Categories and their tag rules are Assumed. Each feature gets exactly one category, using the
priority order of ``CATEGORIES``. Ways are placed at the mean of their nodes; multipolygon
relations are not read.
"""

from __future__ import annotations

from array import array
from collections import Counter
from pathlib import Path

import osmium
import polars as pl

Bbox = tuple[float, float, float, float]

CATEGORIES = (
    "office",
    "shop",
    "health",
    "education",
    "food",
    "craft",
    "industrial",
    "amenity_other",
)
_HEALTH = {"hospital", "clinic", "doctors", "dentist", "pharmacy"}
_EDUCATION = {"school", "college", "university", "kindergarten"}
_FOOD = {"restaurant", "cafe", "fast_food", "food_court", "bar", "pub", "ice_cream"}
# Street furniture and similar: not places where anyone works.
_NOT_A_PLACE = {
    "atm", "bench", "bicycle_parking", "clock", "drinking_water", "fountain",
    "motorcycle_parking", "parking", "parking_entrance", "parking_space", "post_box",
    "recycling", "shelter", "telephone", "toilets", "vending_machine", "waste_basket",
    "waste_disposal", "water_point",
}  # fmt: skip
_KEYS = ("office", "shop", "amenity", "craft", "healthcare", "landuse", "man_made")


def classify(tags: osmium.osm.TagList) -> str | None:
    amenity = tags.get("amenity")
    if "office" in tags:
        return "office"
    if "shop" in tags:
        return "shop"
    if "healthcare" in tags or amenity in _HEALTH:
        return "health"
    if amenity in _EDUCATION:
        return "education"
    if amenity in _FOOD:
        return "food"
    if "craft" in tags:
        return "craft"
    if tags.get("landuse") == "industrial" or tags.get("man_made") == "works":
        return "industrial"
    if amenity is not None and amenity not in _NOT_A_PLACE:
        return "amenity_other"
    return None


def extract_pois(path: Path, bbox: Bbox) -> tuple[pl.DataFrame, dict[str, int]]:
    min_lon, min_lat, max_lon, max_lat = bbox
    osm_type: list[str] = []
    osm_id, lat, lon = array("q"), array("d"), array("d")
    categories: list[str] = []
    skipped: Counter[str] = Counter()

    processor = (
        osmium.FileProcessor(str(path))
        .with_locations()
        .with_filter(osmium.filter.KeyFilter(*_KEYS))
    )
    for obj in processor:
        if isinstance(obj, osmium.osm.Node):
            if not obj.location.valid():
                continue
            point = (obj.location.lon, obj.location.lat)
            kind = "node"
        elif isinstance(obj, osmium.osm.Way):
            coords = [(n.location.lon, n.location.lat) for n in obj.nodes if n.location.valid()]
            if not coords:
                continue
            point = (
                sum(x for x, _ in coords) / len(coords),
                sum(y for _, y in coords) / len(coords),
            )
            kind = "way"
        else:
            skipped["relation"] += 1
            continue
        if not (min_lon <= point[0] <= max_lon and min_lat <= point[1] <= max_lat):
            continue
        category = classify(obj.tags)
        if category is None:
            skipped["not_a_place"] += 1
            continue
        osm_type.append(kind)
        osm_id.append(obj.id)
        lon.append(point[0])
        lat.append(point[1])
        categories.append(category)

    pois = pl.DataFrame(
        {
            "osm_type": osm_type,
            "osm_id": pl.Series(osm_id, dtype=pl.Int64),
            "category": pl.Series(categories, dtype=pl.String),
            "lat": pl.Series(lat, dtype=pl.Float64),
            "lon": pl.Series(lon, dtype=pl.Float64),
        }
    ).sort("osm_type", "osm_id")
    return pois, dict(sorted(skipped.items()))
