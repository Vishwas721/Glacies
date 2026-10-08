"""Apply scenario mutations to the canonical transit tables (PRD §30).

Pure functions on Polars frames: the baseline is never modified and nothing is copied to a
database. The result is a complete canonical network, so the router and every later stage read
it unchanged. Stop and route indices stay stable (added routes are appended); patterns and trips
are renumbered with the transit build's own sort order, so a scenario that changes nothing
returns tables equal to the baseline.

Generated trips copy the stop-to-stop running times of the nearest existing trip of the same
pattern, which keeps the time-of-day congestion the timetable already encodes. Their stop times
are labelled Assumed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import polars as pl

from glacies.cities import ScenarioDefaults
from glacies.model.transit.schema import MODE_BY_ROUTE_TYPE, conform
from glacies.provenance import DataNature
from glacies.scenario.schema import (
    AddRoute,
    ModifyHeadway,
    RemoveRoute,
    Resolved,
    Scenario,
    parse_seconds,
    resolve,
)
from glacies.validate.gtfs.common import haversine_m

SCENARIO_DATASET = "scenario"
GENERATED = DataNature.ASSUMED.value
ROUTE_TYPE_BY_MODE = {mode: route_type for route_type, mode in MODE_BY_ROUTE_TYPE.items()}
OTHER_ROUTE_TYPE = 3  # a mode without a GTFS basic type is stored as bus
_EPS = 1e-9


@dataclass(frozen=True)
class Change:
    """What one mutation did, for the run record and the CLI."""

    mutation: int
    type: str
    route_id: str
    trips_removed: int
    trips_added: int


@dataclass(frozen=True)
class Applied:
    tables: dict[str, pl.DataFrame]
    changes: list[Change]


def hms(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _round(values: npt.NDArray[np.float64]) -> npt.NDArray[np.int64]:
    """Half-up rounding to whole seconds; monotone, so ordered times stay ordered."""
    return np.floor(values + 0.5).astype(np.int64)


def mutations_sha256(scenario: Scenario) -> str:
    """Hash of what the engine applies; titles and descriptions do not change it."""
    payload = [m.model_dump(mode="json") for m in scenario.mutations]
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Network:
    """Mutable working copy of the tables a mutation touches; frames are replaced, not edited."""

    def __init__(self, tables: Mapping[str, pl.DataFrame]) -> None:
        self.tables = dict(tables)
        self.trips = tables["trips"]
        self.stop_times = tables["stop_times"]
        self.next_trip = self.trips.height  # canonical trip indices are dense

    def take_trip_ids(self, count: int) -> list[int]:
        ids = list(range(self.next_trip, self.next_trip + count))
        self.next_trip += count
        return ids

    def drop_trips(self, trip_idx: list[int]) -> None:
        gone = pl.Series(trip_idx, dtype=pl.UInt32)
        self.trips = self.trips.filter(~pl.col("trip_idx").is_in(gone.implode()))
        self.stop_times = self.stop_times.filter(~pl.col("trip_idx").is_in(gone.implode()))

    def add(self, trips: pl.DataFrame, stop_times: pl.DataFrame) -> None:
        self.trips = pl.concat([self.trips, conform("trips", trips)])
        self.stop_times = pl.concat([self.stop_times, conform("stop_times", stop_times)])


def apply(
    baseline: Mapping[str, pl.DataFrame], scenario: Scenario, defaults: ScenarioDefaults
) -> Applied:
    """Apply ``scenario`` to ``baseline`` canonical tables, in mutation order."""
    resolved = resolve(scenario, baseline)
    net = _Network(baseline)
    if any(isinstance(m, AddRoute) for m in scenario.mutations):
        _add_scenario_feed(net, scenario)
    changes: list[Change] = []
    for n, mutation in enumerate(scenario.mutations, start=1):
        if isinstance(mutation, RemoveRoute):
            removed, added = _remove_route(net, resolved.route_idx[mutation.route_id]), 0
        elif isinstance(mutation, ModifyHeadway):
            removed, added = _modify_headway(net, resolved.route_idx[mutation.route_id], mutation)
        else:
            removed, added = 0, _add_route(net, mutation, resolved, defaults)
        changes.append(Change(n, mutation.type, mutation.route_id, removed, added))
    return Applied(tables=_renumber(net), changes=changes)


def _add_scenario_feed(net: _Network, scenario: Scenario) -> None:
    """Added routes belong to a feed named after the scenario, so their provenance is visible."""
    feeds, services = net.tables["feeds"], net.tables["services"]
    feed_idx = feeds.height
    net.tables["feeds"] = pl.concat(
        [
            feeds,
            conform(
                "feeds",
                pl.DataFrame(
                    {
                        "feed_idx": [feed_idx],
                        "dataset": [SCENARIO_DATASET],
                        "snapshot": [scenario.scenario_id],
                        "checksum_sha256": [mutations_sha256(scenario)],
                    }
                ),
            ),
        ]
    )
    net.tables["services"] = pl.concat(
        [
            services,
            conform(
                "services",
                pl.DataFrame(
                    {
                        "service_idx": [services.height],
                        "feed_idx": [feed_idx],
                        "source_service_id": [scenario.scenario_id],
                    }
                ),
            ),
        ]
    )


def _remove_route(net: _Network, route_idx: int) -> int:
    gone = net.trips.filter(pl.col("route_idx") == route_idx)["trip_idx"].to_list()
    net.drop_trips(gone)
    return len(gone)


def _sequences(trips: pl.DataFrame, stop_times: pl.DataFrame) -> pl.DataFrame:
    """Per trip: its stop sequence as a sortable key and its first departure."""
    return (
        stop_times.join(trips.select("trip_idx"), on="trip_idx", how="semi")
        .sort("trip_idx", "position")
        .group_by("trip_idx", maintain_order=True)
        .agg(
            pl.col("stop_idx").cast(pl.String).str.join(",").alias("_key"),
            pl.col("departure").first().cast(pl.Int64).alias("_first"),
        )
    )


def _modify_headway(net: _Network, route_idx: int, m: ModifyHeadway) -> tuple[int, int]:
    """Rewrite the departures of each pattern of the route inside the window."""
    route_trips = net.trips.filter(pl.col("route_idx") == route_idx)
    seq = _sequences(route_trips, net.stop_times)
    if m.window is not None:
        start, end = parse_seconds(m.window[0]), parse_seconds(m.window[1])
        seq = seq.filter((pl.col("_first") >= start) & (pl.col("_first") < end))
    removed: list[int] = []
    copies: list[tuple[int, int]] = []  # (template trip_idx, new first departure)
    for key in sorted(seq["_key"].unique().to_list()):
        group = seq.filter(pl.col("_key") == key).sort("_first", "trip_idx")
        trip_ids = group["trip_idx"].to_list()
        deps = group["_first"].to_numpy().astype(np.float64)
        keep, new = _new_departures(deps, m)
        removed += [t for i, t in enumerate(trip_ids) if i not in keep]
        copies += [(trip_ids[_nearest(deps, d)], d) for d in new]
    _copy_trips(net, copies)  # before dropping: removed trips can still be templates
    net.drop_trips(removed)
    return len(removed), len(copies)


def _new_departures(deps: npt.NDArray[np.float64], m: ModifyHeadway) -> tuple[set[int], list[int]]:
    """Indices of departures kept as they are, and new departures to generate.

    A target time equal to an existing departure keeps that trip, so a factor of 1, or a
    regular headway equal to the current one, changes nothing.
    """
    n = len(deps)
    if m.headway_factor is not None:
        if n < 2:
            return set(range(n)), []
        # Departure "position" k*f on the piecewise-linear curve through (i, deps[i]): every
        # gap is multiplied by f, so the timetable keeps its shape.
        steps = int(np.floor((n - 1) / m.headway_factor + _EPS))
        positions = np.arange(steps + 1, dtype=np.float64) * m.headway_factor
        on_trip = np.abs(positions - np.round(positions)) < _EPS
        keep = {round(p) for p in positions[on_trip]}
        times = _round(np.interp(positions[~on_trip], np.arange(n), deps))
        return keep, sorted({int(t) for t in times})
    assert m.headway_secs is not None  # guaranteed by the schema
    if n == 0:
        return set(), []
    targets = np.arange(deps[0], deps[-1] + _EPS, m.headway_secs).astype(np.int64)
    existing = {int(d): i for i, d in reversed(list(enumerate(deps)))}  # first trip per time
    keep = {existing[int(t)] for t in targets if int(t) in existing}
    return keep, [int(t) for t in targets if int(t) not in existing]


def _nearest(deps: npt.NDArray[np.float64], t: int) -> int:
    """Index of the departure closest in time to ``t``; ties go to the earlier trip."""
    return int(np.argmin(np.abs(deps - t)))


def _copy_trips(net: _Network, copies: list[tuple[int, int]]) -> None:
    if not copies:
        return
    plan = pl.DataFrame(
        {
            "_template": [c[0] for c in copies],
            "_departure": [c[1] for c in copies],
            "_new": net.take_trip_ids(len(copies)),
            "_suffix": [f"@{hms(c[1])}" for c in copies],
        },
        schema={
            "_template": pl.UInt32,
            "_departure": pl.Int64,
            "_new": pl.UInt32,
            "_suffix": pl.String,
        },
    )
    first = net.stop_times.filter(pl.col("position") == 0).select(
        pl.col("trip_idx").alias("_template"), pl.col("departure").cast(pl.Int64).alias("_t0")
    )
    plan = plan.join(first, on="_template").with_columns(
        (pl.col("_departure") - pl.col("_t0")).alias("_shift")
    )
    trips = (
        net.trips.rename({"trip_idx": "_template"})
        .join(plan, on="_template")
        .with_columns(
            pl.col("_new").alias("trip_idx"),
            (pl.col("source_trip_id") + pl.col("_suffix")).alias("source_trip_id"),
        )
    )
    stop_times = (
        net.stop_times.rename({"trip_idx": "_template"})
        .join(plan.select("_template", "_new", "_shift"), on="_template")
        .with_columns(
            pl.col("_new").alias("trip_idx"),
            (pl.col("arrival").cast(pl.Int64) + pl.col("_shift")).alias("arrival"),
            (pl.col("departure").cast(pl.Int64) + pl.col("_shift")).alias("departure"),
            pl.lit(GENERATED).alias("time_nature"),
        )
    )
    net.add(trips, stop_times)


def _add_route(net: _Network, m: AddRoute, resolved: Resolved, defaults: ScenarioDefaults) -> int:
    routes = net.tables["routes"]
    route_idx = routes.height  # canonical route indices are dense
    feed_idx = net.tables["feeds"].height - 1
    service_idx = net.tables["services"].height - 1
    net.tables["routes"] = pl.concat(
        [
            routes,
            conform(
                "routes",
                pl.DataFrame(
                    {
                        "route_idx": [route_idx],
                        "feed_idx": [feed_idx],
                        "source_route_id": [m.route_id],
                        "short_name": [m.route_id],
                        "long_name": [m.name or ""],
                        "route_number": [m.route_id],
                        "route_type": [ROUTE_TYPE_BY_MODE.get(m.mode, OTHER_ROUTE_TYPE)],
                        "mode": [m.mode],
                    }
                ),
            ),
        ]
    )
    dwell = defaults.dwell_s if m.dwell_secs is None else m.dwell_secs
    first, last = parse_seconds(m.span[0]), parse_seconds(m.span[1])
    departures = list(range(first, last + 1, m.headway_secs))
    stops = net.tables["stops"]
    added = 0
    for direction, stop_ids in enumerate(m.directions()):
        idx = [resolved.stop_idx[s] for s in stop_ids]
        arrive, depart = _run_profile(stops, idx, m.speed_kmh, defaults.detour_factor, dwell)
        headsign = stops.filter(pl.col("stop_idx") == idx[-1])["name"][0]
        trip_ids = net.take_trip_ids(len(departures))
        trips = pl.DataFrame(
            {
                "trip_idx": trip_ids,
                "pattern_idx": [0] * len(trip_ids),  # assigned by _renumber
                "route_idx": route_idx,
                "service_idx": service_idx,
                "feed_idx": feed_idx,
                "source_trip_id": [f"{m.route_id}:{direction}:{hms(d)}" for d in departures],
                "piece": 0,
                "headsign": headsign,
                "direction_id": direction,
            }
        )
        stop_times = pl.DataFrame(
            {
                "trip_idx": np.repeat(trip_ids, len(idx)),
                "position": np.tile(np.arange(len(idx)), len(departures)),
                "stop_idx": np.tile(idx, len(departures)),
                "arrival": (np.add.outer(departures, arrive)).ravel(),
                "departure": (np.add.outer(departures, depart)).ravel(),
                "time_nature": GENERATED,
            }
        )
        net.add(trips, stop_times)
        added += len(trip_ids)
    return added


def _run_profile(
    stops: pl.DataFrame, idx: list[int], speed_kmh: float, detour: float, dwell: int
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """Arrival and departure offsets from the first departure, in whole seconds."""
    coords = pl.DataFrame({"stop_idx": idx}, schema={"stop_idx": pl.UInt32}).join(
        stops.select("stop_idx", "lat", "lon"), on="stop_idx", how="left", maintain_order="left"
    )
    hops = (
        coords.select(
            haversine_m(
                pl.col("lat"), pl.col("lon"), pl.col("lat").shift(-1), pl.col("lon").shift(-1)
            )
        )
        .to_series()[:-1]
        .to_numpy()
    )
    ride = hops * detour / (speed_kmh / 3.6)
    # Dwell at every intermediate stop; none at the first (departure) or last (arrival).
    dwells = np.full(len(idx), float(dwell))
    dwells[[0, -1]] = 0.0
    arrive = np.concatenate([[0.0], np.cumsum(ride + dwells[:-1])])
    depart = arrive + dwells
    return _round(arrive), _round(depart)


def _renumber(net: _Network) -> dict[str, pl.DataFrame]:
    """Rebuild patterns and dense trip indices exactly as the transit build orders them."""
    seq = _sequences(net.trips, net.stop_times)
    trips = net.trips.join(seq, on="trip_idx")
    patterns = (
        trips.select("route_idx", "_key")
        .unique()
        .sort("route_idx", "_key")
        .with_row_index("pattern_idx")
    )
    trips = (
        trips.drop("pattern_idx")
        .join(patterns, on=["route_idx", "_key"])
        .sort("pattern_idx", "_first", "feed_idx", "source_trip_id", "piece")
        .with_row_index("_trip")
    )
    old_to_new = trips.select("trip_idx", "_trip")
    stop_times = (
        net.stop_times.join(old_to_new, on="trip_idx")
        .drop("trip_idx")
        .rename({"_trip": "trip_idx"})
        .sort("trip_idx", "position")
    )
    pattern_stops = (
        patterns.join(
            trips.unique("pattern_idx", keep="first").select("pattern_idx", "trip_idx"),
            on="pattern_idx",
        )
        .join(net.stop_times.select("trip_idx", "position", "stop_idx"), on="trip_idx")
        .sort("pattern_idx", "position")
    )
    patterns = pattern_stops.group_by("pattern_idx", maintain_order=True).agg(
        pl.col("route_idx").first(), pl.len().alias("stop_count")
    )
    trips = trips.drop("trip_idx").rename({"_trip": "trip_idx"})
    return net.tables | {
        "patterns": conform("patterns", patterns),
        "pattern_stops": conform("pattern_stops", pattern_stops),
        "trips": conform("trips", trips),
        "stop_times": conform("stop_times", stop_times),
    }
