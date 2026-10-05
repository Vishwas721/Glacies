"""H3 zone grid over the study area."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import h3
import polars as pl

Bbox = tuple[float, float, float, float]


def make_zones(bbox: Bbox, resolution: int) -> pl.DataFrame:
    """Every H3 cell that overlaps the bbox, ordered by cell id (so zone_idx is stable)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    shape = h3.LatLngPoly(
        [(min_lat, min_lon), (min_lat, max_lon), (max_lat, max_lon), (max_lat, min_lon)]
    )
    cells = sorted(h3.h3shape_to_cells_experimental(shape, resolution, contain="overlap"))
    centres = [h3.cell_to_latlng(c) for c in cells]
    return pl.DataFrame(
        {
            "zone_idx": pl.Series(range(len(cells)), dtype=pl.UInt32),
            "h3_cell": cells,
            "lat": [lat for lat, _ in centres],
            "lon": [lon for _, lon in centres],
            "area_m2": [h3.cell_area(c, unit="m^2") for c in cells],
        }
    )


def polygon(cell: str) -> dict[str, Any]:
    """GeoJSON polygon (lon, lat) of an H3 cell, ring closed."""
    ring = [(lon, lat) for lat, lon in h3.cell_to_boundary(cell)]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def assign_points(
    zones: pl.DataFrame, lat: Iterable[float], lon: Iterable[float], resolution: int
) -> pl.Series:
    """zone_idx of each point (null when the point's cell is not a study-area zone)."""
    cells = pl.Series(
        "h3_cell",
        [h3.latlng_to_cell(y, x, resolution) for y, x in zip(lat, lon, strict=True)],
        dtype=pl.String,
    )
    lookup = zones.select("h3_cell", "zone_idx")
    return cells.to_frame().join(lookup, on="h3_cell", how="left", maintain_order="left")[
        "zone_idx"
    ]
