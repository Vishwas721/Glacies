"""Zonal statistics for WorldPop (population) and WorldCover (land-cover shares).

Each pixel belongs to the zone containing its centre, so totals are conserved exactly. Rasters
are read in horizontal strips to keep memory bounded.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import numpy.typing as npt
import polars as pl
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine
from rasterio.windows import Window

from glacies.model.zones.grid import polygon

Bbox = tuple[float, float, float, float]
_STRIP_ROWS = 1024

# ESA WorldCover v200 class codes.
LANDCOVER_CLASSES: dict[int, str] = {
    10: "tree",
    20: "shrub",
    30: "grass",
    40: "cropland",
    50: "built",
    60: "bare",
    70: "snow",
    80: "water",
    90: "wetland",
    95: "mangrove",
    100: "moss",
}


def _strips(
    path: str, zones: pl.DataFrame
) -> Iterator[tuple[npt.NDArray[np.int32], npt.NDArray[np.generic], float | None, Affine]]:
    """Yield (zone label per pixel, pixel values, nodata, strip transform) for each strip."""
    shapes = [(polygon(c), i + 1) for i, c in enumerate(zones["h3_cell"])]
    lons = [x for g, _ in shapes for x, _ in g["coordinates"][0]]
    lats = [y for g, _ in shapes for _, y in g["coordinates"][0]]
    with rasterio.open(path) as src:
        row0, col0 = src.index(min(lons), max(lats))
        row1, col1 = src.index(max(lons), min(lats))
        row0, col0 = max(row0, 0), max(col0, 0)
        row1, col1 = min(row1, src.height - 1), min(col1, src.width - 1)
        width = col1 - col0 + 1
        for top in range(row0, row1 + 1, _STRIP_ROWS):
            height = min(_STRIP_ROWS, row1 + 1 - top)
            window = Window(col0, top, width, height)
            values = src.read(1, window=window)
            transform = src.window_transform(window)
            labels = rasterize(
                shapes,
                out_shape=values.shape,
                transform=transform,
                fill=0,
                all_touched=False,
                dtype="int32",
            )
            yield labels, values, src.nodata, transform


def population_by_zone(
    path: str, zones: pl.DataFrame, bbox: Bbox
) -> tuple[pl.Series, dict[str, float]]:
    """Population per zone, plus totals used to check that nothing is lost or double-counted."""
    n = zones.height
    min_lon, min_lat, max_lon, max_lat = bbox
    sums = np.zeros(n + 1, dtype=np.float64)
    total_read = in_bbox = 0.0
    for labels, values, nodata, transform in _strips(path, zones):
        data = values.astype(np.float64)
        if nodata is not None:
            data[values == nodata] = 0.0
        data[~np.isfinite(data) | (data < 0)] = 0.0
        sums += np.bincount(labels.ravel(), weights=data.ravel(), minlength=n + 1)
        total_read += float(data.sum())
        rows, cols = data.shape
        xs = transform.c + (np.arange(cols) + 0.5) * transform.a
        ys = transform.f + (np.arange(rows) + 0.5) * transform.e
        inside = np.outer((ys >= min_lat) & (ys <= max_lat), (xs >= min_lon) & (xs <= max_lon))
        in_bbox += float(data[inside].sum())
    population = pl.Series("population", sums[1:])
    stats = {
        "population_zones": round(float(sums[1:].sum()), 1),
        "population_bbox": round(in_bbox, 1),
        "population_raster_window": round(total_read, 1),
        "population_outside_zones": round(float(sums[0]), 1),
    }
    return population, stats


def landcover_by_zone(path: str, zones: pl.DataFrame) -> pl.DataFrame:
    n = zones.height
    codes = np.array(sorted(LANDCOVER_CLASSES), dtype=np.int64)
    counts = np.zeros((n + 1, 256), dtype=np.int64)
    for labels, values, _, _ in _strips(path, zones):
        key = labels.astype(np.int64) * 256 + values.astype(np.int64)
        counts += np.bincount(key.ravel(), minlength=(n + 1) * 256).reshape(n + 1, 256)
    per_zone = counts[1:]
    valid = per_zone[:, codes].sum(axis=1)
    shares = np.divide(
        per_zone[:, codes], valid[:, None], out=np.zeros((n, codes.size)), where=valid[:, None] > 0
    )
    return pl.DataFrame(
        {f"landcover_{LANDCOVER_CLASSES[int(code)]}": shares[:, j] for j, code in enumerate(codes)}
    )
