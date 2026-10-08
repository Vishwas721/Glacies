# Scenario comparisons — Bengaluru (2026-10-08 runs)

Outputs of `uv run glacies scenario run` and `uv run glacies scenario compare baseline <file>`
for the three Phase 4 demo scenarios (`scenarios/bengaluru/`). All values are **Simulated**;
the job counts behind the shares are **Estimated** (employment proxy, 0.50/0.50 weights); every
scenario parameter (speeds, headways, detour factor 1.15, dwell 20 s) is **Assumed**. Tables
are copied from `data/processed/bengaluru/comparisons/baseline__vs__<scenario>/comparison.md`.

Headline: population-weighted mean share of the city's estimated jobs reachable within 45 min
at the median (p50) departure in the 07:30-09:30 window. Baseline **2.7399 %**.

## Summary

| Scenario | Change | Headline | Zones up / down (45 min, p50) | Direction check |
|---|---|---:|---|---|
| ORR 500-D x2 (`headway_factor` 0.5 on route 1066) | +258 trips | 2.7416 % (+0.0017 pp) | 19 / 0 | passed |
| Remove 304-K (routes 2255, 2256) | -175 trips | 2.7389 % (-0.0010 pp) | 0 / 16 | passed |
| Kundalahalli metro - Eco Space feeder, 20 km/h | +182 trips | 2.7403 % (+0.0004 pp) | 6 / 0 | passed |

The direction check covers every zone, percentile and threshold (127,932 values per
scenario): added service never lowered a value, removed service never raised one.

All three effects are small at city scale, as expected: each touches one corridor that other
routes already serve. They are visible at zone level (up to +0.377 pp and -0.850 pp of the
city's estimated jobs for a single zone).

## Expected vs observed (PRD validation level 5)
### ORR 500-D frequency x2

- **Expected:** gains only; small, because 500-D already runs about every 5 min at peak; along
  the ORR from Central Silk Board through Bellandur, Marathahalli and KR Pura to Hebbal.
- **Observed:** gains only (19 zones at the headline). Most lie along the route; the largest
  is at Marathahalli (12.956, 77.695, +0.377 pp). Several are **off the ORR**, e.g. two central
  zones near 12.95, 77.58 (+0.214 pp each) and two near 13.046, 77.62 in the north: their
  residents reach jobs along the ORR by transferring onto 500-D, so a faster ORR helps them too.
- **Verdict:** matches, with the off-corridor gains explained by transfers.

Run: `b01eba560339`, incremental, commit `f5411f6`

| Metric | A | B | Change |
|---|---:|---:|---:|
| Estimated jobs reachable within 15 min (p50, population-weighted) | 0.0899 % | 0.0899 % | +0.0000 pp |
| Estimated jobs reachable within 30 min (p50, population-weighted) | 0.7642 % | 0.7646 % | +0.0004 pp |
| Estimated jobs reachable within 45 min (p50, population-weighted) | 2.7399 % | 2.7416 % | +0.0017 pp |
| Estimated jobs reachable within 60 min (p50, population-weighted) | 6.9460 % | 6.9505 % | +0.0045 pp |
| Population reachable within 45 min (p50, population-weighted) | 1.6372 % | 1.6382 % | +0.0009 pp |
| Population reaching under 1 % of estimated jobs within 45 min | 59.6173 % | 59.6173 % | +0.0000 pp |
| Gini of estimated-job access within 45 min (0 equal, 1 unequal) | 0.7330 | 0.7330 | +0.0000 |
| Zone pairs connected within 60 min (p50) | 231,766 | 231,821 | +55 |
| Zone pairs connected within 120 min (p50) | 1,559,686 | 1,559,858 | +172 |
| Mean door-to-door time over pairs connected in both (p50, by origin population) | 86.36 | 86.35 | -0.01 |
| Trips in the service-day timetable | 58,258 | 58,516 | +258 |
| Zones gaining access at the headline (45 min, p50) | 0 | 19 | +19 |
| Zones losing access at the headline (45 min, p50) | 0 | 0 | +0 |

### Remove 304-K (duplicates the Purple Line)

- **Expected:** losses only; close to zero city-wide; in zones along Whitefield Main Road (Hope
  Farm to KR Pura) farther than a short walk from a Purple Line station.
- **Observed:** losses only (16 zones). The largest is near KR Pura / Tin Factory (13.001,
  77.688, -0.850 pp); the others follow the route towards Whitefield (e.g. 12.985, 77.763,
  -0.201 pp) and the area north of it. City-wide -0.0010 pp.
- **Verdict:** matches. The Purple Line absorbs most of 304-K's role. Checked afterwards:
  12 of the 16 losing zones are more than 800 m (straight line) from a Purple Line stop, so
  beyond the access walk. The other 4 are close to the line (116-636 m), including the largest
  loss (636 m): for some of their trips 304-K was faster than the metro, which costs a
  4-minute station entry (Assumed) and does not serve every stop the bus does.

Run: `11ab8e12f7b9`, incremental, commit `f5411f6`

| Metric | A | B | Change |
|---|---:|---:|---:|
| Estimated jobs reachable within 15 min (p50, population-weighted) | 0.0899 % | 0.0899 % | +0.0000 pp |
| Estimated jobs reachable within 30 min (p50, population-weighted) | 0.7642 % | 0.7639 % | -0.0002 pp |
| Estimated jobs reachable within 45 min (p50, population-weighted) | 2.7399 % | 2.7389 % | -0.0010 pp |
| Estimated jobs reachable within 60 min (p50, population-weighted) | 6.9460 % | 6.9440 % | -0.0019 pp |
| Population reachable within 45 min (p50, population-weighted) | 1.6372 % | 1.6366 % | -0.0006 pp |
| Population reaching under 1 % of estimated jobs within 45 min | 59.6173 % | 59.6173 % | +0.0000 pp |
| Gini of estimated-job access within 45 min (0 equal, 1 unequal) | 0.7330 | 0.7330 | +0.0000 |
| Zone pairs connected within 60 min (p50) | 231,766 | 231,691 | -75 |
| Zone pairs connected within 120 min (p50) | 1,559,686 | 1,559,280 | -406 |
| Mean door-to-door time over pairs connected in both (p50, by origin population) | 86.35 | 86.36 | +0.01 |
| Trips in the service-day timetable | 58,258 | 58,083 | -175 |
| Zones gaining access at the headline (45 min, p50) | 0 | 0 | +0 |
| Zones losing access at the headline (45 min, p50) | 0 | 16 | +16 |

### Kundalahalli metro - Eco Space feeder

- **Expected:** gains only; localised near the feeder stops between Kundalahalli and Bellandur
  and for trips reaching the corridor by metro; small, because 500-F, V-500F and 500-D already
  serve this road.
- **Observed:** gains only (6 zones), all between Kundalahalli and Marathahalli (largest
  12.956, 77.695, +0.187 pp). **No zone gains on the Marathahalli - Eco Space stretch**, where
  the feeder also runs.
- **Verdict:** partly matches. Gains are where expected near the metro end. On the southern
  stretch the existing ORR buses most likely already give the same or better times, so a
  10-min feeder at 20 km/h adds nothing there (not checked trip by trip). At the earlier 15 km/h only 1 zone gained: the speed assumption
  decides whether the feeder is ever the fastest option.

Run: `39970dcc9c60`, incremental, commit `f5411f6`

| Metric | A | B | Change |
|---|---:|---:|---:|
| Estimated jobs reachable within 15 min (p50, population-weighted) | 0.0899 % | 0.0900 % | +0.0001 pp |
| Estimated jobs reachable within 30 min (p50, population-weighted) | 0.7642 % | 0.7648 % | +0.0006 pp |
| Estimated jobs reachable within 45 min (p50, population-weighted) | 2.7399 % | 2.7403 % | +0.0004 pp |
| Estimated jobs reachable within 60 min (p50, population-weighted) | 6.9460 % | 6.9469 % | +0.0009 pp |
| Population reachable within 45 min (p50, population-weighted) | 1.6372 % | 1.6375 % | +0.0002 pp |
| Population reaching under 1 % of estimated jobs within 45 min | 59.6173 % | 59.6173 % | +0.0000 pp |
| Gini of estimated-job access within 45 min (0 equal, 1 unequal) | 0.7330 | 0.7330 | +0.0000 |
| Zone pairs connected within 60 min (p50) | 231,766 | 231,785 | +19 |
| Zone pairs connected within 120 min (p50) | 1,559,686 | 1,559,845 | +159 |
| Mean door-to-door time over pairs connected in both (p50, by origin population) | 86.36 | 86.36 | +0.00 |
| Trips in the service-day timetable | 58,258 | 58,440 | +182 |
| Zones gaining access at the headline (45 min, p50) | 0 | 6 | +6 |
| Zones losing access at the headline (45 min, p50) | 0 | 0 | +0 |

## Not compared yet

PRD §31 also lists average waiting, transfers and crowding. They need per-journey results and
passenger demand and arrive with assignment (Phase 6). The travel-time matrix stores
door-to-door times only.

## Reproducibility and performance

- Re-running a scenario is a cache hit (2.3 s, mostly start-up). Changing a mutation, the city
  config, the engine code or the data gives a new key; editing titles, docs or tests does not.
- Incremental runs equal full recomputes byte for byte on all 54 Parquet files of each scenario
  (verified at commit de2b867), and repeated comparisons are byte-identical.
- Run times on mains power (16 logical CPUs, 24 GB): full recompute 102 s; incremental 97 s
  for the first scenario after a code change (it computes and caches the zone walks), 40 s for
  each further scenario. Comparisons take 2-3 s. About 3,000 of the 3,465 transit-served
  origins are recomputed per scenario: corridor routes are reachable from most of the city
  within 120 min, so most of the saving comes from the walk cache.
- On battery the same work took 94-555 s; timings should be taken on mains power.
