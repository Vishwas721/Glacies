# ADR 0011 — Scenario comparisons read cached runs and check the direction of change

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

PRD §31 asks that every scenario be compared against a baseline in a table of average travel
time, average waiting, transfers, accessibility and crowding. After Phase 4 the engine has
door-to-door travel-time matrices and accessibility for every run; it has no per-journey
breakdown (waiting, transfers) and no demand (crowding).

## Decision

- `glacies scenario compare <a> <b>` compares two networks, each `baseline` or a scenario file.
  A scenario is located by its cache key under the current code and data (ADR 0009); if that
  run does not exist the command says to run it, rather than picking an older result.
- Nothing is recomputed. Metrics come from the accessibility summaries and zone tables and from
  the travel-time matrices the runs wrote:
  - estimated-jobs share reachable at every threshold, population reachable, the share of
    people below 1 % of jobs, and the Gini index (p50, population-weighted, Simulated);
  - zone pairs connected within 60 and 120 minutes, and the mean p50 door-to-door time over
    pairs connected in both networks, weighted by origin population;
  - trips in the timetable, and zones gaining and losing at the headline.
- **Waiting, transfers and crowding are not reported** until assignment (Phase 6) provides
  per-journey results and demand. The report says so instead of approximating them.
- **Direction check.** When A is the baseline and B a scenario that only added trips, no zone
  value may fall; if it only removed trips, none may rise. The check runs over every zone,
  percentile and threshold and a violation is reported as a failure (it indicates a bug, not a
  finding). Mixed scenarios are not checked.
- The planner's `expected_change` text is printed next to the results, for the PRD's level-5
  (logical plausibility) review.
- Outputs: `comparison.md`, `metrics.parquet`, `zone_deltas.parquet`, `zone_deltas.geoparquet`
  (one hexagon per zone, for QGIS), `delta_map.png` and `comparison.json` (inputs by cache key
  and manifest hash). The map uses the reference diverging pair (blue gain, red loss, grey
  midpoint), each arm validated as an ordinal ramp, and is zoomed to the changed zones.
  Comparing the same inputs twice gives byte-identical files.

## Consequences

- A comparison is always traceable to exact runs, and cheap to regenerate.
- Results are keyed by the last commit that changed engine code (ADR 0009), so a change to
  `src/` or `crates/` means re-running scenarios before comparing them: measured on mains
  power, 97 s for the first scenario (it caches the zone walks) and 40 s for each further one.
  Docs, tests and merges that leave engine code unchanged keep the results.
