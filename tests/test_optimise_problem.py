"""The frequency-setting problem on a hand-checkable case (Phase 8 M1, M5).

Two routes, headways {5, 10, 20} min, an evaluator whose waiting time is the textbook half
headway: route 1 carries 100 trips, route 2 carries 60, so waiting (hours) is
(100 h1 + 60 h2) / 2 / 60.

Route 1 runs 10 min of a 20-min round trip (two 5-min layovers) and today every 10 min at
0.6 of capacity; route 2 has a 30-min round trip, every 10 min at 0.3. Vehicles are
ceil(round trip / headway): route 1 needs 4 / 2 / 1, route 2 needs 6 / 3 / 2. The fleet is 7
and the load limit 1.0, so route 1 every 20 min (load 1.2) is never allowed.

| h1, h2 | vehicles | waiting h | |
|---|---:|---:|---|
| 5, 5   | 10 | 6.67  | over the fleet |
| 5, 10  | 7  | 9.17  | front |
| 5, 20  | 6  | 14.17 | beaten by 10, 10 |
| 10, 5  | 8  | 10.83 | over the fleet |
| 10, 10 | 5  | 13.33 | front |
| 10, 20 | 4  | 18.33 | front |
| 20, *  |    |       | over the load limit |
"""

from pathlib import Path
from typing import Any, ClassVar

import pytest

from glacies.optimise.config import Optimise, OptimiseRoute
from glacies.optimise.problem import (
    EvaluationCache,
    HeadwayProblem,
    Waiting,
    baseline_fleet,
    cache_key,
    pareto_front,
)
from glacies.optimise.routes import OptimiseError, RouteFacts
from glacies.optimise.run import run_nsga2
from glacies.scenario.runner import EngineVersions
from glacies.scenario.schema import ModifyHeadway, Scenario

CLEAN = EngineVersions(glacies="t", glacies_raptor="t", git_commit="abc", git_dirty=False)
FRONT = [[10, 20], [10, 10], [5, 10]]

OPTIMISE = Optimise(
    routes=[OptimiseRoute(route_id="R1", label="1"), OptimiseRoute(route_id="R2", label="2")],
    headways_min=[5, 10, 20],
    window=("07:00", "10:00"),
    layover_min=5,
    max_load_factor=1.0,
    fleet_vehicles=7,
)
FACTS = [
    RouteFacts("R1", "1", 0, 2, running_s=600, cycle_s=1200, headway_now_s=600, utilisation=0.6),
    RouteFacts("R2", "2", 1, 2, running_s=1200, cycle_s=1800, headway_now_s=600, utilisation=0.3),
]


class HalfHeadway:
    """Waiting = trips x headway / 2 per route, read back from the scenario's mutations."""

    TRIPS: ClassVar[dict[str, float]] = {"R1": 100.0, "R2": 60.0}

    def __init__(self) -> None:
        self.calls: list[str] = []

    def describe(self) -> dict[str, Any]:
        return {"method": "half-headway"}

    def __call__(self, scenario: Scenario) -> Waiting:
        self.calls.append(scenario.scenario_id)
        minutes = 0.0
        for m in scenario.mutations:
            assert isinstance(m, ModifyHeadway)
            assert m.headway_secs is not None
            minutes += self.TRIPS[m.route_id] * m.headway_secs / 60 / 2
        return Waiting(waiting_hours=minutes / 60, transit_trips=sum(self.TRIPS.values()))


def problem(cache: EvaluationCache | None = None) -> tuple[HeadwayProblem, HalfHeadway]:
    evaluator = HalfHeadway()
    return HeadwayProblem(OPTIMISE, FACTS, evaluator, cache), evaluator


def every_vector() -> list[list[int]]:
    return [[a, b] for a in OPTIMISE.headways_min for b in OPTIMISE.headways_min]


def test_vehicles_and_load_factor_by_hand() -> None:
    r1, r2 = FACTS
    assert [r1.vehicles(h * 60) for h in (5, 10, 20)] == [4, 2, 1]
    assert [r2.vehicles(h * 60) for h in (5, 10, 20)] == [6, 3, 2]
    assert r1.load_factor(1200) == pytest.approx(1.2)
    assert r2.load_factor(300) == pytest.approx(0.15)
    assert baseline_fleet(FACTS) == 2 + 3


def test_screen_by_hand() -> None:
    p, evaluator = problem()
    e = p.screen([10, 20])
    assert e.vehicles == [2, 2]
    assert e.vehicle_hours == pytest.approx(4 * 3.0)  # 07:00-10:00
    assert e.feasible
    assert p.constraints(e) == pytest.approx([4 - 7, 0.6 - 1.0, 0.6 - 1.0])
    assert not p.screen([5, 5]).feasible  # 10 vehicles
    assert not p.screen([20, 5]).feasible  # route 1 at 1.2 of capacity
    assert evaluator.calls == []


def test_infeasible_candidates_never_reach_the_evaluator() -> None:
    p, evaluator = problem()
    for vector in every_vector():
        p.evaluate(vector)
    assert sorted(evaluator.calls) == sorted(
        f"optimise-{a}-{b}" for a, b in ([5, 10], [5, 20], [10, 10], [10, 20])
    )
    assert p.evaluate([5, 5]).waiting_hours is None


def test_brute_force_front_by_hand() -> None:
    p, _ = problem()
    front = pareto_front([p.evaluate(v) for v in every_vector()])
    assert [e.headways_min for e in front] == FRONT
    assert [e.waiting_hours for e in front] == pytest.approx([2200 / 120, 1600 / 120, 1100 / 120])


def test_nsga2_recovers_the_front_and_repeats_itself() -> None:
    fronts = []
    for _ in range(2):
        p, evaluator = problem()
        result = run_nsga2(p, population=4, generations=10, seed=1)
        fronts.append([e.headways_min for e in result.front])
        assert len(set(evaluator.calls)) == len(evaluator.calls)  # each vector evaluated once
    assert fronts[0] == FRONT
    assert fronts[1] == fronts[0]


def test_scenario_is_one_regular_timetable_per_route() -> None:
    p, _ = problem()
    scenario = p.scenario([5, 20])
    assert scenario.scenario_id == "optimise-5-20"
    assert [(m.route_id, m.headway_secs, m.window) for m in scenario.mutations] == [  # type: ignore[union-attr]
        ("R1", 300, ("07:00", "10:00")),
        ("R2", 1200, ("07:00", "10:00")),
    ]
    with pytest.raises(OptimiseError, match="not in the set"):
        p.scenario([5, 7])
    with pytest.raises(OptimiseError, match="expected 2"):
        p.scenario([5])


def test_cache_reuses_evaluations_and_dirty_trees_do_not_read(tmp_path: Path) -> None:
    key = cache_key(OPTIMISE, FACTS, 7, HalfHeadway(), CLEAN, 42)
    first, evaluator = problem(EvaluationCache(tmp_path, key))
    first.evaluate([10, 10])
    again, evaluator = problem(EvaluationCache(tmp_path, key))
    assert again.evaluate([10, 10]) == first.evaluate([10, 10])
    assert evaluator.calls == []
    dirty, evaluator = problem(EvaluationCache(tmp_path, key, read=False))
    dirty.evaluate([10, 10])
    assert evaluator.calls == ["optimise-10-10"]


def test_cache_key_covers_engine_seed_and_config() -> None:
    key = cache_key(OPTIMISE, FACTS, 7, HalfHeadway(), CLEAN, 42)
    assert key == cache_key(OPTIMISE, FACTS, 7, HalfHeadway(), CLEAN, 42)
    other_engine = CLEAN.model_copy(update={"git_commit": "def"})
    other_config = OPTIMISE.model_copy(update={"layover_min": 6})
    assert (
        len(
            {
                key,
                cache_key(OPTIMISE, FACTS, 7, HalfHeadway(), other_engine, 42),
                cache_key(OPTIMISE, FACTS, 7, HalfHeadway(), CLEAN, 43),
                cache_key(other_config, FACTS, 7, HalfHeadway(), CLEAN, 42),
                cache_key(OPTIMISE, FACTS, 8, HalfHeadway(), CLEAN, 42),
            }
        )
        == 5
    )


def test_config_rejects_unsorted_headways_and_too_many_routes() -> None:
    with pytest.raises(ValueError, match="increasing"):
        Optimise.model_validate({**OPTIMISE.model_dump(), "headways_min": [10, 5]})
    routes = [{"route_id": str(i), "label": str(i)} for i in range(6)]
    with pytest.raises(ValueError, match="at most 5"):
        Optimise.model_validate({**OPTIMISE.model_dump(), "routes": routes})
