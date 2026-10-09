"""Trip productions and attractions on a 5-zone toy (Phase 5 M1)."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from glacies.cities import DemandConfig, load_demand
from glacies.demand.production import DemandError, candidate_pairs, trip_ends

TOY = Path(__file__).parent / "fixtures" / "cities" / "toyville" / "demand.toml"


@pytest.fixture
def demand() -> DemandConfig:
    return load_demand(TOY)  # rate 0.10 (0.08-0.14) x share 0.5 (0.4-0.6)


def zones() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "zone_idx": pl.Series(range(5), dtype=pl.UInt32),
            "h3_cell": [f"cell{i}" for i in range(5)],
            "population": [100.0, 200.0, 300.0, 50.0, 0.0],
        }
    )


# Zone 0 and 1 have a stop and reach each other. Zone 2 has no stop (it reaches zone 0 on foot).
# Zone 3 has a stop but reaches only itself. Zone 4 has a stop and nobody lives there.
SCORE = np.array([0.4, 0.3, 0.2, 0.1, 0.0])
ACCESS = np.array([True, True, False, True, True])


def matrix() -> pl.LazyFrame:
    rows: list[tuple[int, int, int | None]] = [
        (0, 0, 0), (0, 1, 600), (0, 2, 900), (1, 0, 600), (1, 1, 0), (2, 0, 900), (3, 3, 0),
        (1, 4, None),  # p50 not reached
    ]  # fmt: skip
    return pl.LazyFrame(
        rows,
        schema={"origin_zone": pl.UInt32, "dest_zone": pl.UInt32, "p50_s": pl.UInt16},
        orient="row",
    )


def test_candidate_pairs_drop_unreached_and_intrazonal() -> None:
    pairs = candidate_pairs(matrix(), "p50_s", exclude_intrazonal=True)

    assert pairs.rows() == [(0, 1, 600), (0, 2, 900), (1, 0, 600), (2, 0, 900)]
    with_self = candidate_pairs(matrix(), "p50_s", exclude_intrazonal=False)
    assert (3, 3, 0) in with_self.rows()


def test_unknown_cost_column() -> None:
    with pytest.raises(DemandError, match="p90_s"):
        candidate_pairs(matrix(), "p90_s", exclude_intrazonal=True)


def test_trip_ends_by_hand(demand: DemandConfig) -> None:
    """O = population x 0.10 x 0.5 for zones 0 and 1 only: 5 + 10 = 15 trips.

    Zone 2 has no stop, zone 3 reaches no other zone, zone 4 has no people or jobs. The
    destinations are zones 0 and 1, whose scores 0.4 and 0.3 split the 15 trips 8.571 / 6.429.
    """
    pairs = candidate_pairs(matrix(), "p50_s", exclude_intrazonal=True)

    ends = trip_ends(zones(), SCORE, ACCESS, pairs, demand)

    np.testing.assert_allclose(ends.table["origin"].to_numpy(), [5, 10, 0, 0, 0])
    np.testing.assert_allclose(
        ends.table["destination"].to_numpy(), [15 * 4 / 7, 15 * 3 / 7, 0, 0, 0]
    )
    s = ends.stats
    assert (s.zones, s.zones_with_access, s.origin_zones, s.destination_zones) == (5, 4, 2, 2)
    assert s.population_with_access == 350
    assert s.population_unreachable == 50  # zone 3
    assert s.trips == pytest.approx(15)
    assert s.trips_low == pytest.approx(15 * 0.08 * 0.4 / 0.05)
    assert s.trips_high == pytest.approx(15 * 0.14 * 0.6 / 0.05)
    assert s.employment_share_kept == pytest.approx(0.7)


def test_stranded_zones_are_dropped_until_none_is_left(demand: DemandConfig) -> None:
    """Zone 0's only destination (zone 1) has no jobs, so zone 0 produces nothing; then zone
    0's only origin is gone too, and nothing is left."""
    pairs = pl.DataFrame(
        {"origin_zone": [0, 1], "dest_zone": [1, 0], "cost_s": [600, 600]},
        schema={"origin_zone": pl.UInt32, "dest_zone": pl.UInt32, "cost_s": pl.UInt32},
    )
    score = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
    population = zones().with_columns(pl.Series("population", [100.0, 0.0, 0.0, 0.0, 0.0]))

    with pytest.raises(DemandError, match="no zone with transit access"):
        trip_ends(population, score, ACCESS, pairs, demand)


def test_rejects_non_contiguous_zones(demand: DemandConfig) -> None:
    shuffled = zones().with_columns(pl.Series("zone_idx", [0, 1, 2, 3, 7], dtype=pl.UInt32))
    pairs = candidate_pairs(matrix(), "p50_s", exclude_intrazonal=True)

    with pytest.raises(DemandError, match=r"0\.\.n-1"):
        trip_ends(shuffled, SCORE, ACCESS, pairs, demand)


def test_a_zone_that_only_rides_produces_but_does_not_attract(demand: DemandConfig) -> None:
    """Zone 2 rides to a station (no walk to a stop): it sends 300 x 0.05 = 15 trips to zone 0,
    but trips end with a walk, so its score (0.2) attracts nothing. O = 5 + 10 + 15 = 30, split
    4 : 3 over zones 0 and 1."""
    pairs = candidate_pairs(matrix(), "p50_s", exclude_intrazonal=True)
    rides = ACCESS | np.array([False, False, True, False, False])

    ends = trip_ends(zones(), SCORE, rides, pairs, demand, walk_access=ACCESS)

    np.testing.assert_allclose(ends.table["origin"].to_numpy(), [5, 10, 15, 0, 0])
    np.testing.assert_allclose(
        ends.table["destination"].to_numpy(), [30 * 4 / 7, 30 * 3 / 7, 0, 0, 0]
    )
    assert ends.table["has_walk_access"].to_list() == ACCESS.tolist()
    assert (ends.stats.zones_ride_only, ends.stats.population_ride_only) == (1, 300)
