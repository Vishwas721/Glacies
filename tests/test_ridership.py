"""Ridership normalisation and calibration targets on hand-made files (Phase 5 M4)."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from glacies.demand.production import DemandError
from glacies.demand.ridership import observed_entries, observed_pairs, read_ridership

STATIONS = pl.DataFrame(
    {"station_idx": [5, 9], "name": ["Alpha", "Beta"]},
    schema={"station_idx": pl.UInt32, "name": pl.String},
)


def write(
    folder: Path,
    entries: list[tuple[str, int, str, int]],
    pairs: list[tuple[str, int, str, str, int]] | None = None,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    columns = ["Date", "Hour", "Station", "Ridership"]
    pl.DataFrame(entries, schema=columns, orient="row").write_parquet(
        folder / "station-hourly.parquet"
    )
    exits = [(d, h, s, n // 2) for d, h, s, n in entries]
    pl.DataFrame(exits, schema=columns, orient="row").write_parquet(
        folder / "station-hourly-exits.parquet"
    )
    pair_columns = {
        "Date": pl.String,
        "Hour": pl.Int64,
        "Origin Station": pl.String,
        "Destination Station": pl.String,
        "Ridership": pl.Int64,
    }
    pl.DataFrame(pairs or [], schema=pair_columns, orient="row").write_parquet(
        folder / "stationpair-hourly.parquet"
    )
    return folder


ENTRIES = [
    ("2025-08-12", 8, "Alpha", 100),
    ("2025-08-12", 9, "Alpha", 50),
    ("2025-08-12", 8, "Beta", 10),
    ("2025-08-13", 8, "Alpha", 70),
    ("2025-08-13", 10, "Beta", 999),
]
PAIRS = [("2025-08-12", 9, "Alpha", "Beta", 40), ("2025-08-12", 11, "Alpha", "Beta", 7)]


def test_reads_and_maps_station_names(tmp_path: Path) -> None:
    ridership = read_ridership(write(tmp_path / "d", ENTRIES, PAIRS), "vonter-hourly", STATIONS)

    first = ridership.stations.row(0, named=True)
    assert first == {
        "date": date(2025, 8, 12), "hour": 8, "station_idx": 5, "entries": 100, "exits": 50,
    }  # fmt: skip
    assert ridership.stations.height == len(ENTRIES)
    assert ridership.pairs.select("entry_station", "exit_station", "trips").rows() == [
        (5, 9, 40),
        (5, 9, 7),
    ]


def test_observed_entries_average_the_window_over_dates(tmp_path: Path) -> None:
    """Alpha: (100 + 50 + 70) / 2 days = 110. Beta: 10 / 2 = 5 (its 10:00 row is outside)."""
    ridership = read_ridership(write(tmp_path / "d", ENTRIES), "vonter-hourly", STATIONS)

    table = observed_entries(ridership.stations, [date(2025, 8, 12), date(2025, 8, 13)], [8, 9])

    assert table.rows() == [(5, 110.0), (9, 5.0)]


def test_missing_calibration_date_is_an_error(tmp_path: Path) -> None:
    ridership = read_ridership(write(tmp_path / "d", ENTRIES), "vonter-hourly", STATIONS)

    with pytest.raises(DemandError, match="2025-08-14"):
        observed_entries(ridership.stations, [date(2025, 8, 14)], [8])


def test_observed_pairs_use_the_dates_that_have_pairs(tmp_path: Path) -> None:
    ridership = read_ridership(write(tmp_path / "d", ENTRIES, PAIRS), "vonter-hourly", STATIONS)

    table, used = observed_pairs(ridership.pairs, [date(2025, 8, 12), date(2025, 8, 13)], [8, 9])

    assert used == [date(2025, 8, 12)]
    assert table.rows() == [(5, 9, 40.0)]


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ([("2025-08-12", 8, "Gamma", 1)], "Gamma"),
        ([("2025-08-12", 8, "Alpha", 1), ("2025-08-12", 8, "Alpha", 2)], "duplicate"),
        ([("2025-08-12", 24, "Alpha", 1)], "hour"),
        ([("2025-08-12", 8, "Alpha", -3)], "negative"),
    ],
)
def test_rejects_bad_rows(
    tmp_path: Path, entries: list[tuple[str, int, str, int]], message: str
) -> None:
    with pytest.raises(DemandError, match=message):
        read_ridership(write(tmp_path / "d", entries), "vonter-hourly", STATIONS)


def test_unknown_format(tmp_path: Path) -> None:
    with pytest.raises(DemandError, match="unknown ridership format"):
        read_ridership(tmp_path, "csv-daily", STATIONS)
