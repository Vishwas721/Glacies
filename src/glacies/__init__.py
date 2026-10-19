"""Glacies — urban transit digital twin and scenario simulation platform."""

import polars as pl

from glacies._geoenv import isolate_geo_data

__version__ = "0.1.0"

# Must run before pyproj/rasterio load their data files.
isolate_geo_data()

# Polars 2 runs lazy queries on the streaming engine by default, which does not keep row order
# through joins, so float sums in a group_by change in the last bits from run to run and
# outputs stop being byte-identical (CLAUDE.md rule 3). The in-memory engine keeps them stable.
pl.Config.set_engine_affinity("in-memory")
