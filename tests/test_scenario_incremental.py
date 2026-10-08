from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl
import pytest

from glacies.analytics.travel_times import write_part
from glacies.cities import ScenarioDefaults
from glacies.model.transit.schema import TABLES
from glacies.scenario.incremental import changed_stops
from glacies.scenario.mutations import apply
from glacies.scenario.schema import Scenario


@pytest.fixture
def baseline(city_dir: Path) -> dict[str, pl.DataFrame]:
    return {n: pl.read_parquet(city_dir / "transit" / f"{n}.parquet") for n in TABLES}


Tables = dict[str, pl.DataFrame]


def applied(baseline: Tables, *mutations: dict[str, Any]) -> Tables:
    scenario = Scenario.model_validate(
        {"schema_version": 1, "scenario_id": "t", "title": "T", "mutations": list(mutations)}
    )
    return apply(baseline, scenario, ScenarioDefaults()).tables


def names(baseline: Tables, stops: npt.NDArray[np.uint32] | None) -> list[str]:
    assert stops is not None
    idx = pl.Series(stops, dtype=pl.UInt32)
    table = baseline["stops"].filter(pl.col("stop_idx").is_in(idx.implode()))
    return sorted(table["source_stop_id"].to_list())


def test_changed_stops_are_the_stops_of_added_or_removed_trips(
    baseline: dict[str, pl.DataFrame],
) -> None:
    halve = {"type": "modify_headway", "route_id": "R1", "headway_factor": 0.5}
    assert names(baseline, changed_stops(baseline, applied(baseline, halve))) == ["A", "B", "C"]
    remove = {"type": "remove_route", "route_id": "R3"}
    assert names(baseline, changed_stops(baseline, applied(baseline, remove))) == ["D", "P1"]
    noop = {**halve, "headway_factor": 1}
    assert names(baseline, changed_stops(baseline, applied(baseline, noop))) == []


def test_retimed_trips_count_as_changed(baseline: dict[str, pl.DataFrame]) -> None:
    later = baseline | {
        "stop_times": baseline["stop_times"].with_columns(
            pl.when(pl.col("trip_idx") == 0)
            .then(pl.col("arrival") + 60)
            .otherwise(pl.col("arrival"))
            .alias("arrival")
        )
    }
    assert names(baseline, changed_stops(baseline, later)) == ["A", "B", "C"]


def test_changed_stops_refuse_a_different_stop_table(baseline: dict[str, pl.DataFrame]) -> None:
    moved = baseline | {"stops": baseline["stops"].with_columns(pl.col("lat") + 0.001)}
    assert changed_stops(baseline, moved) is None


def test_matrix_parts_are_written_independently_of_chunking(tmp_path: Path) -> None:
    # 150k rows fit one row group, but Polars keeps a chunk of ~100k rows as its own: a
    # Bengaluru part is this size, a toy part far smaller, so toy end-to-end runs cannot
    # catch it.
    n = 150_000
    rows = pl.DataFrame(
        {
            "origin_zone": pl.arange(0, n, eager=True) // 50,
            "dest_zone": pl.arange(0, n, eager=True) % 50,
        }
    ).cast(pl.UInt32)
    stitched = pl.concat([rows.head(100_000), rows.tail(n - 100_000)], rechunk=False)
    assert stitched.n_chunks() == 2
    write_part(rows, tmp_path / "one.parquet")
    write_part(stitched, tmp_path / "two.parquet")
    assert (tmp_path / "one.parquet").read_bytes() == (tmp_path / "two.parquet").read_bytes()
