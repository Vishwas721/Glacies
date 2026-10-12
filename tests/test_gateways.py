"""Gateway trips and the fitted gateway factor, by hand (Phase 5 M8)."""

import math

import h3
import numpy as np
import polars as pl
import pytest

from glacies.cities import Gateway, Gateways
from glacies.demand.calibrate import best_factor
from glacies.demand.gateways import gateway_od, gateway_zones, prepare_gateways
from glacies.demand.production import DemandError

POINTS = [(12.97, 77.57), (12.98, 77.60), (13.00, 77.65)]
CELLS = [h3.latlng_to_cell(lat, lon, 8) for lat, lon in POINTS]
ZONES = pl.DataFrame({"zone_idx": pl.Series([0, 1, 2], dtype=pl.UInt32), "h3_cell": CELLS})
PAIRS = pl.DataFrame(
    {"origin_zone": [0, 0, 1], "dest_zone": [1, 2, 2], "cost_s": [600, 1200, 600]},
    schema={"origin_zone": pl.UInt32, "dest_zone": pl.UInt32, "cost_s": pl.UInt32},
)


def gateways(*stations: tuple[str, float, float, float]) -> Gateways:
    return Gateways(
        factor=0.1,
        stations=[
            Gateway(name=n, lat=lat, lon=lon, daily_passengers=d, source="test", verified=False)
            for n, lat, lon, d in stations
        ],
    )


def test_gateways_map_to_the_zone_containing_them() -> None:
    found = gateway_zones(ZONES, gateways(("Rail", *POINTS[0], 1000.0), ("Bus", *POINTS[2], 50.0)))

    assert found.rows() == [("Rail", 0, 1000.0), ("Bus", 2, 50.0)]
    with pytest.raises(DemandError, match="Far"):
        gateway_zones(ZONES, gateways(("Far", 20.0, 70.0, 1.0)))


def test_trips_split_by_attraction_times_friction() -> None:
    """1,000 passengers x 0.1 = 100 trips from zone 0. With β = ln 2 / 10 per minute, zone 1
    (10 min, attraction 1) weighs 0.5 and zone 2 (20 min, attraction 1) 0.25: 66.7 / 33.3.
    Zone 1 is no gateway, so its pair to zone 2 carries nothing."""
    found = gateway_zones(ZONES, gateways(("Rail", *POINTS[0], 1000.0)))
    model = prepare_gateways(found, PAIRS, np.array([0.0, 1.0, 1.0]), np.array([1.0, 2.0, 1.5]))

    od = gateway_od(model, math.log(2) / 10, 0.1)

    assert od.select("origin_zone", "dest_zone").rows() == [(0, 1), (0, 2)]
    np.testing.assert_allclose(od["trips"].to_numpy(), [200 / 3, 100 / 3])
    np.testing.assert_allclose(od["distance_km"].to_numpy(), [1.0, 2.0])


def test_a_gateway_that_reaches_nothing_fails() -> None:
    found = gateway_zones(ZONES, gateways(("Dead end", *POINTS[2], 10.0)))

    with pytest.raises(DemandError, match="Dead end"):
        prepare_gateways(found, PAIRS, np.array([1.0, 1.0, 1.0]), np.ones(3))


def test_best_factor_recovers_the_missing_station() -> None:
    """Stations A and B are simulated right, C (a gateway) not at all; observed shares are
    equal, so adding the gateway with factor 0.5 x (2 at C) fits exactly."""
    factor = best_factor(
        np.array([10.0, 10.0, 0.0]), np.array([0.0, 0.0, 20.0]), np.array([5.0, 5.0, 5.0]), 2.0
    )

    assert factor == pytest.approx(0.5, abs=1e-6)
