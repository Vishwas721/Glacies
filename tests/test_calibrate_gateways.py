"""Calibration fits the gateway factor on training stations (Phase 5 M8)."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from glacies.cities import Gateway, Gateways, load_demand
from glacies.demand.calibrate import TRAINING, Targets, calibrate, station_sets
from glacies.demand.gateways import prepare_gateways
from glacies.demand.od import DemandModel, PurposeModel, prepare_demand

TOY = Path(__file__).parent / "fixtures" / "cities" / "toyville" / "demand.toml"
U32 = pl.UInt32
MATRIX = pl.LazyFrame(
    [(i, j, 600 * (1 + abs(i - j))) for i in range(4) for j in range(4) if i != j],
    schema={"origin_zone": U32, "dest_zone": U32, "p50_s": pl.UInt16},
    orient="row",
)


def zones() -> pl.DataFrame:
    """Zone 3 has nobody living in it: only the gateway starts trips there."""
    return pl.DataFrame(
        {
            "zone_idx": pl.Series([0, 1, 2, 3], dtype=U32),
            "h3_cell": ["a", "b", "c", "d"],
            "lat": [12.00, 12.01, 12.02, 12.03],
            "lon": [77.0] * 4,
            "pop_lat": [12.00, 12.01, 12.02, 12.03],
            "pop_lon": [77.0] * 4,
            "population": [1000.0, 2000.0, 1000.0, 0.0],
        }
    )


def targets() -> Targets:
    """0 -> 2 enters at A (10); 3 -> 1 enters at B (12); both stations observe 30 entries.
    Central Station (13) is the toy's held-out station."""
    stations = pl.DataFrame(
        {"station_idx": [10, 11, 12, 13], "name": ["A", "Z", "B", "Central Station"],
         "lines": ["M1"] * 4},
        schema={"station_idx": U32, "name": pl.String, "lines": pl.String},
    )  # fmt: skip
    metro = {(0, 2): 10, (3, 1): 12}
    reach = pl.DataFrame(
        [(i, j, 4, 0, 4 * int((i, j) in metro)) for i in range(4) for j in range(4) if i != j],
        schema={"origin_zone": U32, "dest_zone": U32, "reached": U32, "walked": U32, "metro": U32},
        orient="row",
    )
    paths = pl.DataFrame(
        [(o, d, entry, 11, 4, 1.0) for (o, d), entry in metro.items()],
        schema={"origin_zone": U32, "dest_zone": U32, "entry_station": U32, "exit_station": U32,
                "departures": U32, "share": pl.Float64},
        orient="row",
    )  # fmt: skip
    demand = load_demand(TOY)
    return Targets(
        sets=station_sets(stations, demand.calibration),
        entries=pl.DataFrame(
            {"station_idx": [10, 11, 12, 13], "observed": [30.0, 0.0, 30.0, 5.0]},
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


def test_gateway_factor_balances_the_two_stations() -> None:
    gateways = Gateways(
        factor=0.0,
        factor_max=10.0,
        stations=[
            Gateway(name="Terminal", lat=12.03, lon=77.0, daily_passengers=100.0,
                    source="test", verified=False)
        ],
    )  # fmt: skip
    demand = load_demand(TOY).model_copy(update={"gateways": gateways})
    prepared = prepare_demand(
        zones(), np.array([0.2, 0.3, 0.3, 0.2]), np.ones(4, dtype=bool), MATRIX, demand,
        detour_factor=1.0,
    )  # fmt: skip
    pairs = MATRIX.collect().rename({"p50_s": "cost_s"}).with_columns(pl.col("cost_s").cast(U32))
    found = pl.DataFrame(
        {"name": ["Terminal"], "zone_idx": [3], "daily_passengers": [100.0]},
        schema={"name": pl.String, "zone_idx": U32, "daily_passengers": pl.Float64},
    )
    model = DemandModel(
        main=PurposeModel(config=demand, prepared=prepared),
        purposes=[],
        gateways=prepare_gateways(found, pairs, prepared.attractions, np.ones(pairs.height)),
    )

    result = calibrate(model, demand, targets())

    training = result.stations.filter(pl.col("set") == TRAINING).sort("station_idx")
    a, _, b = training["simulated"].to_list()
    assert 0 < result.gateway_factor < 10
    assert a == pytest.approx(b, rel=1e-4)
    assert result.fits[TRAINING].rmse_share == pytest.approx(0, abs=1e-5)
    assert all(p.gateway_factor > 0 for p in result.sweep)
