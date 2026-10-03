# Phase 9 — Advanced Research (backlog)

This is a backlog, not a committed phase. Pick items only after the core demonstration (Phase 7)
works and Phase 8 is either done or consciously skipped. Each item below becomes its own
mini-phase using the same template (research → decisions → milestones → kickoff → DoD).

## Candidate tracks

| Track | What | Research starting points | Prerequisite |
|---|---|---|---|
| **Surrogate models** | ML model predicting optimisation fitness to cut evaluations | Surrogate-assisted evolutionary optimisation; Gaussian processes, gradient-boosted trees; active learning | Phase 8 evaluation archive |
| **Better route choice** | Logit choice over the Pareto journey set; strategy-based assignment | Spiess & Florian 1989; path-size logit | Phase 6 |
| **Uncertainty analysis** | Monte Carlo over Assumed parameters → confidence bands on every metric | Global sensitivity analysis (Sobol, Morris), SALib | Phases 3–6 |
| **Resilience** | Accessibility loss when a line/station fails; criticality ranking | Network vulnerability/criticality literature | Phase 4 |
| **Second city** | Prove city-agnosticism with a city that has an official GTFS (e.g. Helsinki, Portland) | That city's open data portal | Phases 1–7 |
| **Demand improvement** | Multiple purposes/periods, logit mode choice, survey-based priors | Ortúzar & Willumsen; CMP surveys | Phase 5 |
| **Network redesign** | Route generation heuristics beyond frequency | Transit network design problem reviews | Phase 8 |
| **Additional modes** | Suburban rail, feeder autos/shared mobility as access modes | — | Phase 2 |

## How to start one

1. Copy `docs/phases/01-data-foundation.md` as a template to `docs/phases/09x-<track>.md`.
2. Fill in sections 1–5 yourself.
3. Use this generic kickoff prompt:

```text
We are starting an advanced research track for Glacies: docs/phases/09x-<track>.md. Read CLAUDE.md and
that doc. Propose milestones and a validation approach before writing code; keep the deterministic
core untouched unless the doc says otherwise; small Conventional Commits; open a PR per milestone.
```

## Explicitly still out of scope (PRD §70)

Microscopic traffic simulation, GTFS-RT, weather, emissions, vehicle physics, traffic lights,
individual car simulation, full automatic route generation, LLM-first interface, cloud deployment.
Revisiting any of these requires a new ADR explaining why the scope changed.
