"""Sensitivity variants on a 4-zone hand-made model (Phase 5 M5)."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from glacies.cities import load_demand
from glacies.demand.calibrate import Targets, station_sets
from glacies.demand.od import Prepared, prepare_demand
from glacies.demand.sensitivity import run_variants

TOY = Path(__file__).parent / "fixtures" / "cities" / "toyville" / "demand.toml"
U32 = pl.UInt32


def zones() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "zone_idx": pl.Series([0, 1, 2, 3], dtype=U32),
            "h3_cell": ["a", "b", "c", "d"],
            "lat": [12.00, 12.01, 12.02, 12.03],
            "lon": [77.0, 77.0, 77.0, 77.0],
            "pop_lat": [12.00, 12.01, 12.02, 12.03],
            "pop_lon": [77.0, 77.0, 77.0, 77.0],
            "population": [1000.0, 2000.0, 1000.0, 1000.0],
        }
    )


MATRIX = pl.LazyFrame(
    [(i, j, 600 * (1 + abs(i - j))) for i in range(4) for j in range(4) if i != j],
    schema={"origin_zone": U32, "dest_zone": U32, "p50_s": pl.UInt16},
    orient="row",
)


def targets() -> Targets:
    """Zone 0 -> 2 rides the metro from station 10 to 11 at every departure."""
    stations = pl.DataFrame(
        {"station_idx": [10, 11], "name": ["Central Station", "Far"], "lines": ["M1", "M1"]},
        schema={"station_idx": U32, "name": pl.String, "lines": pl.String},
    )
    reach = pl.DataFrame(
        [(i, j, 4, 0, int(i == 0 and j == 2) * 4) for i in range(4) for j in range(4) if i != j],
        schema={"origin_zone": U32, "dest_zone": U32, "reached": U32, "walked": U32, "metro": U32},
        orient="row",
    )
    paths = pl.DataFrame(
        {"origin_zone": [0], "dest_zone": [2], "entry_station": [10], "exit_station": [11],
         "departures": [4], "share": [1.0]},
        schema={"origin_zone": U32, "dest_zone": U32, "entry_station": U32, "exit_station": U32,
                "departures": U32, "share": pl.Float64},
    )  # fmt: skip
    return Targets(
        sets=station_sets(stations, load_demand(TOY).calibration),
        entries=pl.DataFrame(
            {"station_idx": [10, 11], "observed": [30.0, 10.0]},
            schema={"station_idx": U32, "observed": pl.Float64},
        ),
        pairs=pl.DataFrame(
            schema={"entry_station": U32, "exit_station": U32, "observed": pl.Float64}
        ),
        pair_dates=[],
        reach=reach,
        paths=paths,
        stations=stations,
    )


def test_variants_change_one_thing_each() -> None:
    demand = load_demand(TOY)  # β 0.1; rate 0.10 (0.08-0.14) x share 0.5 (0.4-0.6)
    scores = {
        "baseline": np.array([0.2, 0.3, 0.3, 0.2]),
        "other": np.array([0.4, 0.3, 0.2, 0.1]),
    }

    def prepare(name: str) -> Prepared:
        return prepare_demand(
            zones(), scores[name], np.ones(4, dtype=bool), MATRIX, demand, detour_factor=1.0
        )

    results = {r.name: r for r in run_variants(prepare, demand, targets(), ["baseline", "other"],
                                               {3})}  # fmt: skip

    assert list(results) == [
        "baseline",
        "beta x 0.5",
        "beta x 2",
        "proxy other",
        "trip rate and transit share low",
        "trip rate and transit share high",
    ]
    base = results["baseline"]
    assert base.trips == pytest.approx(5000 * 0.05)
    assert results["beta x 2"].beta_per_min == pytest.approx(0.2)
    assert results["beta x 2"].mean_km < base.mean_km < results["beta x 0.5"].mean_km
    low, high = (
        results["trip rate and transit share low"],
        results["trip rate and transit share high"],
    )
    assert low.trips == pytest.approx(base.trips * 0.08 * 0.4 / 0.05)
    assert high.station_entries == pytest.approx(base.station_entries * 0.14 * 0.6 / 0.05)
    assert low.mean_km == base.mean_km
    assert base.hub_trip_share == pytest.approx(0.2)  # zone 3's share of the proxy
    assert results["proxy other"].hub_trip_share == pytest.approx(0.1)
