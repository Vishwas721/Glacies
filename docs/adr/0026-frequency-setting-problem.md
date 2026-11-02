# ADR 0026 — Frequency setting: five trunk routes, two objectives, arithmetic constraints

- **Status:** Accepted
- **Date:** 2026-11-02

## Context

Phase 8 searches for headways on up to five trunk routes (PRD §34–36) with NSGA-II and shows
the Pareto front. One full scenario run (travel-time matrix for the affected origins,
accessibility, assignment with crowding) took 197–1,160 s on the development laptop for
single-change scenarios, so the 2,000 evaluations of a 40 × 50 NSGA-II run would take
110–640 hours. All-or-nothing assignment of every origin took 122–302 s in Phase 6.

## Decision

- **Routes** (`cities/bengaluru/optimise.toml`): 378, 401-K, 600-F, 226-N and V-335E. They
  are the BMTC routes with the most simulated morning boardings that run every 10 minutes or
  better, have one stop pattern per direction and use different corridors. Routes with more
  passenger-km (airport, intercity, 285-M) were left out: their simulated peak loads (14–24
  times capacity on the busiest segment, or 2.08 over the inbound route on 285-M) are the
  Phase 6 bus pile-up, not demand.
- **Variables:** one headway per route from {3, 5, 7, 10, 15, 20, 30} min, applied as a
  Phase 4 `modify_headway` (regular departures, both directions, 07:00–10:30). The optimiser
  only writes scenarios.
- **Objectives:** total passenger waiting time (first and transfer waits of the baseline
  trips, passenger-hours, Simulated) and fleet operating hours (vehicles × window length,
  Estimated). Accessibility is reported for chosen solutions, not optimised, so the front stays
  a two-dimensional trade-off a planner can read.
- **Vehicles** = ceil(round trip / headway), the round trip being the mean timetabled running
  time of both directions (Observed) plus 10 minutes at each terminal (Assumed). The **fleet**
  is what the five routes need today (205, Estimated).
- **Load limit:** a route's peak-hour passenger-km over design capacity-km, held at its
  baseline riders and scaled by new / current headway, must stay ≤ 1.0 (Estimated). Limiting
  the busier direction or the 90th-percentile segment instead leaves almost no feasible vector
  with today's fleet, because of the same pile-up.
- **Constraints are arithmetic** and are checked before the evaluator runs; a candidate that
  breaks one is never routed, and NSGA-II's constraint domination keeps it off the front.
- **Evaluator:** all-or-nothing assignment of the baseline OD (ADRs 0017, 0019) on the
  scenario network; walks and rides to stations are computed once, because headway changes
  never move stops. Phase 8 M2 adds an origin sample sized to the budget and checks it
  against full scenario runs.
- **Cache:** one JSON file per headway vector under a key that hashes the optimiser config, the
  route facts, the fleet, the evaluator's inputs (baseline manifests, demand and assignment
  settings, city config), the engine commit and the seed. A dirty working tree writes but never
  reads it, as the scenario cache does.
- **NSGA-II** from pymoo (Apache-2.0): integer sampling, simulated binary crossover and
  polynomial mutation with distribution index 3, rounded to integers, duplicates removed. With
  the textbook values (15 and 20) the offspring of a small integer space repeat their parents
  and the population collapses.

## Consequences

- The load limit is a maximum headway per route (378 ≤ 5, V-335E ≤ 7, the others ≤ 10 min), so
  only 2 × 4 × 4 × 4 × 3 = 384 vectors are allowed before the fleet check. The cache bounds a
  run at 384 evaluator calls, however many generations it has, and the whole space can be
  enumerated to check NSGA-II on the real network.
- Riders are held fixed in the load limit, so it is cautious: a less frequent route would lose
  some riders to others. The full scenario run of a chosen solution reports the real crowding.
- Demand does not respond to the new service (ADR 0019): the front under-states what extra
  service on these routes would attract.
