"""The frequency-setting problem: a headway per trunk route -> objectives and constraints.

A candidate is a vector of headways from the configured set. It becomes an ordinary scenario
(one ``modify_headway`` per route, Phase 4), so the optimiser never edits a network itself.

- Objective 1, total passenger waiting time (passenger-hours, Simulated), comes from an
  evaluator that routes the baseline demand on the scenario network.
- Objective 2, fleet operating hours (Estimated), is the vehicles each route needs
  (``ceil(round trip / headway)``) times the length of the changed window.
- Constraints: total vehicles within the fleet, and each route's estimated peak-hour load
  factor within the limit. Both are arithmetic, so a candidate that breaks them is never
  sent to the evaluator; NSGA-II's constraint domination keeps it off the front.

Evaluations are deterministic and cached on disk, one JSON file per headway vector, under a
key that covers everything the result depends on.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel
from pymoo.core.problem import ElementwiseProblem

from glacies.optimise.config import Optimise
from glacies.optimise.routes import OptimiseError, RouteFacts
from glacies.provenance import DataNature
from glacies.scenario.runner import EngineVersions
from glacies.scenario.schema import ModifyHeadway, Scenario

CACHE_VERSION = 1
# Objective value for a candidate that breaks a constraint and was not evaluated. NSGA-II
# ranks such candidates by constraint violation alone, so the value only has to be finite.
NOT_EVALUATED = 1e12


@dataclass(frozen=True)
class Waiting:
    """What an evaluator measures on one scenario network (Simulated)."""

    waiting_hours: float  # first and transfer waits of every transit trip, passenger-hours
    transit_trips: float


class Evaluator(Protocol):
    def describe(self) -> dict[str, Any]:
        """Everything the evaluator's results depend on besides the scenario (for the key)."""
        ...

    def __call__(self, scenario: Scenario) -> Waiting: ...


class Evaluation(BaseModel):
    """One headway vector, evaluated or rejected by the constraints."""

    headways_min: list[int]
    vehicles: list[int]  # Estimated
    fleet_vehicles: int  # Estimated from the baseline, or stated in optimise.toml
    vehicle_hours: float  # Estimated
    load_factors: list[float]  # Estimated
    feasible: bool
    waiting_hours: float | None = None  # Simulated; None when not evaluated
    transit_trips: float | None = None
    seconds: float | None = None  # wall time of the evaluator call that produced it
    nature: dict[str, DataNature] = {
        "vehicles": DataNature.ESTIMATED,
        "vehicle_hours": DataNature.ESTIMATED,
        "load_factors": DataNature.ESTIMATED,
        "waiting_hours": DataNature.SIMULATED,
    }

    def objectives(self) -> tuple[float, float]:
        waiting = self.waiting_hours if self.waiting_hours is not None else NOT_EVALUATED
        return waiting, self.vehicle_hours


def vector_name(headways_min: Sequence[int]) -> str:
    return "-".join(str(h) for h in headways_min)


class EvaluationCache:
    """``<root>/<key>/<vector>.json``. A dirty working tree writes but never reads, because the
    commit no longer describes the code (as the scenario cache does)."""

    def __init__(self, root: Path, key: str, *, read: bool = True) -> None:
        self.dir = root / key
        self.read = read

    def get(self, headways_min: Sequence[int]) -> Evaluation | None:
        path = self.dir / f"{vector_name(headways_min)}.json"
        if not self.read or not path.is_file():
            return None
        return Evaluation.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, evaluation: Evaluation) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{vector_name(evaluation.headways_min)}.json"
        staging = path.with_suffix(".tmp")
        staging.write_text(evaluation.model_dump_json(indent=2) + "\n", "utf-8", newline="\n")
        staging.replace(path)  # a killed run never leaves half a file behind


def cache_key(
    optimise: Optimise,
    facts: Sequence[RouteFacts],
    fleet: int,
    evaluator: Evaluator,
    engine: EngineVersions,
    seed: int,
) -> str:
    material = {
        "cache_version": CACHE_VERSION,
        "optimise": optimise.model_dump(mode="json"),
        "facts": [asdict(f) for f in facts],
        "fleet": fleet,
        "evaluator": evaluator.describe(),
        "engine": engine.model_dump(),
        "seed": seed,
    }
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class HeadwayProblem:
    """Headway vectors -> evaluations, through the scenario engine and the cache."""

    def __init__(
        self,
        optimise: Optimise,
        facts: Sequence[RouteFacts],
        evaluator: Evaluator,
        cache: EvaluationCache | None = None,
    ) -> None:
        if len(facts) != len(optimise.routes):
            raise OptimiseError("one RouteFacts per configured route is needed")
        self.optimise = optimise
        self.facts = list(facts)
        self.evaluator = evaluator
        self.cache = cache
        self.fleet = optimise.fleet_vehicles or baseline_fleet(self.facts)
        start, end = optimise.window_s()
        self.window_hours = (end - start) / 3600
        self.evaluator_calls = 0
        self._memo: dict[tuple[int, ...], Evaluation] = {}

    @property
    def headways(self) -> list[int]:
        return self.optimise.headways_min

    def scenario(self, headways_min: Sequence[int]) -> Scenario:
        """The Phase 4 scenario for a headway vector: one regular timetable per route."""
        self._check(headways_min)
        return Scenario(
            schema_version=1,
            scenario_id=f"optimise-{vector_name(headways_min)}",
            title="Headways "
            + ", ".join(
                f"{f.label} every {h} min" for f, h in zip(self.facts, headways_min, strict=True)
            ),
            description="Generated by the frequency optimiser (Phase 8).",
            mutations=[
                ModifyHeadway(
                    type="modify_headway",
                    route_id=r.route_id,
                    feed=r.feed,
                    headway_secs=h * 60,
                    window=self.optimise.window,
                )
                for r, h in zip(self.optimise.routes, headways_min, strict=True)
            ],
        )

    def screen(self, headways_min: Sequence[int]) -> Evaluation:
        """The arithmetic part: vehicles, operating hours, load factors and feasibility."""
        self._check(headways_min)
        vehicles = [f.vehicles(h * 60) for f, h in zip(self.facts, headways_min, strict=True)]
        loads = [f.load_factor(h * 60) for f, h in zip(self.facts, headways_min, strict=True)]
        feasible = sum(vehicles) <= self.fleet and all(
            lf <= self.optimise.max_load_factor + 1e-9 for lf in loads
        )
        return Evaluation(
            headways_min=list(headways_min),
            vehicles=vehicles,
            fleet_vehicles=self.fleet,
            vehicle_hours=sum(vehicles) * self.window_hours,
            load_factors=loads,
            feasible=feasible,
        )

    def evaluate(self, headways_min: Sequence[int]) -> Evaluation:
        """Screen, then (if feasible and not cached) run the evaluator."""
        known = self._memo.get(tuple(headways_min))
        if known is not None:
            return known
        if self.cache is not None:
            cached = self.cache.get(headways_min)
            if cached is not None:
                self._memo[tuple(headways_min)] = cached
                return cached
        evaluation = self.screen(headways_min)
        if evaluation.feasible:
            clock = time.perf_counter()
            waiting = self.evaluator(self.scenario(headways_min))
            self.evaluator_calls += 1
            evaluation = evaluation.model_copy(
                update={
                    "waiting_hours": waiting.waiting_hours,
                    "transit_trips": waiting.transit_trips,
                    "seconds": round(time.perf_counter() - clock, 3),
                }
            )
        if self.cache is not None:
            self.cache.put(evaluation)
        self._memo[tuple(headways_min)] = evaluation
        return evaluation

    def constraints(self, evaluation: Evaluation) -> list[float]:
        """pymoo inequality constraints (<= 0 is satisfied): fleet, then one per route."""
        limit = self.optimise.max_load_factor
        return [
            float(sum(evaluation.vehicles) - self.fleet),
            *(lf - limit for lf in evaluation.load_factors),
        ]

    def pymoo(self) -> PymooProblem:
        return PymooProblem(self)

    def _check(self, headways_min: Sequence[int]) -> None:
        if len(headways_min) != len(self.facts):
            raise OptimiseError(f"expected {len(self.facts)} headways, got {len(headways_min)}")
        unknown = sorted(set(headways_min) - set(self.headways))
        if unknown:
            raise OptimiseError(f"headways {unknown} are not in the set {self.headways}")


def baseline_fleet(facts: Sequence[RouteFacts]) -> int:
    """Vehicles the routes need today at their current headways (Estimated)."""
    return sum(f.vehicles(f.headway_now_s) for f in facts)


class PymooProblem(ElementwiseProblem):  # type: ignore[misc]
    """Integer variables: the index of each route's headway in the configured set."""

    def __init__(self, problem: HeadwayProblem) -> None:
        self.problem = problem
        n = len(problem.facts)
        super().__init__(
            n_var=n,
            n_obj=2,
            n_ieq_constr=1 + n,
            xl=np.zeros(n),
            xu=np.full(n, len(problem.headways) - 1),
            vtype=int,
        )

    def headways_of(self, x: npt.ArrayLike) -> list[int]:
        return [self.problem.headways[round(float(v))] for v in np.asarray(x).ravel()]

    def _evaluate(
        self, x: npt.NDArray[np.float64], out: dict[str, Any], *args: Any, **kwargs: Any
    ) -> None:
        evaluation = self.problem.evaluate(self.headways_of(x))
        out["F"] = list(evaluation.objectives())
        out["G"] = self.problem.constraints(evaluation)


def pareto_front(evaluations: Sequence[Evaluation]) -> list[Evaluation]:
    """Feasible, evaluated candidates that no other one beats on both objectives, cheapest
    first. Ties (equal objectives) all stay, so a front compares as a set of vectors."""
    done = [e for e in evaluations if e.feasible and e.waiting_hours is not None]
    front = [
        e
        for e in done
        if not any(
            o.objectives()[0] <= e.objectives()[0]
            and o.objectives()[1] <= e.objectives()[1]
            and o.objectives() != e.objectives()
            for o in done
        )
    ]
    return sorted(front, key=lambda e: (e.vehicle_hours, e.objectives()[0], e.headways_min))
