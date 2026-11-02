# Frequency optimisation (Phase 8)

How the optimiser's problem was set up and checked. Design: ADR 0026.

## Trunk routes (M1, 2026-11-02)

Candidates were the BMTC routes in the baseline assignment (`assignment/baseline/routes.parquet`,
morning boardings Simulated), with their timetable in the canonical network (Observed). The
five chosen are the busiest that run every 10 minutes or better between 08:00 and 10:00, have
exactly one stop pattern per direction from 07:00 to 10:30, and use different corridors.

`glacies optimise facts` (round trip = mean running time of both directions + 10 min layover at
each end, Assumed; peak-hour load = passenger-km / design capacity-km, 08:30–09:29):

| Route | Corridor | Morning boardings (Simulated) | Every (min) now | Round trip (min) | Vehicles now (Estimated) | Peak-hour load | Headways within the limit |
|---|---|---:|---:|---:|---:|---:|---|
| 378 | Kengeri – Electronic City | 18,693 | 4.3 | 233 | 55 | 0.71 | 3, 5 |
| 401-K | Yelahanka – Kengeri | 13,239 | 6.3 | 278 | 45 | 0.51 | 3, 5, 7, 10 |
| 600-F | Attibele – Banashankari | 10,535 | 5.2 | 221 | 43 | 0.39 | 3, 5, 7, 10 |
| 226-N | Bidadi – Kempegowda Bus Station | 7,804 | 5.5 | 199 | 37 | 0.50 | 3, 5, 7, 10 |
| V-335E | Kadugodi – Kempegowda Bus Station | 9,202 | 8.6 | 211 | 25 | 1.02 | 3, 5, 7 |

Fleet: 205 vehicles (Estimated). As a cross-check, the timetable has 148 of these routes'
buses on the road at 08:45. The difference is the layovers (Assumed) and the busier direction:
today the two directions of a route do not run equally often, while the optimiser regularises
both to one headway.

Left out:

- **Airport and intercity routes** (VV-EXP 298MN, KIA-8, VV-EXP TMK-1, KIA-14, 240-MA) have the
  most passenger-km, but run every 12–24 minutes and reach peak load factors of 14–24. That is
  the bus pile-up found in Phase 6 (riders with a single alternative), not demand the
  optimiser should serve.
- **285-M** (Doddaballapura, 10,320 boardings, every 8.6 min) carries 2.08 times its design
  capacity inbound in the peak hour (the same pile-up pattern). Under the busier-direction
  rule below it could only run every 3 minutes.

The load limit applies to the whole route, not to its busier direction. With the
busier-direction rule (busier-direction loads 0.90, 0.53, 0.46, 0.73 and 1.19) the cheapest
allowed vector, 3/10/10/7/7 min, already needs 189 of the 205 vehicles (378 could only run
every 3 minutes), which leaves almost nothing to trade off.

## Toy brute force (M5, `tests/test_optimise_toy.py`)

Toyville with route 10 (A–B) and route 20 (B–C), each running both ways every 10 minutes
from 06:00 to 11:00, 5 minutes a way and 5 minutes at each end. The headway set is {5, 10, 20}
min and the fleet 7, so 5/5 (8 vehicles) is not allowed. The other eight vectors went through
the scenario engine and an all-or-nothing assignment of Toyville's baseline demand (12.8
transit trips):

| Route 10, route 20 (min) | Vehicle-hours | Waiting (passenger-hours, Simulated) | |
|---|---:|---:|---|
| 5, 5 | 40 | – | over the fleet |
| 5, 10 | 30 | 1.178 | beaten by 10, 5 |
| 5, 20 | 25 | 1.922 | beaten by 10, 10 |
| 10, 5 | 30 | 1.128 | **front** |
| 10, 10 | 20 | 1.339 | **front** |
| 10, 20 | 15 | 2.083 | beaten by 20, 10 |
| 20, 5 | 25 | 1.772 | beaten by 10, 10 |
| 20, 10 | 15 | 1.983 | **front** |
| 20, 20 | 10 | 3.049 | **front** |

NSGA-II (population 6, 15 generations, seed 7) returns exactly these four front vectors and
never the over-fleet one. A rerun with the same seed returns the same front. Waiting never
falls when either route runs less often. In an earlier version of the toy, route 20 ran C–D
and got no riders; there, route 10's mean wait per trip rose by exactly 2.50 min (5 → 10)
and 5.00 min (10 → 20). That is half the change in headway, the textbook random-arrival wait.

The analytic case in `tests/test_optimise_problem.py` (waiting = trips × headway / 2) checks
vehicles, load factors, the screen, the cache and the NSGA-II front by hand.
