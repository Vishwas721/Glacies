"""`glacies scenario run` on the full toy city: cache, invalidation, run.json, determinism."""

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from glacies.analytics.travel_times import load_walks, save_walks, zone_points, zone_walks
from glacies.cities import CityConfig, load_city
from glacies.cli import app
from glacies.config import Settings, get_settings
from glacies.provenance import sha256_file
from glacies.routing.network import load_router, parse_clock
from glacies.scenario.incremental import affected_origins
from glacies.scenario.runner import EngineVersions, RunOutcome, run_scenario
from tests.gtfs_edit import TOY_FEED
from tests.zone_inputs import write_buildings, write_landcover, write_population

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()
CLEAN = EngineVersions(glacies="t", glacies_raptor="t", git_commit="abc", git_dirty=False)


@pytest.fixture
def city(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Toyville built from raw, with a baseline matrix and accessibility."""
    monkeypatch.setenv("GLACIES_CITIES_DIR", str(FIXTURES / "cities"))
    monkeypatch.setenv("GLACIES_CITY", "toyville")
    monkeypatch.setenv("GLACIES_DATA_DIR", str(tmp_path / "data"))
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    sources = {
        "toy_gtfs": shutil.copytree(TOY_FEED, downloads / "toy_feed"),
        "toy_osm": shutil.copy(FIXTURES / "osm" / "toy.osm", downloads / "toy.osm"),
        "toy_population": write_population(downloads / "pop.tif"),
        "toy_landcover": write_landcover(downloads / "lc.tif"),
        "toy_buildings": write_buildings(downloads / "buildings.csv.gz"),
    }
    for name, path in sources.items():
        result = runner.invoke(app, ["ingest", "register", name, str(path), "--snapshot", "v1"])
        assert result.exit_code == 0, result.output
    for command in (["build-city"], ["build", "tt-matrix"], ["build", "accessibility"]):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
    return tmp_path / "data" / "processed" / "toyville"


def write_scenario(
    directory: Path, scenario_id: str, *mutations: dict[str, Any], **extra: Any
) -> Path:
    path = directory / f"{scenario_id}.json"
    data = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "title": "Toy",
        "mutations": list(mutations),
        **extra,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


HALVE = {"type": "modify_headway", "route_id": "R1", "headway_factor": 0.5}
REMOVE = {"type": "remove_route", "route_id": "R1"}


def run(path: Path, config: CityConfig | None = None, **kw: Any) -> RunOutcome:
    settings: Settings = get_settings()
    config = config or load_city(settings.city_config_path)
    return run_scenario(settings, config, path, engine=kw.pop("engine", CLEAN), **kw)


def parquet_fingerprint(directory: Path) -> dict[str, str]:
    return {
        p.relative_to(directory).as_posix(): sha256_file(p)
        for p in sorted(directory.rglob("*.parquet"))
    }


def accessibility(directory: Path) -> pl.DataFrame:
    return pl.read_parquet(directory / "accessibility.parquet")


def test_run_writes_results_and_a_run_record(city: Path, tmp_path: Path) -> None:
    first = run(write_scenario(tmp_path, "halve", HALVE))

    assert not first.cached
    assert first.out_dir == city / "results" / first.record.cache_key
    for stage in ("transit", "tt_matrix", "accessibility"):
        assert (first.out_dir / stage / "manifest.json").is_file()
    record = json.loads((first.out_dir / "run.json").read_text(encoding="utf-8"))
    assert record["scenario_id"] == "halve"
    assert record["mode"] == "incremental"
    assert record["nature"] == "simulated"
    assert [b["stage"] for b in record["baseline"]] == ["transit", "walk", "zones", "attraction"]
    assert {d["dataset"] for d in record["datasets"]} >= {"toy_gtfs", "toy_osm"}
    (change,) = record["changes"]
    assert (change["type"], change["trips_removed"], change["trips_added"]) == (
        "modify_headway",
        0,
        1,
    )
    assert record["engine"] == CLEAN.model_dump()
    assert record["config"]["city"]["id"] == "toyville"
    assert not list((city / "results").glob(".*staging"))


def test_second_run_hits_the_cache(city: Path, tmp_path: Path) -> None:
    path = write_scenario(tmp_path, "halve", HALVE)
    first = run(path)
    second = run(path)
    assert second.cached
    assert second.record == first.record


def test_titles_do_not_invalidate_but_mutations_do(city: Path, tmp_path: Path) -> None:
    first = run(write_scenario(tmp_path, "halve", HALVE))
    retitled = run(write_scenario(tmp_path, "halve", HALVE, title="Another", description="x"))
    assert retitled.cached
    assert retitled.record.cache_key == first.record.cache_key

    changed = run(write_scenario(tmp_path, "halve", {**HALVE, "headway_factor": 0.4}))
    assert not changed.cached
    assert changed.record.cache_key != first.record.cache_key


def test_config_and_engine_changes_invalidate(city: Path, tmp_path: Path) -> None:
    path = write_scenario(tmp_path, "halve", HALVE)
    first = run(path)
    config = load_city(get_settings().city_config_path)
    slower = config.model_copy(
        update={"routing": config.routing.model_copy(update={"walking_speed_m_s": 1.0})}
    )
    assert run(path, slower).record.cache_key != first.record.cache_key
    newer = CLEAN.model_copy(update={"git_commit": "def"})
    assert run(path, engine=newer).record.cache_key != first.record.cache_key


def test_a_dirty_tree_never_reads_the_cache(city: Path, tmp_path: Path) -> None:
    path = write_scenario(tmp_path, "halve", HALVE)
    dirty = CLEAN.model_copy(update={"git_dirty": True})
    assert not run(path, engine=dirty).cached
    assert not run(path, engine=dirty).cached
    assert not run(path, force=True).cached


def test_recomputing_gives_identical_parquet(city: Path, tmp_path: Path) -> None:
    path = write_scenario(tmp_path, "halve", HALVE)
    before = parquet_fingerprint(run(path).out_dir)
    after = parquet_fingerprint(run(path, force=True).out_dir)
    assert before == after
    assert len(before) > 10


def test_a_scenario_that_changes_nothing_reproduces_the_baseline(
    city: Path, tmp_path: Path
) -> None:
    noop = run(write_scenario(tmp_path, "noop", {**HALVE, "headway_factor": 1}))
    scenario = accessibility(noop.out_dir / "accessibility")
    assert scenario.equals(accessibility(city / "accessibility" / "baseline"))


def test_direction_of_change(city: Path, tmp_path: Path) -> None:
    """Adding trips never lowers access; removing the only daytime route never raises it."""
    keys = ["zone_idx", "percentile", "threshold_min"]
    base = accessibility(city / "accessibility" / "baseline").select(*keys, "est_jobs_share")

    def delta(*mutations: dict[str, Any]) -> pl.Series:
        path = write_scenario(tmp_path, f"s{len(list(tmp_path.glob('*.json')))}", *mutations)
        out = accessibility(run(path).out_dir / "accessibility")
        joined = base.join(out.select(*keys, "est_jobs_share"), on=keys, suffix="_s")
        assert joined.height == base.height
        return joined["est_jobs_share_s"] - joined["est_jobs_share"]

    halved, removed = delta(HALVE), delta(REMOVE)
    assert (halved >= 0).all()
    assert (removed <= 0).all()
    assert (removed < 0).sum() > 0  # R1 mattered somewhere


def test_run_command_reports_cache_hits(city: Path, tmp_path: Path) -> None:
    path = write_scenario(tmp_path, "halve", HALVE)
    first = runner.invoke(app, ["scenario", "run", str(path)])
    assert first.exit_code == 0, first.output
    assert "1. modify_headway R1: -0 / +1 trips" in first.output
    assert "halve: headline" in first.output


# --- incremental recomputation (M4) ----------------------------------------------------------

FEEDER = {
    "type": "add_route",
    "route_id": "F",
    "stops": ["A", "C"],
    "headway_secs": 300,
    "span": ["07:30", "09:30"],
    "speed_kmh": 30,
}
CASES: dict[str, list[dict[str, Any]]] = {
    "halve": [HALVE],
    "regular": [{"type": "modify_headway", "route_id": "R1", "headway_secs": 240}],
    "remove": [REMOVE],
    "feeder": [FEEDER],
    "mixed": [REMOVE, FEEDER],
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_incremental_equals_full_recompute(city: Path, tmp_path: Path, case: str) -> None:
    path = write_scenario(tmp_path, case, *CASES[case])
    incremental = run(path)
    assert incremental.record.mode == "incremental"
    fast = parquet_fingerprint(incremental.out_dir)
    full = run(path, full=True)
    assert (full.record.mode, full.record.full_reason) == ("full", "full recompute requested")
    assert parquet_fingerprint(full.out_dir) == fast


def test_only_affected_origins_are_recomputed(city: Path, tmp_path: Path) -> None:
    record = run(write_scenario(tmp_path, "rm", REMOVE)).record
    assert 0 < record.origins_recomputed < record.origins_total
    noop = run(write_scenario(tmp_path, "noop", {**HALVE, "headway_factor": 1})).record
    assert (noop.mode, noop.origins_recomputed) == ("incremental", 0)


def test_falls_back_to_full_without_a_usable_baseline(city: Path, tmp_path: Path) -> None:
    path = write_scenario(tmp_path, "halve", HALVE)
    expected = parquet_fingerprint(run(path, full=True).out_dir)

    part = next((city / "tt_matrix" / "baseline").glob("part-*.parquet"))
    part.write_bytes(part.read_bytes() + b"x")
    tampered = run(path, force=True)
    assert tampered.record.mode == "full"
    assert "missing or changed" in tampered.record.full_reason
    assert parquet_fingerprint(tampered.out_dir) == expected

    shutil.rmtree(city / "tt_matrix" / "baseline")
    missing = run(path, force=True)
    assert "no baseline travel-time matrix" in missing.record.full_reason


def test_reach_uses_the_last_departure_of_the_window(city: Path) -> None:
    """Leaving at 07:50 boards R1 at A at 08:00 and reaches C at 08:06 (16 min): within a
    20-minute limit, so C counts, although from 07:40 it takes 26 min."""
    config = load_city(get_settings().city_config_path)
    router = load_router(city, config.routing, config.city.crs_projected)
    zones = pl.read_parquet(city / "zones" / "zones.parquet")
    walks = zone_walks(router, city / "walk", zone_points(zones), config.accessibility)
    stops = pl.read_parquet(city / "transit" / "stops.parquet")
    idx = dict(zip(stops["source_stop_id"], stops["stop_idx"], strict=True))
    near_a_only = [
        i
        for i, (s, _) in enumerate(walks.access)
        if idx["A"] in s and idx["C"] not in s and idx["B"] not in s
    ]
    assert near_a_only
    c = np.array([idx["C"]], dtype=np.uint32)
    departures = [parse_clock("07:40"), parse_clock("07:50")]
    affected = affected_origins(router, walks, c, departures, 20 * 60)
    assert set(near_a_only) <= affected
    assert not set(near_a_only) & affected_origins(router, walks, c, departures, 15 * 60)


def test_walks_are_cached_across_scenarios(city: Path, tmp_path: Path) -> None:
    first = run(write_scenario(tmp_path, "halve", HALVE)).record
    path = write_scenario(tmp_path, "rm", REMOVE)
    second = run(path)
    assert (first.walks_reused, second.record.walks_reused) == (False, True)
    full = run(path, full=True)
    assert not full.record.walks_reused  # --full recomputes walks too, so it checks the cache
    assert parquet_fingerprint(full.out_dir) == parquet_fingerprint(second.out_dir)
    dirty = CLEAN.model_copy(update={"git_dirty": True})
    assert not run(path, engine=dirty).record.walks_reused


def test_walks_survive_a_round_trip(city: Path, tmp_path: Path) -> None:
    config = load_city(get_settings().city_config_path)
    router = load_router(city, config.routing, config.city.crs_projected)
    zones = pl.read_parquet(city / "zones" / "zones.parquet")
    walks = zone_walks(router, city / "walk", zone_points(zones), config.accessibility)
    assert any(s.size == 0 for s, _ in walks.access)  # zones without stops round-trip too
    save_walks(walks, tmp_path / "walks")
    loaded = load_walks(tmp_path / "walks", zones.height)
    for got, want in ((loaded.access, walks.access), (loaded.walk_only, walks.walk_only)):
        assert len(got) == len(want)
        for (a, b), (c, d) in zip(got, want, strict=True):
            assert a.tolist() == c.tolist()
            assert b.tolist() == d.tolist()
