"""Synthetic WorldPop/WorldCover rasters and an Open Buildings CSV for Toyville tests."""

from pathlib import Path

import numpy as np
import polars as pl
import rasterio
from rasterio.transform import from_origin

HOT = (12.0504, 77.0504)  # (lat, lon) of the 1000-person pixel
NODATA_AT = (12.06, 77.06)  # top-left of a 2x2 nodata block
POP_RES = 1 / 1200  # WorldPop 100 m grid
LC_RES = 1 / 12000  # WorldCover 10 m grid
EXTENT = (76.99, 12.11)  # raster top-left (lon, lat); rasters cover the bbox plus 0.01 deg


def _write_raster(path: Path, data: np.ndarray, res: float, nodata: float) -> None:
    with rasterio.open(
        path, "w", driver="GTiff", height=data.shape[0], width=data.shape[1], count=1,
        dtype=data.dtype, crs="EPSG:4326", transform=from_origin(*EXTENT, res, res), nodata=nodata,
    ) as dst:  # fmt: skip
        dst.write(data, 1)


def _pixel(lat: float, lon: float, res: float) -> tuple[int, int]:
    return int((EXTENT[1] - lat) / res), int((lon - EXTENT[0]) / res)


def write_population(path: Path) -> Path:
    """One person per pixel, a 1000-person pixel at HOT and a nodata block at NODATA_AT."""
    size = round(0.12 / POP_RES)
    data = np.ones((size, size), dtype=np.float32)
    row, col = _pixel(*NODATA_AT, POP_RES)
    data[row : row + 2, col : col + 2] = -99999.0
    data[_pixel(*HOT, POP_RES)] = 1000.0
    _write_raster(path, data, POP_RES, -99999.0)
    return path


def write_landcover(path: Path) -> Path:
    """Built-up (50) west of lon 77.05, cropland (40) east of it."""
    size = round(0.12 / LC_RES)
    data = np.full((size, size), 40, dtype=np.uint8)
    data[:, : round((77.05 - EXTENT[0]) / LC_RES)] = 50
    _write_raster(path, data, LC_RES, 0)
    return path


def write_buildings(path: Path) -> Path:
    """Two buildings in one zone (confidence 0.70 and 0.80), one elsewhere, one outside."""
    pl.DataFrame(
        {
            "latitude": [12.0500, 12.0501, 12.0800, 12.5000],
            "longitude": [77.0200, 77.0201, 77.0800, 77.5000],
            "area_in_meters": [100.0, 50.0, 30.0, 10.0],
            "confidence": [0.70, 0.80, 0.90, 0.90],
            "geometry": ["POLYGON EMPTY"] * 4,
        }
    ).write_csv(path, compression="gzip")
    return path
