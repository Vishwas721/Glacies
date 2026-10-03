# Phase 8 — Optimisation (frequency setting with NSGA-II)

## 1. Goal & why

Go from "evaluate a scenario" to "**search** for good ones": given a fixed fleet, find headways for
up to about 5 trunk routes that trade off passenger waiting time against operating cost, and show the
**Pareto front** rather than one "best" answer. (PRD §34–36, §68)

## 2. Prerequisites

The deterministic pipeline (Phases 2–6) is stable and validated, and a full scenario evaluation
runs in a known time. Only start this phase once that is true.

## 3. Research before starting

- **Deb et al. (2002), *A fast and elitist multiobjective genetic algorithm: NSGA-II***: non-dominated
  sorting, crowding distance, elitism.
- [pymoo](https://pymoo.org/) docs: problem definition, NSGA-II, integer/discrete variables, termination.
- The **transit network frequency-setting problem** literature (e.g. reviews by Ibarra-Rojas et al.
  2015, *Planning, operation, and control of bus transport systems: A literature review*).
- Fleet requirement formula: vehicles = ⌈cycle time / headway⌉ per route.
- Evaluation budget: if one evaluation takes *t* minutes, population × generations × *t* must fit
  in an overnight run. Do the arithmetic before designing.

## 4. Decisions you must make

| Decision | Guidance | Your choice |
|---|---|---|
| Routes in scope | ≤ 5 trunk routes (PRD §36): pick them | |
| Decision variables | headway per route from a discrete set {3,5,7,10,15,20,30} min | |
| Objectives | total passenger waiting time ↓, fleet operating hours ↓ (+ optional accessibility ↑) | |
| Constraints | total vehicles ≤ fleet available on those routes; max load factor | |
| Evaluation fidelity | accessibility-only (fast) vs. full assignment (slow); start fast | |
| Budget | e.g. population 40 × 50 generations; evaluations cached by headway vector | |

## 5. Your hands-on tasks

- [ ] Choose the trunk routes and the current fleet/cycle times for them (Observed from GTFS or Assumed).
- [ ] Run the optimiser overnight; inspect the front. Do the extreme solutions make sense?
- [ ] Pick 2–3 solutions from the front and run them as normal scenarios for the full comparison.

## 6. Agent tasks

1. **M1 — Problem definition**: pymoo `Problem` wrapping the scenario runner (headway vector →
   scenario mutations → metrics); deterministic evaluation; on-disk cache keyed by headway vector.
2. **M2 — Fast evaluator**: a reduced evaluator (subset of origins, accessibility/wait only), with a
   correlation check against the full evaluator.
3. **M3 — NSGA-II runs**: seeded runs, checkpoint/resume, progress logging, results Parquet
   (all evaluated points + front).
4. **M4 — Visualisation**: Pareto front chart (CLI report, then a UI view in the web app) with
   click-through to the scenario.
5. **M5 — Validation**: brute-force a tiny case (2 routes × 3 headways) and confirm NSGA-II finds the
   true front.

## 7. Kickoff prompt

```text
We are starting Phase 8 (Optimisation) of Glacies. Read CLAUDE.md, docs/phases/08-optimisation.md
(with my chosen trunk routes, headway set, objectives, constraints and budget).

Implement milestone M<N> only. Rules:
- the optimiser only generates Phase 4 scenario mutations; it never bypasses the scenario engine;
- evaluations are deterministic, cached and resumable; seeds explicit;
- validate on a brute-forceable toy problem first;
- small Conventional Commits on branch phase/08-m<N>; all checks green; open a PR with the front plot.
```

## 8. Deliverables

`src/glacies/optimise/{problem,evaluator,run}.py`, `docs/validation/optimisation.md`, Pareto UI view.

## 9. Definition of done

- [ ] The toy brute-force front is recovered exactly.
- [ ] A Bengaluru run over ≤ 5 routes completes within the budget and is resumable.
- [ ] The front is displayed; selected solutions re-run as full scenarios with consistent metrics.
- [ ] Constraint violations (fleet, load) are never on the reported front.

## 10. Risks & pitfalls

- **Evaluation cost explosion**: cache, use the reduced evaluator, keep routes ≤ 5.
- **Noisy objectives** from seeded sampling: fix seeds per evaluation and use common random numbers.
- **Overselling**: the front is only as good as the demand model. Show the uncertainty.

**Core:** NSGA-II frequency setting for ≤ 5 routes, Pareto view.
**Later:** ML surrogate for fitness (Phase 9), more routes, timetable synchronisation.
**Never (for now):** whole-network route generation.
