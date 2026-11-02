"""NSGA-II over headway vectors (Deb et al. 2002, via pymoo).

Variables are integer indices into the headway set: integer sampling, then simulated binary
crossover and polynomial mutation rounded back to integers (pymoo's recipe for discrete
variables), with duplicate candidates removed. Everything random draws from ``seed``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.repair.rounding import RoundingRepair
from pymoo.operators.sampling.rnd import IntegerRandomSampling
from pymoo.optimize import minimize

from glacies.optimise.problem import Evaluation, HeadwayProblem, pareto_front


@dataclass(frozen=True)
class NsgaResult:
    front: list[Evaluation]  # non-dominated, feasible members of the final population
    generations: int
    candidates: int  # candidates NSGA-II asked for, repeats included
    evaluator_calls: int  # of which the evaluator actually ran (the rest: cache or screen)


def algorithm(population: int) -> NSGA2:
    return NSGA2(
        pop_size=population,
        sampling=IntegerRandomSampling(),
        crossover=SBX(prob=1.0, eta=3.0, vtype=float, repair=RoundingRepair()),
        mutation=PM(prob=1.0, eta=3.0, vtype=float, repair=RoundingRepair()),
        eliminate_duplicates=True,
    )


def run_nsga2(
    problem: HeadwayProblem, *, population: int, generations: int, seed: int
) -> NsgaResult:
    pymoo_problem = problem.pymoo()
    calls_before = problem.evaluator_calls
    result = minimize(
        pymoo_problem,
        algorithm(population),
        ("n_gen", generations),
        seed=seed,
        verbose=False,
        save_history=False,
    )
    final = result.pop.get("X")
    vectors = sorted({tuple(pymoo_problem.headways_of(x)) for x in np.atleast_2d(final)})
    return NsgaResult(
        front=pareto_front([problem.evaluate(list(v)) for v in vectors]),
        generations=int(result.algorithm.n_gen),
        candidates=int(result.algorithm.evaluator.n_eval),
        evaluator_calls=problem.evaluator_calls - calls_before,
    )
