"""Riding to a station at the home end of a trip (Phase 5 M7, ADR 0015).

Metro riders also reach stations by auto, two-wheeler and feeder bus, from well beyond the
access walk. Each zone gets a board-only ride to every platform of the calibration mode within
``max_km`` (straight line): ``penalty + distance x detour / speed``. Board-only means the ride
must be followed by a vehicle (``glacies_raptor``), so riding to a station and walking out is
never counted as transit. Platforms the zone can already walk to keep the walk.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import polars as pl

from glacies.cities import RideAccess
from glacies.validate.gtfs.common import haversine_m

U32 = npt.NDArray[np.uint32]


def ride_access(
    points: pl.DataFrame,
    platforms: pl.DataFrame,
    walks: list[tuple[U32, U32]],
    settings: RideAccess,
) -> list[tuple[U32, U32]]:
    """Per zone (``points`` row order, columns lat, lon): platforms and ride seconds.

    ``platforms`` has stop_idx, lat, lon; ``walks`` are the zones' access walks (stops,
    seconds). Rides are sorted by stop and rounded up to whole seconds.
    """
    zones = points.select(pl.int_range(pl.len(), dtype=pl.UInt32).alias("zone"), "lat", "lon")
    walked = pl.DataFrame(
        {
            "zone": np.repeat(
                np.arange(len(walks), dtype=np.uint32), [stops.size for stops, _ in walks]
            ),
            "stop_idx": np.concatenate([s for s, _ in walks] or [np.zeros(0, np.uint32)]).astype(
                np.uint32
            ),
        }
    )
    metres_per_second = settings.speed_kmh / 3.6
    rides = (
        zones.join(
            platforms.select(
                pl.col("stop_idx").cast(pl.UInt32),
                pl.col("lat").alias("stop_lat"),
                pl.col("lon").alias("stop_lon"),
            ),
            how="cross",
        )
        .with_columns(
            haversine_m(pl.col("lat"), pl.col("lon"), pl.col("stop_lat"), pl.col("stop_lon")).alias(
                "metres"
            )
        )
        .filter(pl.col("metres") <= settings.max_km * 1000)
        .join(walked, on=["zone", "stop_idx"], how="anti")
        .select(
            "zone",
            "stop_idx",
            (
                settings.penalty_min * 60
                + pl.col("metres") * settings.detour_factor / metres_per_second
            )
            .ceil()
            .cast(pl.UInt32)
            .alias("seconds"),
        )
        .sort("zone", "stop_idx")
    )
    zone = rides["zone"].to_numpy()
    bounds = np.searchsorted(zone, np.arange(len(walks) + 1))
    stops = rides["stop_idx"].to_numpy().astype(np.uint32)
    seconds = rides["seconds"].to_numpy().astype(np.uint32)
    return [
        (stops[a:b].copy(), seconds[a:b].copy())
        for a, b in zip(bounds[:-1].tolist(), bounds[1:].tolist(), strict=True)
    ]
