"""Evaluators: route the baseline demand on a scenario network and measure waiting.

``AonEvaluator`` assigns the baseline OD (ADR 0019) all-or-nothing on the fastest journey
(ADR 0017), with no crowding loop: the same journeys and waiting definition as the
assignment's, at a fraction of its cost. Walks, rides to stations and the OD are read once;
headway changes add and remove trips only, never stops, so they stay valid for every
candidate. Each call applies the scenario with the Phase 4 engine and builds a router on it.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import polars as pl

from glacies.assignment.aon import assign_od
from glacies.cities import CityConfig, CityConfigError, load_assignment
from glacies.config import Settings
from glacies.demand.metro import metro_network
from glacies.model.transit.schema import TABLES
from glacies.optimise.problem import Waiting
from glacies.optimise.routes import OptimiseError
from glacies.pipeline import city_dir, demand_settings, demand_walks
from glacies.provenance import sha256_file
from glacies.routing.network import load_router
from glacies.scenario.mutations import apply
from glacies.scenario.schema import Scenario

# Baseline stages the evaluator reads; their manifests go into the cache key.
STAGES = ("transit", "walk", "zones", "demand/baseline")


class AonEvaluator:
    """Total waiting time of the baseline trips, all-or-nothing on a scenario network."""

    def __init__(self, settings: Settings, config: CityConfig) -> None:
        self.config = config
        self.base = city_dir(settings, config)
        for stage in STAGES:
            if not (self.base / stage / "manifest.json").is_file():
                raise OptimiseError(f"missing {self.base / stage}; build the city and demand first")
        try:
            assignment = load_assignment(settings.assignment_config_path)
        except CityConfigError as exc:
            raise OptimiseError(str(exc)) from exc
        self.window = assignment.assignment
        demand, self.mode = demand_settings(settings, config)
        self.tables = {n: pl.read_parquet(self.base / "transit" / f"{n}.parquet") for n in TABLES}
        zones = pl.read_parquet(self.base / "zones" / "zones.parquet").sort("zone_idx")
        router = load_router(self.base, config.routing, config.city.crs_projected)
        self.walks, _ = demand_walks(router, self.base, zones, config, demand, self.mode)
        self.od = pl.read_parquet(self.base / "demand" / "baseline" / "od.parquet")
        self._describe = {
            "method": "aon",
            "stages": {s: sha256_file(self.base / s / "manifest.json") for s in STAGES},
            "demand.toml": sha256_file(settings.demand_config_path),
            "assignment.toml": sha256_file(settings.assignment_config_path),
            "city": config.model_dump(mode="json"),
        }

    def describe(self) -> dict[str, Any]:
        return self._describe

    def __call__(self, scenario: Scenario) -> Waiting:
        applied = apply(self.tables, scenario, self.config.scenario)
        scratch = self.base / "optimise" / "tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        transit = Path(tempfile.mkdtemp(prefix="net-", dir=scratch))
        try:
            for name in TABLES:
                applied.tables[name].write_parquet(transit / f"{name}.parquet")
            router = load_router(
                self.base, self.config.routing, self.config.city.crs_projected, transit_dir=transit
            )
            metro = metro_network(router, transit, self.mode)
        finally:
            shutil.rmtree(transit, ignore_errors=True)
        stop_times = applied.tables["stop_times"].sort("trip_idx", "position")
        flows = assign_od(
            router,
            self.walks,
            self.od,
            stop_times,
            self.window,
            self.config.accessibility.max_travel_time_min * 60,
            metro.metro_trip,
            metro.station,
        )
        od = flows.od.filter(pl.col("transit") > 0)
        return Waiting(
            waiting_hours=float((od["waiting_min"] * od["transit"]).sum()) / 60,
            transit_trips=float(od["transit"].sum()),
        )
