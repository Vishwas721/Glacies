"""All-or-nothing assignment: vehicles, segment loads and conservation (Phase 6 M1)."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from glacies.assignment.aon import (
    AonFlows,
    AssignmentError,
    check_and_summarise,
    segment_loads,
    stop_flows,
    trip_vehicles,
)
from glacies.cities import load_assignment

TOY = Path(__file__).parent / "fixtures" / "cities" / "toyville" / "assignment.toml"

# Trip 0 (bus): stops 5 -> 6 -> 7 at 08:40, 08:45, 08:50. Trip 1 (metro): stops 8 -> 9.
STOP_TIMES = pl.DataFrame(
    {
        "trip_idx": [0, 0, 0, 1, 1],
        "position": [0, 1, 2, 0, 1],
        "stop_idx": [5, 6, 7, 8, 9],
        "arrival": [31200, 31500, 31800, 31200, 31560],
        "departure": [31200, 31500, 31800, 31200, 31560],
    },
    schema_overrides=dict.fromkeys(("trip_idx", "stop_idx", "arrival", "departure"), pl.UInt32)
    | {"position": pl.UInt16},
)
ROUTES = pl.DataFrame(
    {
        "route_idx": [0, 1, 2],
        "mode": ["bus", "metro", "bus"],
        "short_name": ["10", "M1", "10 EXP"],
        "route_number": ["10", "M1", "10 EXP"],
    },
    schema_overrides={"route_idx": pl.UInt32},
)


def flows(board: list[float], alight: list[float], od: pl.DataFrame | None = None) -> AonFlows:
    if od is None:
        od = pl.DataFrame({"trips": [12.0], "transit": [12.0], "walked": [0.0], "unreached": [0.0]})
    return AonFlows(od=od, boardings=np.array(board), alightings=np.array(alight))


def vehicles() -> pl.DataFrame:
    trips = pl.DataFrame(
        {"trip_idx": [0, 1], "route_idx": [0, 1]},
        schema=[("trip_idx", pl.UInt32), ("route_idx", pl.UInt32)],
    )
    return trip_vehicles(ROUTES, trips, load_assignment(TOY).capacity)


def test_vehicles_match_mode_and_route_prefix() -> None:
    trips = pl.DataFrame(
        {"trip_idx": [0, 1, 2], "route_idx": [0, 1, 2]},
        schema=[("trip_idx", pl.UInt32), ("route_idx", pl.UInt32)],
    )
    table = trip_vehicles(ROUTES, trips, load_assignment(TOY).capacity)

    # Toy vehicles: bus 30 seats + 5 m² (60 at 6/m², 70 at 8/m²); "10 EXP" buses 40 seats
    # and no standing; metro 100 seats + 50 m² (400 / 500).
    assert table["vehicle"].to_list() == ["bus", "metro", "bus_express"]
    assert table["capacity"].to_list() == [60, 400, 40]
    assert table["crush_capacity"].to_list() == [70, 500, 40]


def test_a_mode_without_a_vehicle_is_an_error() -> None:
    routes = ROUTES.with_columns(pl.lit("tram").alias("mode"))
    trips = pl.DataFrame(
        {"trip_idx": [0], "route_idx": [0]},
        schema=[("trip_idx", pl.UInt32), ("route_idx", pl.UInt32)],
    )
    with pytest.raises(AssignmentError, match="tram"):
        trip_vehicles(routes, trips, load_assignment(TOY).capacity)


def test_loads_are_the_running_sum_of_boardings_minus_alightings() -> None:
    # Bus: 10 board at stop 5; at stop 6, 4 alight and 2 board; 8 alight at stop 7.
    # Segment 5->6 carries 10, 6->7 carries 8. Metro: 2 ride 8->9.
    f = flows([10.0, 2.0, 0.0, 2.0, 0.0], [0.0, 4.0, 8.0, 0.0, 2.0])
    loads = segment_loads(STOP_TIMES, f, vehicles())

    assert loads["from_stop_idx"].to_list() == [5, 6, 8]
    assert loads["to_stop_idx"].to_list() == [6, 7, 9]
    assert loads["load"].to_list() == [10.0, 8.0, 2.0]
    assert loads["load_factor"].to_list() == pytest.approx([10 / 60, 8 / 60, 2 / 400])
    assert loads["arrival"].to_list() == [31500, 31800, 31560]

    stops = stop_flows(STOP_TIMES, f)
    assert stops["stop_idx"].to_list() == [5, 6, 7, 8, 9]
    assert stops["boardings"].sum() == stops["alightings"].sum() == 14.0


def test_passengers_left_on_board_are_an_error() -> None:
    f = flows([10.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 6.0, 0.0, 0.0])
    with pytest.raises(AssignmentError, match="on board"):
        segment_loads(STOP_TIMES, f, vehicles())


def test_summary_counts_peak_segments_and_transfers() -> None:
    # 12 transit trips make 14 boardings: 2 change from the bus to the metro.
    f = flows([10.0, 2.0, 0.0, 2.0, 0.0], [0.0, 4.0, 8.0, 0.0, 2.0])
    loads = segment_loads(STOP_TIMES, f, vehicles())
    stats = check_and_summarise(f, loads, (31200, 31500))  # 08:40-08:45 leaves

    assert stats.boardings == 14.0
    assert stats.transfers_per_transit_trip == pytest.approx(2 / 12)
    assert stats.peak_segments == 2  # the bus from stop 5 and the metro
    assert stats.passenger_hours == pytest.approx((10 * 300 + 8 * 300 + 2 * 360) / 3600)


def test_leaked_demand_fails_the_conservation_check() -> None:
    od = pl.DataFrame({"trips": [12.0], "transit": [11.0], "walked": [0.0], "unreached": [0.0]})
    f = flows([10.0, 2.0, 0.0, 2.0, 0.0], [0.0, 4.0, 8.0, 0.0, 2.0], od)
    with pytest.raises(AssignmentError, match="differ from the OD"):
        check_and_summarise(f, segment_loads(STOP_TIMES, f, vehicles()), (0, 1))
