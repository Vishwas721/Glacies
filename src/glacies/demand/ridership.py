"""Hourly station ridership → canonical Observed tables (Phase 5 M4).

The engine never reads raw files: ``glacies build ridership`` validates an archived snapshot
and writes ``ridership/<dataset>/`` with dates, hours and the network's own station indices.
Station names in the data are matched to the names of the network's stations of the same mode;
an unknown name is an error, because a silently dropped station would bias calibration.

Formats are named after their layout, not their city. ``vonter-hourly`` is the layout of
Vonter/bmrcl-ridership-hourly: ``station-hourly.parquet`` (entries),
``station-hourly-exits.parquet`` and ``stationpair-hourly.parquet``, with ``Date`` (ISO text),
``Hour`` and ``Ridership`` columns. Everything here is **Observed**.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.demand.production import DemandError
from glacies.fsutil import rename_with_retry
from glacies.provenance import DataNature, sha256_file

MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
STATIONS_NAME = "station_hourly.parquet"
PAIRS_NAME = "station_pairs_hourly.parquet"


@dataclass(frozen=True)
class Layout:
    entries: str
    exits: str
    pairs: str
    date: str
    hour: str
    station: str
    origin: str
    destination: str
    count: str


FORMATS: dict[str, Layout] = {
    "vonter-hourly": Layout(
        entries="station-hourly.parquet",
        exits="station-hourly-exits.parquet",
        pairs="stationpair-hourly.parquet",
        date="Date",
        hour="Hour",
        station="Station",
        origin="Origin Station",
        destination="Destination Station",
        count="Ridership",
    )
}


@dataclass
class Ridership:
    stations: pl.DataFrame  # date, hour, station_idx, entries, exits
    pairs: pl.DataFrame  # date, hour, entry_station, exit_station, trips


def _read(path: Path, columns: Sequence[str]) -> pl.DataFrame:
    if not path.is_file():
        raise DemandError(f"ridership file missing: {path.name}")
    frame = pl.read_parquet(path)
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise DemandError(f"{path.name}: missing column(s) {', '.join(missing)}")
    return frame.select(columns)


def _station_ids(names: pl.Series, stations: pl.DataFrame, what: str) -> None:
    unknown = sorted(set(names.unique().to_list()) - set(stations["name"].to_list()))
    if unknown:
        raise DemandError(f"{what}: stations not in the network: {', '.join(unknown)}")


def read_ridership(data_dir: Path, fmt: str, stations: pl.DataFrame) -> Ridership:
    """Validated tables keyed by ``stations`` (station_idx, name) of the network."""
    layout = FORMATS.get(fmt)
    if layout is None:
        raise DemandError(f"unknown ridership format {fmt!r}; known: {', '.join(FORMATS)}")
    if stations["name"].n_unique() != stations.height:
        raise DemandError("network station names are not unique")
    by_name = stations.select("station_idx", pl.col("name"))
    station_cols = [layout.date, layout.hour, layout.station, layout.count]
    tables = []
    for file, column in ((layout.entries, "entries"), (layout.exits, "exits")):
        frame = _read(data_dir / file, station_cols)
        _station_ids(frame[layout.station], stations, file)
        tables.append(
            frame.select(
                pl.col(layout.date).str.to_date().alias("date"),
                pl.col(layout.hour).cast(pl.Int64).alias("hour"),
                pl.col(layout.station).alias("name"),
                pl.col(layout.count).cast(pl.Int64).alias(column),
            )
        )
    keys = ["date", "hour", "name"]
    merged = (
        tables[0]
        .join(tables[1], on=keys, how="full", coalesce=True)
        .with_columns(pl.col("entries").fill_null(0), pl.col("exits").fill_null(0))
    )
    pair_frame = _read(
        data_dir / layout.pairs,
        [layout.date, layout.hour, layout.origin, layout.destination, layout.count],
    )
    for column in (layout.origin, layout.destination):
        _station_ids(pair_frame[column], stations, layout.pairs)
    pairs = (
        pair_frame.select(
            pl.col(layout.date).str.to_date().alias("date"),
            pl.col(layout.hour).cast(pl.Int64).alias("hour"),
            pl.col(layout.origin).alias("from"),
            pl.col(layout.destination).alias("to"),
            pl.col(layout.count).cast(pl.Int64).alias("trips"),
        )
        .join(by_name.rename({"name": "from", "station_idx": "entry_station"}), on="from")
        .join(by_name.rename({"name": "to", "station_idx": "exit_station"}), on="to")
    )
    for frame, what in ((merged, "station ridership"), (pairs, "station-pair ridership")):
        bad = frame.filter((pl.col("hour") < 0) | (pl.col("hour") > 23)).height
        if bad:
            raise DemandError(f"{what}: {bad} rows with an hour outside 0-23")
        value = "trips" if "trips" in frame.columns else "entries"
        negative = frame.filter(pl.col(value) < 0).height
        if "exits" in frame.columns:
            negative += frame.filter(pl.col("exits") < 0).height
        if negative:
            raise DemandError(f"{what}: {negative} negative counts")
    if merged.select(keys).is_duplicated().any():
        raise DemandError("station ridership: duplicate (date, hour, station) rows")
    pair_keys = ["date", "hour", "entry_station", "exit_station"]
    if pairs.select(pair_keys).is_duplicated().any():
        raise DemandError("station-pair ridership: duplicate rows")
    return Ridership(
        stations=merged.join(by_name, on="name")
        .select(
            "date",
            pl.col("hour").cast(pl.UInt8),
            "station_idx",
            pl.col("entries").cast(pl.UInt32),
            pl.col("exits").cast(pl.UInt32),
        )
        .sort("date", "hour", "station_idx"),
        pairs=pairs.select(
            "date",
            pl.col("hour").cast(pl.UInt8),
            "entry_station",
            "exit_station",
            pl.col("trips").cast(pl.UInt32),
        ).sort(pair_keys),
    )


def observed_entries(
    stations: pl.DataFrame, dates: Sequence[date], hours: Sequence[int]
) -> pl.DataFrame:
    """station_idx, observed: mean over ``dates`` of entries summed over ``hours``.

    Every date must be in the data; a station with no row on a date counts zero that day.
    """
    present = set(stations["date"].unique().to_list())
    missing = sorted(d for d in dates if d not in present)
    if missing:
        raise DemandError(
            "calibration dates not in the ridership data: " + ", ".join(map(str, missing))
        )
    window = stations.filter(
        pl.col("date").is_in(list(dates)) & pl.col("hour").is_in([int(h) for h in hours])
    )
    return (
        window.group_by("station_idx")
        .agg((pl.col("entries").cast(pl.Float64).sum() / len(dates)).alias("observed"))
        .sort("station_idx")
    )


def observed_pairs(
    pairs: pl.DataFrame, dates: Sequence[date], hours: Sequence[int]
) -> tuple[pl.DataFrame, list[date]]:
    """entry_station, exit_station, observed: daily mean trips *leaving* in ``hours``.

    In ``vonter-hourly`` the station-pair hour is the exit hour (its per-station hourly sums
    equal the exit counts exactly). Pair data can cover fewer dates than station counts, so
    only the requested dates it has are used; they are returned with the table.
    """
    present = set(pairs["date"].unique().to_list())
    used = sorted(d for d in dates if d in present)
    if not used:
        raise DemandError("no calibration date has station-pair data")
    window = pairs.filter(
        pl.col("date").is_in(used) & pl.col("hour").is_in([int(h) for h in hours])
    )
    table = (
        window.group_by("entry_station", "exit_station")
        .agg((pl.col("trips").cast(pl.Float64).sum() / len(used)).alias("observed"))
        .sort("entry_station", "exit_station")
    )
    return table, used


# --- outputs ----------------------------------------------------------------------------------


class RidershipManifest(BaseModel):
    city: str
    dataset: str
    snapshot: str
    source_checksum_sha256: str
    format: str
    builder_version: str
    nature: DataNature
    first_date: date
    last_date: date
    dates: int
    stations: int
    station_rows: int
    pair_rows: int
    outputs: dict[str, str]


def write_ridership(
    ridership: Ridership,
    out_dir: Path,
    *,
    city: str,
    dataset: str,
    snapshot: str,
    checksum: str,
    fmt: str,
) -> RidershipManifest:
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    outputs = {}
    for name, frame in ((STATIONS_NAME, ridership.stations), (PAIRS_NAME, ridership.pairs)):
        frame.rechunk().write_parquet(staging / name, compression="zstd", statistics=True)
        outputs[name] = sha256_file(staging / name)
    s = ridership.stations
    manifest = RidershipManifest(
        city=city,
        dataset=dataset,
        snapshot=snapshot,
        source_checksum_sha256=checksum,
        format=fmt,
        builder_version=__version__,
        nature=DataNature.OBSERVED,
        first_date=s["date"].min(),
        last_date=s["date"].max(),
        dates=s["date"].n_unique(),
        stations=s["station_idx"].n_unique(),
        station_rows=s.height,
        pair_rows=ridership.pairs.height,
        outputs=outputs,
    )
    (staging / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (staging / REPORT_NAME).write_text(report(manifest, ridership), encoding="utf-8", newline="\n")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rename_with_retry(staging, out_dir)
    return manifest


def report(m: RidershipManifest, ridership: Ridership) -> str:
    daily = (
        ridership.stations.group_by("date")
        .agg(
            pl.col("entries").sum().alias("entries"),
            pl.col("station_idx").n_unique().alias("stations"),
        )
        .join(
            ridership.pairs.group_by("date").agg(pl.col("trips").sum().alias("pair_trips")),
            on="date",
            how="left",
        )
        .sort("date")
    )
    return "\n".join(
        [
            f"# Ridership — `{m.city}` / `{m.dataset}` @ {m.snapshot} (Observed)",
            "",
            f"Builder {m.builder_version} · format `{m.format}` · {m.dates} dates "
            f"({m.first_date} to {m.last_date}) · {m.stations} stations",
            "",
            "Every station name matched a network station. The station-pair hour is the "
            "**exit** hour (per exit station it sums to the exit counts). Days with no "
            "station-pair data show 0.",
            "",
            "| Date | Weekday | Stations | Entries | Station-pair trips |",
            "|---|---|---:|---:|---:|",
            *(
                f"| {r['date']} | {r['date']:%a} | {r['stations']} | {r['entries']:,} | "
                f"{(r['pair_trips'] or 0):,} |"
                for r in daily.iter_rows(named=True)
            ),
            "",
        ]
    )
