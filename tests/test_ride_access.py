"""Rides to stations at the home end, on hand-measured distances (Phase 5 M7)."""

import numpy as np
import polars as pl

from glacies.cities import RideAccess
from glacies.demand.access import ride_access

# 0.01 degrees of latitude is 1,111.95 m on the haversine sphere (R = 6,371,008.8 m).
DEGREE_M = 1111.95
SETTINGS = RideAccess(
    max_km=2.5, speed_kmh=18.0, detour_factor=1.5, penalty_min=5, source="test", verified=False
)


def test_rides_by_hand() -> None:
    """Zone 0 is at the origin; platforms 7, 3 and 9 lie 1, 2 and 3 'centi-degrees' north.

    Zone 0: platform 9 is beyond 2.5 km; platform 7 is walked to, so only 3 is ridden:
    300 s + 2,223.9 m x 1.5 / 5 m/s = 967.2 -> 968 s. Zone 1 (at platform 9) rides to 9 (300 s,
    0 m) and 3 (1,111.95 m: 300 + 333.6 -> 634 s), sorted by stop; 7 is 2.2 km away: 968 s.
    """
    points = pl.DataFrame({"lat": [12.00, 12.03], "lon": [77.0, 77.0]})
    platforms = pl.DataFrame(
        {"stop_idx": [7, 3, 9], "lat": [12.01, 12.02, 12.03], "lon": [77.0, 77.0, 77.0]}
    )
    walks = [
        (np.array([7], dtype=np.uint32), np.array([600], dtype=np.uint32)),
        (np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.uint32)),
    ]

    rides = ride_access(points, platforms, walks, SETTINGS)

    assert [r[0].tolist() for r in rides] == [[3], [3, 7, 9]]
    assert [r[1].tolist() for r in rides] == [[968], [634, 968, 300]]
    assert all(r[0].dtype == np.uint32 and r[1].dtype == np.uint32 for r in rides)


def test_zones_without_a_station_in_range_get_no_rides() -> None:
    points = pl.DataFrame({"lat": [13.0], "lon": [77.0]})
    platforms = pl.DataFrame({"stop_idx": [1], "lat": [12.0], "lon": [77.0]})
    empty = (np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.uint32))

    rides = ride_access(points, platforms, [empty], SETTINGS)

    assert [r[0].size for r in rides] == [0]
