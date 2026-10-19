"""Assignment metrics on hand-checkable numbers (Phase 6 M2)."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from glacies.assignment.aon import AonFlows, segment_loads
from glacies.assignment.metrics import (
    city_metrics,
    route_metrics,
    station_fit,
    station_flows,
    with_distances,
)
from glacies.cities import load_demand
from tests.test_assignment_aon import STOP_TIMES, flows, vehicles

TOY_DEMAND = Path(__file__).parent / "fixtures" / "cities" / "toyville" / "demand.toml"


def loads_with_km() -> pl.DataFrame:
    # Bus 5->6 carries 10 for 1 km, 6->7 carries 8 for 2 km; metro 8->9 carries 2 for 3 km.
    f = flows([10.0, 2.0, 0.0, 2.0, 0.0], [0.0, 4.0, 8.0, 0.0, 2.0])
    return segment_loads(STOP_TIMES, f, vehicles()).with_columns(pl.Series("km", [1.0, 2.0, 3.0]))


def test_distances_are_great_circle_km() -> None:
    # 0.01° of latitude is 1.112 km; the stops are on one meridian.
    stops = pl.DataFrame(
        {"stop_idx": [5, 6], "lat": [12.97, 12.98], "lon": [77.59, 77.59]},
        schema_overrides={"stop_idx": pl.UInt32},
    )
    loads = pl.DataFrame(
        {"from_stop_idx": [5], "to_stop_idx": [6]},
        schema={"from_stop_idx": pl.UInt32, "to_stop_idx": pl.UInt32},
    )
    assert with_distances(loads, stops)["km"].to_list() == pytest.approx([1.112], abs=1e-3)


def test_route_metrics_sum_the_segments() -> None:
    trips = pl.DataFrame(
        {"trip_idx": [0, 1], "route_idx": [0, 1]},
        schema={"trip_idx": pl.UInt32, "route_idx": pl.UInt32},
    )
    routes = pl.DataFrame(
        {"route_idx": [0, 1], "mode": ["bus", "metro"], "short_name": ["10", "M1"]},
        schema_overrides={"route_idx": pl.UInt32},
    )
    # Report window 08:40-08:45: the bus from stop 5 (10 of 60 places, 1 km) and the metro
    # (2 of 400, 3 km) leave in it; the bus from stop 6 does not.
    table = route_metrics(loads_with_km(), trips, routes, (31200, 31500))
    bus, metro = table.row(0, named=True), table.row(1, named=True)

    assert bus["boardings"] == 12.0
    assert bus["passenger_km"] == 10 * 1 + 8 * 2
    assert bus["passenger_hours"] == pytest.approx((10 * 300 + 8 * 300) / 3600)
    assert bus["peak_trips"] == 1
    assert bus["peak_utilisation"] == pytest.approx(10 / 60)
    assert bus["peak_max_load_factor"] == pytest.approx(10 / 60)
    assert bus["peak_share_over_capacity"] == 0.0
    assert metro["passenger_km"] == 6.0
    assert metro["peak_utilisation"] == pytest.approx(2 / 400)


def test_city_metrics_weight_pairs_by_their_transit_trips() -> None:
    # Pair A: 3 transit trips of 20 min in vehicles, 4 waiting, 6 walking, 1 vehicle.
    # Pair B: 1 trip of 40 + 8 + 2 + 5 riding, 3 vehicles, starting with a ride.
    # Pair C: walked, so it has no journey and does not count.
    od = pl.DataFrame(
        {
            "trips": [3.0, 1.0, 2.0],
            "transit": [3.0, 1.0, 0.0],
            "walked": [0.0, 0.0, 2.0],
            "unreached": [0.0, 0.0, 0.0],
            "in_vehicle_min": [20.0, 40.0, None],
            "waiting_min": [4.0, 8.0, None],
            "walking_min": [6.0, 2.0, None],
            "riding_min": [0.0, 5.0, None],
            "vehicles": [1.0, 3.0, None],
            "ridden": [0.0, 1.0, 0.0],
        }
    )
    gates = pl.DataFrame({"entry_station": [8], "exit_station": [9], "trips": [1.0]})
    f = AonFlows(od=od, boardings=np.zeros(0), alightings=np.zeros(0), gates=gates)
    # In the window: 10 people on an overfull km (above crush too) and 30 on a comfortable one;
    # a segment outside the window adds passenger-km but no crowding.
    loads = pl.DataFrame(
        {
            "departure": [100, 100, 900],
            "load": [10.0, 30.0, 5.0],
            "km": [1.0, 1.0, 2.0],
            "load_factor": [1.5, 0.5, 2.0],
            "crush_factor": [1.2, 0.4, 1.8],
        }
    )
    c = city_metrics(f, loads, (0, 500))

    assert c.mean_in_vehicle_min == pytest.approx((3 * 20 + 40) / 4)
    assert c.mean_waiting_min == pytest.approx((3 * 4 + 8) / 4)
    assert c.mean_riding_min == pytest.approx(5 / 4)
    assert c.mean_travel_min == pytest.approx((3 * 30 + 55) / 4)
    assert c.transfers_per_trip == pytest.approx((3 * 1 + 3) / 4 - 1)
    assert c.share_riding_to_station == pytest.approx(0.25)
    assert c.passenger_km == 10 + 30 + 10
    assert c.peak_crowded_pkm_share == pytest.approx(0.25)
    assert c.peak_crush_pkm_share == pytest.approx(0.25)
    assert c.metro_entries == 1.0


def test_station_entries_are_scored_per_set() -> None:
    gates = pl.DataFrame(
        {"entry_station": [1, 2, 3], "exit_station": [2, 1, 1], "trips": [2.0, 2.0, 5.0]},
        schema={"entry_station": pl.UInt32, "exit_station": pl.UInt32, "trips": pl.Float64},
    )
    f = AonFlows(od=pl.DataFrame(), boardings=np.zeros(0), alightings=np.zeros(0), gates=gates)
    network = pl.DataFrame(
        {
            "station_idx": [1, 2, 3],
            "name": ["North", "South", "Central Station"],
            "lines": ["Red", "Red", "Red"],
        },
        schema_overrides={"station_idx": pl.UInt32},
    )
    stations = station_flows(f, network)
    assert stations["entries"].to_list() == [2.0, 2.0, 5.0]
    assert stations["exits"].to_list() == [7.0, 2.0, 0.0]

    observed = pl.DataFrame(
        {"station_idx": [1, 2, 3], "observed": [1.0, 3.0, 5.0]},
        schema_overrides={"station_idx": pl.UInt32},
    )
    # Toyville holds out "Central Station". Training shares: simulated 0.5 / 0.5 against
    # observed 0.25 / 0.75, so R² = 1 - 0.125 / 0.125 = 0 and the level is 4 / 4.
    table, fits = station_fit(stations, observed, load_demand(TOY_DEMAND).calibration)
    assert table["set"].to_list() == ["training", "training", "held_out"]
    assert fits["training"].r2_share == pytest.approx(0.0)
    assert fits["training"].level_ratio == pytest.approx(1.0)
    assert fits["held_out"].level_ratio == pytest.approx(1.0)
