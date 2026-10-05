"""Keep PROJ/GDAL data from other installations out of this process.

System-wide PROJ_DATA / PROJ_LIB / GDAL_DATA (e.g. left by another Python or a PostgreSQL
install) override the data bundled with the pyproj and rasterio wheels and can be incompatible
("proj.db ... DATABASE.LAYOUT.VERSION.MINOR"). Variables pointing outside the active
environment are dropped for this process only, so the bundled data is used.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_VARIABLES = ("PROJ_DATA", "PROJ_LIB", "GDAL_DATA")


def isolate_geo_data(environ: dict[str, str] | None = None, prefix: str = sys.prefix) -> list[str]:
    """Remove geo-data variables not under ``prefix``; return the names removed."""
    env = os.environ if environ is None else environ
    root = Path(prefix).resolve()
    removed = []
    for name in _VARIABLES:
        value = env.get(name)
        if value and not Path(value).resolve().is_relative_to(root):
            del env[name]
            removed.append(name)
    return removed
