# ADR 0008 — Scenario networks are complete canonical tables

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

Scenario files (ADR 0007) describe changes; something has to turn them into a network the
router, the travel-time matrix and accessibility can use. Those stages read the canonical
transit tables and assume their invariants: dense `*_idx` indices, trips ordered by pattern and
first departure, patterns keyed by route and stop sequence.

## Decision

- `glacies.scenario.mutations.apply(baseline, scenario, defaults)` is a pure function from the
  baseline tables to a complete set of canonical tables. Nothing is written to a database and
  the baseline frames are not modified.
- **Stable where possible.** Stops and routes keep their indices; added routes are appended.
  Patterns and trips are renumbered with the transit build's sort order, so a scenario that
  changes nothing returns tables equal to the baseline (tested on the toy network and on all
  58,258 Bengaluru trips).
- **Generated trips copy real running times.** A trip added by `modify_headway` copies the
  stop-to-stop times of the nearest existing trip of the same pattern (ties: the earlier one),
  keeping the time-of-day congestion in the timetable. A target departure that equals an
  existing one keeps that trip unchanged.
- **Added routes are timed from geometry.** Running time = straight-line distance between
  consecutive stops x `[scenario] detour_factor` / `speed_kmh`, plus `dwell_s` at intermediate
  stops, rounded once on the running total. `detour_factor` is measured by
  `glacies scenario calibrate` (walk distance over straight line for consecutive bus stops).
- **Provenance.** Added routes belong to a synthetic feed (`dataset = "scenario"`,
  `snapshot = scenario_id`, checksum = hash of the mutations). Every generated stop time has
  `time_nature = "assumed"`. New trip ids are derived from their template or route and the
  departure time, never from counters.

## Consequences

- Later stages need no scenario-specific code paths: they read a transit directory.
- Copying running times means a frequency change cannot model the faster running that less
  crowding might bring; that is a separate future mutation (`adjust_speed`).
- The detour factor is calibrated on walking paths, which ignore one-way streets, so it
  slightly understates bus road distance; the mean (not the median) ratio is used for that reason.
