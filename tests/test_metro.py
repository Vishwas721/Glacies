"""Station flows from OD trips and a path table, by hand (Phase 5 M3)."""

import polars as pl
import pytest

from glacies.demand.metro import path_shares, station_flows, walk_pairs

U32 = pl.UInt32


def frame(rows: list[tuple[object, ...]], columns: list[str]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=columns, orient="row").with_columns(
        pl.col(c).cast(U32) for c in columns if c not in ("trips",)
    )


STATIONS = pl.DataFrame(
    {"station_idx": [10, 11, 12], "name": ["X", "Y", "Z"], "lines": ["P", "P", "G+P"]},
    schema={"station_idx": U32, "name": pl.String, "lines": pl.String},
)


def test_flows_by_hand() -> None:
    """Pair (0, 1): 120 trips, 4 departures reach it: 1 walks, 2 ride X -> Y, 1 rides X -> Z
    and then re-enters at Z -> Y. Pair (0, 2): 60 trips, 2 departures, both by bus only.

    Walked 120/4 = 30. Metro journeys 3 of 4 -> 90 trips. Flows: X -> Y 120 x 2/4 = 60,
    X -> Z 30, Z -> Y 30; entries 120 (one journey enters twice).
    """
    od = frame([(0, 1, 120.0), (0, 2, 60.0)], ["origin_zone", "dest_zone", "trips"])
    reach = frame(
        [(0, 1, 4, 1, 3), (0, 2, 2, 0, 0)],
        ["origin_zone", "dest_zone", "reached", "walked", "metro"],
    )
    segments = frame(
        [(0, 1, 10, 11, 2), (0, 1, 10, 12, 1), (0, 1, 12, 11, 1)],
        ["origin_zone", "dest_zone", "entry_station", "exit_station", "departures"],
    )

    flows = station_flows(od, reach, path_shares(reach, segments), STATIONS)

    assert flows.pairs.rows() == [(10, 11, 60.0), (10, 12, 30.0), (12, 11, 30.0)]
    assert flows.stations.select("name", "entries", "exits").rows() == [
        ("X", 90.0, 0.0),
        ("Y", 0.0, 90.0),
        ("Z", 30.0, 30.0),
    ]
    s = flows.stats
    assert (s.trips, s.trips_walked, s.trips_unreached) == (180, 30, 0)
    assert s.trips_using_metro == pytest.approx(90)
    assert s.entries == pytest.approx(120)


def test_unreached_pairs_are_counted() -> None:
    od = frame([(0, 1, 50.0)], ["origin_zone", "dest_zone", "trips"])
    reach = frame([(0, 1, 0, 0, 0)], ["origin_zone", "dest_zone", "reached", "walked", "metro"])
    segments = frame(
        [], ["origin_zone", "dest_zone", "entry_station", "exit_station", "departures"]
    )

    flows = station_flows(od, reach, path_shares(reach, segments), STATIONS)

    assert flows.stats.trips_unreached == 50
    assert flows.pairs.height == 0


def test_walk_pairs_take_half_or_more_departures_on_foot() -> None:
    reach = frame(
        [(0, 1, 4, 2, 0), (0, 2, 4, 1, 3), (0, 3, 3, 2, 0)],
        ["origin_zone", "dest_zone", "reached", "walked", "metro"],
    )

    assert walk_pairs(reach).rows() == [(0, 1), (0, 3)]
