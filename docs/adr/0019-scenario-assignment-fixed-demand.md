# ADR 0019 — Scenarios re-assign the baseline demand; demand does not respond

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

Phase 6 M5 puts assignment into the scenario runner so comparisons can report PRD §31's
waiting, transfers and crowding. A changed network could also change demand: better service
attracts trips from other modes and to other destinations. Glacies has no mode choice (the
transit share is a prior, `demand.toml`) and its gravity model is calibrated on the baseline
network, so recomputing demand per scenario would mix a real network effect with a model
artefact, and would make scenario results depend on the calibration's weak identification of β.

## Decision

- A scenario run assigns the **baseline OD matrix** (`demand/baseline/od.parquet`) onto the
  scenario network with the same crowding loop, walks and rides to stations as the baseline.
  Differences between baseline and scenario are therefore differences in route choice, crowding,
  waiting and transfers for the same trips.
- The cache key (version 2) includes the baseline demand manifest, `demand.toml` and
  `assignment.toml`; a run made without assignment (`--no-assignment`, or no demand built) has a
  different key and the comparison falls back to it.
- Comparisons add the assignment rows only when both sides have an assignment.

## Consequences

- Scenario comparisons under-state the benefit of improvements that would attract new riders
  and over-state the loss of cuts that would push riders to other modes; reports say so.
- Elastic demand (re-running distribution, or a mode-choice step) would need a new ADR and is
  part of the later demand track (Phase 9).
- A scenario run now takes the travel-time matrix time plus one assignment (minutes).
