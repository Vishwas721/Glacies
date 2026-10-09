# ADR 0013 — Journey paths drive station flows and define transit pairs

- **Status:** Accepted
- **Date:** 2026-10-09

## Context

Phase 5 calibrates demand against BMRCL ridership, which counts people at fare gates. The
model therefore has to say, for each OD pair, which metro station its trips enter and leave.
Calibration will rebuild the OD matrix for many values of β, so that mapping must be cheap to
reapply. The first station-flow run also showed that 20 % of the "transit" trips had walking
as their fastest journey: short zone pairs within the 2 km walk that the gravity model favours
because they cost little.

## Decision

- **Path table.** `glacies build paths` runs the range search from every transit-served zone
  over the departure window and, for each departure, rebuilds the fastest journey to every
  other served zone that the matrix reaches at the median (Rust: labels kept by the range
  search are valid journeys for earlier departures, so no extra searches are needed). Per pair
  it stores departures reached, walked all the way and using the metro; per metro station
  pair, departures. A metro *segment* (consecutive metro rides joined only by changes inside
  one station) is one entry and one exit. The table does not depend on demand.
- **Walking pairs are not transit demand.** A pair whose fastest journey is on foot at half or
  more of its departures (the same median rule as the cost) is left out of the transit OD
  (`exclude_walk_pairs`, default true). Zones left with no transit pair produce nothing and are
  counted in the demand report.
- **Station flows** = Σ over OD pairs of trips × departures on a station pair ÷ departures
  reached: all-or-nothing on the fastest journey, trips spread evenly over the window, no
  crowding. `glacies build station-flows` is a join and takes seconds.
- Stage order: `tt-matrix` → `paths` → `demand` → `station-flows`. `demand` reads which zones
  have a stop from `paths` instead of loading the router.

## Consequences

- Bengaluru baseline (β = 0.05): 11,352 of 1,515,315 served pairs are walking pairs; dropping
  them removes 760 zones (727,334 people) whose stops reach nothing beyond walking distance at
  the median, and trips fall from 386,504 to 354,386. Mean trip length rises from 8.8 to
  10.1 km. 14.7 % of trips use the metro.
- Station flows ignore crowding and route choice beyond the fastest journey; Phase 6
  assignment replaces them. Departure times are uniform over 07:30–09:30 while ridership is
  counted by tap-in hour 08:00–09:59.
