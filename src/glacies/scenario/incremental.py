"""Which origins a scenario can affect, so the rest of the matrix is copied from the baseline.

A journey can only change if it boards a trip that differs between the baseline and the
scenario (removed, added or retimed). Until that first boarding a journey uses trips that exist
in both networks over the same stops and walks, so the stop where it boards is also reached in
the baseline, no later. Hence: an origin is unaffected if, in the **baseline**, it reaches no
stop of a changed trip within the time limit of any departure in the window. That set is a
conservative superset of the origins whose rows can change; every other row is identical.

The argument needs the stops and the walk network to be unchanged, and the baseline matrix to
come from the same settings and inputs. ``baseline_matrix`` checks the latter and returns a
reason when it cannot be reused; the runner then recomputes everything.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from glacies import __version__
from glacies.analytics.travel_times import MANIFEST_NAME, MatrixManifest, ZoneWalks
from glacies.cities import CityConfig
from glacies.provenance import sha256_file
from glacies.routing.network import Router

U32 = npt.NDArray[np.uint32]
REACH_CHUNK = 256


def _signatures(tables: Mapping[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per trip: its identity and full timetable as a string, and its stops."""
    trip_id = pl.concat_str(
        pl.col("feed_idx"), pl.col("source_trip_id"), pl.col("piece"), pl.col("route_idx"),
        separator="|",
    )  # fmt: skip
    return (
        tables["stop_times"]
        .sort("trip_idx", "position")
        .group_by("trip_idx", maintain_order=True)
        .agg(
            pl.concat_str("stop_idx", "arrival", "departure", separator=":")
            .str.join(",")
            .alias("_times"),
            pl.col("stop_idx").alias("_stops"),
        )
        .join(tables["trips"].select("trip_idx", trip_id.alias("_trip")), on="trip_idx")
        .select(pl.concat_str("_trip", "_times", separator="#").alias("signature"), "_stops")
    )


def changed_stops(
    baseline: Mapping[str, pl.DataFrame], scenario: Mapping[str, pl.DataFrame]
) -> U32 | None:
    """Stops of trips present in only one of the networks; ``None`` if the stops differ."""
    if not baseline["stops"].equals(scenario["stops"]):
        return None
    a, b = _signatures(baseline), _signatures(scenario)
    only = pl.concat([a.join(b, on="signature", how="anti"), b.join(a, on="signature", how="anti")])
    stops = only.explode("_stops", empty_as_null=False)["_stops"].unique().sort()
    return stops.to_numpy().astype(np.uint32)


def affected_origins(
    baseline_router: Router,
    walks: ZoneWalks,
    stops: U32,
    departures: list[int],
    max_travel_time_s: int,
) -> frozenset[int]:
    """Zone positions that can reach any of ``stops`` in the baseline within the limit.

    One search from the first departure covers the whole window: leaving earlier and waiting
    never arrives later (timetables are FIFO), so any stop reached by a later departure ``d``
    by ``d + limit`` is reached from the first departure by the same time, at most
    ``departures[-1] + limit``.
    """
    if stops.size == 0 or not departures:
        return frozenset()
    routing = baseline_router.routing
    deadline = departures[-1] + max_travel_time_s
    first = np.array([departures[0]], dtype=np.uint32)
    candidates = [i for i, (s, _) in enumerate(walks.access) if s.size]
    affected: list[int] = []
    for start in range(0, len(candidates), REACH_CHUNK):
        batch = candidates[start : start + REACH_CHUNK]
        arrivals = baseline_router.timetable.range_arrivals_many(
            [walks.access[i] for i in batch],
            first,
            routing.max_rounds,
            routing.min_transfer_time_s,
        )
        for origin, arrival in zip(batch, arrivals, strict=True):
            if (arrival[0, stops] <= deadline).any():
                affected.append(origin)
    return frozenset(affected)


def baseline_matrix(base: Path, config: CityConfig) -> tuple[Path | None, str]:
    """The baseline matrix directory if it can be reused, else ``None`` and the reason."""
    directory = base / "tt_matrix" / "baseline"
    path = directory / MANIFEST_NAME
    if not path.is_file():
        return None, "no baseline travel-time matrix (run `glacies build tt-matrix`)"
    manifest = MatrixManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if manifest.builder_version != __version__:
        return None, f"baseline matrix built by {manifest.builder_version}, not {__version__}"
    if manifest.routing != config.routing or manifest.accessibility != config.accessibility:
        return None, "baseline matrix was built with different routing or accessibility settings"
    for item in manifest.inputs:
        current = base / item.stage / MANIFEST_NAME
        if not current.is_file() or sha256_file(current) != item.manifest_sha256:
            return None, f"baseline matrix is older than the current {item.stage} stage"
    for name, digest in manifest.outputs.items():
        part = directory / name
        if not part.is_file() or sha256_file(part) != digest:
            return None, f"baseline matrix file {name} is missing or changed"
    return directory, ""
