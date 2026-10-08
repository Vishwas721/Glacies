"""Run a scenario end to end, with a content-addressed result cache (PRD §53).

``run_scenario`` applies the mutations to the baseline network, then rebuilds the travel-time
matrix and accessibility on the scenario network. Results go to
``data/processed/<city>/results/<key>/`` where ``key`` hashes everything that can change them:
the baseline stage manifests, the mutations, the city config, the engine versions and commit,
and the seed. A second run with the same key reuses the directory; changing any input gives a
new key. Titles and descriptions are not part of the key.

A working tree with uncommitted changes never reads the cache, because the commit hash no
longer describes the code; its results are still written (under a key that records the dirty
state) so they can be inspected.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.cities import CityConfig
from glacies.config import Settings
from glacies.fsutil import rename_with_retry
from glacies.model.transit.schema import TABLES
from glacies.model.zones.build import InputRef
from glacies.pipeline import (
    BUILD_NAME,
    CityBuild,
    PipelineError,
    city_dir,
    git_state,
    run_accessibility,
    run_matrix,
)
from glacies.provenance import DataNature, sha256_file
from glacies.scenario.mutations import Change, apply, mutations_sha256
from glacies.scenario.schema import Scenario, load_scenario

KEY_VERSION = 1
RESULTS_DIR = "results"
RUN_NAME = "run.json"
MANIFEST_NAME = "manifest.json"
# Baseline stages a scenario run reads; their manifests identify the baseline in the key.
BASELINE_STAGES = ("transit", "walk", "zones", "attraction")


class EngineVersions(BaseModel):
    glacies: str
    glacies_raptor: str
    git_commit: str | None
    git_dirty: bool | None


class StageInput(BaseModel):
    stage: str
    manifest_sha256: str


class ChangeRecord(BaseModel):
    mutation: int
    type: str
    route_id: str
    trips_removed: int
    trips_added: int


class ScenarioTransitManifest(BaseModel):
    """``transit/manifest.json`` of a scenario network."""

    city: str
    scenario: str
    builder_version: str
    base_transit_manifest_sha256: str
    mutations_sha256: str
    changes: list[ChangeRecord]
    stop_times_by_nature: dict[str, int]
    row_counts: dict[str, int]
    outputs: dict[str, str]


class RunRecord(BaseModel):
    """``run.json``: what a scenario result was computed from (PRD §53)."""

    city: str
    scenario_id: str
    title: str
    scenario_file: str
    scenario_sha256: str
    mutations_sha256: str
    cache_key: str
    key_version: int
    baseline: list[StageInput]
    datasets: list[InputRef]
    engine: EngineVersions
    seed: int
    config: dict[str, Any]
    mode: str
    changes: list[ChangeRecord]
    outputs: list[StageInput]
    headline_est_jobs_share: float
    nature: DataNature
    started_at: str
    finished_at: str
    duration_s: float


@dataclass(frozen=True)
class RunOutcome:
    record: RunRecord
    out_dir: Path
    cached: bool


def engine_versions() -> EngineVersions:
    commit, dirty = git_state(Path(__file__).resolve().parents[3])
    return EngineVersions(
        glacies=__version__,
        glacies_raptor=importlib.metadata.version("glacies-raptor"),
        git_commit=commit,
        git_dirty=dirty,
    )


def baseline_inputs(base: Path) -> list[StageInput]:
    inputs = []
    for stage in BASELINE_STAGES:
        manifest = base / stage / MANIFEST_NAME
        if not manifest.is_file():
            raise PipelineError(f"missing {manifest}; build the city first (`glacies build-city`)")
        inputs.append(StageInput(stage=stage, manifest_sha256=sha256_file(manifest)))
    return inputs


def cache_key(
    scenario: Scenario,
    config: CityConfig,
    baseline: list[StageInput],
    engine: EngineVersions,
    seed: int,
) -> str:
    material = {
        "key_version": KEY_VERSION,
        "city": config.city.id,
        "baseline": [b.model_dump() for b in baseline],
        "mutations_sha256": mutations_sha256(scenario),
        "config": config.model_dump(mode="json"),
        "engine": engine.model_dump(),
        "seed": seed,
    }
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def result_dir(base: Path, key: str) -> Path:
    return base / RESULTS_DIR / key


def run_scenario(
    settings: Settings,
    config: CityConfig,
    path: Path,
    *,
    force: bool = False,
    engine: EngineVersions | None = None,
    on_stage: Callable[[str], None] | None = None,
    on_chunk: Callable[[int, int], None] | None = None,
) -> RunOutcome:
    """Apply, route and measure a scenario, or return the cached result.

    ``engine`` defaults to the installed versions and the git state; tests pass their own.
    """

    def stage(message: str) -> None:
        if on_stage is not None:
            on_stage(message)

    scenario = load_scenario(path)
    base = city_dir(settings, config)
    baseline = baseline_inputs(base)
    engine = engine or engine_versions()
    key = cache_key(scenario, config, baseline, engine, settings.random_seed)
    out_dir = result_dir(base, key)
    if (out_dir / RUN_NAME).is_file() and not force and not engine.git_dirty:
        record = RunRecord.model_validate_json((out_dir / RUN_NAME).read_text(encoding="utf-8"))
        return RunOutcome(record=record, out_dir=out_dir, cached=True)

    started, clock = datetime.now(UTC), time.perf_counter()
    staging = out_dir.with_name(f".{key}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    stage("applying mutations")
    baseline_tables = {n: pl.read_parquet(base / "transit" / f"{n}.parquet") for n in TABLES}
    applied = apply(baseline_tables, scenario, config.scenario)
    changes = [_change_record(c) for c in applied.changes]
    _write_transit(
        applied.tables,
        staging / "transit",
        city=config.city.id,
        scenario=scenario,
        base_manifest=base / "transit" / MANIFEST_NAME,
        changes=changes,
    )
    stage("travel-time matrix")
    matrix = run_matrix(
        settings,
        config,
        scenario=scenario.scenario_id,
        transit_dir=staging / "transit",
        out_dir=staging / "tt_matrix",
        on_chunk=on_chunk,
    )
    stage("accessibility")
    access, _ = run_accessibility(
        settings,
        config,
        scenario=scenario.scenario_id,
        tt_dir=matrix.out_dir,
        out_dir=staging / "accessibility",
    )

    record = RunRecord(
        city=config.city.id,
        scenario_id=scenario.scenario_id,
        title=scenario.title,
        scenario_file=path.as_posix(),
        scenario_sha256=sha256_file(path),
        mutations_sha256=mutations_sha256(scenario),
        cache_key=key,
        key_version=KEY_VERSION,
        baseline=baseline,
        datasets=_datasets(base),
        engine=engine,
        seed=settings.random_seed,
        config=config.model_dump(mode="json"),
        mode="full",
        changes=changes,
        outputs=[
            StageInput(stage=s, manifest_sha256=sha256_file(staging / s / MANIFEST_NAME))
            for s in ("transit", "tt_matrix", "accessibility")
        ],
        headline_est_jobs_share=access.headline_est_jobs_share,
        nature=DataNature.SIMULATED,
        started_at=started.isoformat(timespec="seconds"),
        finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
        duration_s=round(time.perf_counter() - clock, 1),
    )
    (staging / RUN_NAME).write_text(
        record.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    rename_with_retry(staging, out_dir)
    return RunOutcome(record=record, out_dir=out_dir, cached=False)


def _change_record(change: Change) -> ChangeRecord:
    return ChangeRecord(
        mutation=change.mutation,
        type=change.type,
        route_id=change.route_id,
        trips_removed=change.trips_removed,
        trips_added=change.trips_added,
    )


def _datasets(base: Path) -> list[InputRef]:
    """Raw dataset versions behind the baseline, when it was built with ``build-city``."""
    build = base / BUILD_NAME
    if not build.is_file():
        return []
    return CityBuild.model_validate_json(build.read_text(encoding="utf-8")).inputs


def _write_transit(
    tables: dict[str, pl.DataFrame],
    out_dir: Path,
    *,
    city: str,
    scenario: Scenario,
    base_manifest: Path,
    changes: list[ChangeRecord],
) -> None:
    out_dir.mkdir(parents=True)
    outputs: dict[str, str] = {}
    for name in TABLES:
        path = out_dir / f"{name}.parquet"
        tables[name].write_parquet(path, compression="zstd", statistics=True)
        outputs[path.name] = sha256_file(path)
    natures = tables["stop_times"].group_by("time_nature").len().sort("time_nature")
    manifest = ScenarioTransitManifest(
        city=city,
        scenario=scenario.scenario_id,
        builder_version=__version__,
        base_transit_manifest_sha256=sha256_file(base_manifest),
        mutations_sha256=mutations_sha256(scenario),
        changes=changes,
        stop_times_by_nature=dict(natures.iter_rows()),
        row_counts={name: tables[name].height for name in TABLES},
        outputs=outputs,
    )
    (out_dir / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
