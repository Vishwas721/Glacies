"""Routing benchmarks on the real network (Phase 2 M8).

Measures the router as later phases will use it: building it, one-to-one plans, one-to-all
searches, 120-departure range searches, and parallel range searches over many origins, which
are extrapolated to an all-zones travel-time matrix. Samples are seeded, so the same stops are
used every run; timings naturally vary with the machine.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
import psutil
from pydantic import BaseModel

from glacies.cities import CityConfig
from glacies.routing.network import Router, load_router

WINDOW = np.arange(7 * 3600 + 30 * 60, 9 * 3600 + 30 * 60, 60, dtype=np.uint32)  # 120 min


class Timing(BaseModel):
    name: str
    runs: int
    median_ms: float
    p95_ms: float


class BenchmarkReport(BaseModel):
    cpu_count: int
    router_build_s: float
    rss_after_build_mb: float
    timings: list[Timing]
    parallel_origins: int
    parallel_s: float
    zones: int
    all_zones_estimate_min: float
    peak_rss_mb: float


def _rss_mb() -> float:
    return float(psutil.Process().memory_info().rss) / 2**20


def _time(name: str, calls: list[Callable[[], object]]) -> Timing:
    durations = []
    for call in calls:
        start = time.perf_counter()
        call()
        durations.append((time.perf_counter() - start) * 1000)
    ms = np.array(durations)
    return Timing(
        name=name,
        runs=len(calls),
        median_ms=round(float(np.median(ms)), 2),
        p95_ms=round(float(np.percentile(ms, 95)), 2),
    )


def run(city_dir: Path, config: CityConfig, *, samples: int, seed: int) -> BenchmarkReport:
    start = time.perf_counter()
    router = load_router(city_dir, config.routing, config.city.crs_projected)
    build_s = time.perf_counter() - start
    rss_build = _rss_mb()
    peak = rss_build

    rng = np.random.default_rng(seed)
    served = _served_stops(router)
    origins = rng.choice(served, size=samples, replace=False)
    destinations = rng.choice(served, size=samples, replace=False)
    routing = config.routing
    rounds, transfer = routing.max_rounds, routing.min_transfer_time_s
    zero = np.zeros(1, dtype=np.uint32)

    def one(stop: int) -> npt.NDArray[np.uint32]:
        return np.array([stop], dtype=np.uint32)

    tt = router.timetable
    at_0830 = 8 * 3600 + 1800
    timings = [
        _time(
            "one-to-one plan (08:30)",
            [
                partial(tt.plan, one(o), zero, at_0830, one(d), zero, rounds, transfer)
                for o, d in zip(origins, destinations, strict=True)
            ],
        ),
        _time(
            "one-to-all earliest arrivals (08:30)",
            [
                partial(tt.earliest_arrivals, one(o), zero, at_0830, rounds, transfer)
                for o in origins
            ],
        ),
        _time(
            "range search, 120 departures 07:30-09:29",
            [
                partial(tt.range_arrivals, one(o), zero, WINDOW, rounds, transfer)
                for o in origins[: max(1, samples // 4)]
            ],
        ),
    ]
    peak = max(peak, _rss_mb())

    batch = [(one(o), zero) for o in origins]
    start = time.perf_counter()
    results = router.timetable.range_arrivals_many(batch, WINDOW, rounds, transfer)
    parallel_s = time.perf_counter() - start
    peak = max(peak, _rss_mb())
    del results

    zones = pl.read_parquet(city_dir / "zones" / "zones.parquet", columns=["population"])
    populated = int((zones["population"] > 0).sum())
    estimate_min = parallel_s / len(batch) * populated / 60
    return BenchmarkReport(
        cpu_count=os.cpu_count() or 1,
        router_build_s=round(build_s, 2),
        rss_after_build_mb=round(rss_build),
        timings=timings,
        parallel_origins=len(batch),
        parallel_s=round(parallel_s, 2),
        zones=populated,
        all_zones_estimate_min=round(estimate_min, 1),
        peak_rss_mb=round(peak),
    )


def _served_stops(router: Router) -> npt.NDArray[np.uint32]:
    boarding = router.stops.filter(pl.col("location_type") == 0)["stop_idx"].to_numpy()
    return boarding.astype(np.uint32)


def markdown(report: BenchmarkReport, header: str) -> str:
    rows = "\n".join(
        f"| {t.name} | {t.runs} | {t.median_ms:,.1f} ms | {t.p95_ms:,.1f} ms |"
        for t in report.timings
    )
    return f"""# Routing benchmark

{header}

Machine: {report.cpu_count} logical CPUs. Router build: **{report.router_build_s} s**
(process memory afterwards {report.rss_after_build_mb:,.0f} MB).

| Query | Runs | Median | p95 |
|---|---:|---:|---:|
{rows}

**Parallel range searches:** {report.parallel_origins} origins x 120 departures in
{report.parallel_s} s across all CPUs. Extrapolated to one origin per populated zone
({report.zones:,} zones): **about {report.all_zones_estimate_min} min** for an all-zones
120-minute travel-time matrix (zone access walks add little; Phase 3 measures it for real).
Peak process memory during the run: {report.peak_rss_mb:,.0f} MB.

Targets (docs/phases/02-routing-engine.md §9): one-to-one < 50 ms, one-to-all < 200 ms,
all-zones x 120-min matrix < 30 min with < 8 GB.
"""
