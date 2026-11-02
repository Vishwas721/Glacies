"""Set the problem up for a built city: config, baseline route facts, evaluator and cache."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from glacies.cities import CityConfig, CityConfigError, load_assignment
from glacies.config import Settings
from glacies.model.transit.schema import TABLES
from glacies.optimise.config import Optimise, load_optimise
from glacies.optimise.evaluator import AonEvaluator
from glacies.optimise.problem import EvaluationCache, HeadwayProblem, baseline_fleet, cache_key
from glacies.optimise.routes import OptimiseError, RouteFacts, route_facts
from glacies.pipeline import city_dir
from glacies.scenario.runner import EngineVersions, engine_versions
from glacies.scenario.schema import parse_seconds

OPTIMISE_DIR = "optimise"
CACHE_DIR = "cache"


def city_facts(settings: Settings, config: CityConfig) -> tuple[Optimise, list[RouteFacts]]:
    try:
        optimise = load_optimise(settings.optimise_config_path)
        window = load_assignment(settings.assignment_config_path).assignment
    except CityConfigError as exc:
        raise OptimiseError(str(exc)) from exc
    base = city_dir(settings, config)
    loads = base / "assignment" / "baseline" / "loads.parquet"
    if not loads.is_file():
        raise OptimiseError(f"missing {loads}; run `glacies build assignment` first")
    tables = {n: pl.read_parquet(base / "transit" / f"{n}.parquet") for n in TABLES}
    facts = route_facts(
        tables,
        pl.read_parquet(loads),
        optimise,
        assignment_window=(parse_seconds(window.window_start), parse_seconds(window.window_end)),
        report_window=window.report_window(),
    )
    return optimise, facts


def cache_root(settings: Settings, config: CityConfig) -> Path:
    return city_dir(settings, config) / OPTIMISE_DIR / CACHE_DIR


def city_problem(
    settings: Settings, config: CityConfig, *, engine: EngineVersions | None = None
) -> HeadwayProblem:
    """The city's problem with the all-or-nothing evaluator and the on-disk cache."""
    optimise, facts = city_facts(settings, config)
    evaluator = AonEvaluator(settings, config)
    engine = engine or engine_versions()
    fleet = optimise.fleet_vehicles or baseline_fleet(facts)
    key = cache_key(optimise, facts, fleet, evaluator, engine, settings.random_seed)
    cache = EvaluationCache(cache_root(settings, config), key, read=not engine.git_dirty)
    return HeadwayProblem(optimise, facts, evaluator, cache)
