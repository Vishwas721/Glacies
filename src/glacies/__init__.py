"""Glacies — urban transit digital twin and scenario simulation platform."""

from glacies._geoenv import isolate_geo_data

__version__ = "0.1.0"

# Must run before pyproj/rasterio load their data files.
isolate_geo_data()
