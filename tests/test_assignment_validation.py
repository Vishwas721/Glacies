"""Assignment validation report: peak segments by hand (Phase 6 M6)."""

import polars as pl
import pytest

from glacies.assignment.validation import peak_segments

U32 = pl.UInt32


def test_peak_segments_sum_the_vehicles_leaving_in_the_window() -> None:
    # Route 0 runs trips 0 and 1 over stops 5 -> 6; trip 1 leaves after the window (09:30).
    # Route 1 (trip 2) runs 8 -> 9 with nobody on board.
    loads = pl.DataFrame(
        {
            "trip_idx": [0, 1, 2],
            "from_stop_idx": [5, 5, 8],
            "to_stop_idx": [6, 6, 9],
            "departure": [31200, 34300, 31200],
            "load": [40.0, 90.0, 0.0],
            "load_factor": [40 / 60, 1.5, 0.0],
            "capacity": [60, 60, 400],
        },
        schema_overrides={"trip_idx": U32, "from_stop_idx": U32, "to_stop_idx": U32},
    )
    trips = pl.DataFrame(
        {"trip_idx": [0, 1, 2], "route_idx": [0, 0, 1]},
        schema=[("trip_idx", U32), ("route_idx", U32)],
    )
    routes = pl.DataFrame(
        {"route_idx": [0, 1], "mode": ["bus", "metro"], "short_name": ["10", "M1"]},
        schema_overrides={"route_idx": U32},
    )
    segments = peak_segments(loads, trips, routes, (30600, 34200))  # 08:30-09:30

    assert segments["trips"].to_list() == [1, 1]
    assert segments["passengers"].to_list() == [40.0, 0.0]
    assert segments["max_load_factor"].to_list() == pytest.approx([40 / 60, 0.0])
    assert segments["short_name"].to_list() == ["10", "M1"]
