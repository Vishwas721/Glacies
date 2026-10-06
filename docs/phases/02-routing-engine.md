# Phase 2 — Routing Engine (Rust RAPTOR + PyO3)

## 1. Goal & why

Fast, correct, schedule-based journey planning: for an origin, destination and departure time,
return the arrival time, walking, waiting, transfers, and legs. Run millions of these quickly
enough for city-wide accessibility and assignment. This is the computational heart of Glacies.
(PRD §18–21, §58, §63; ADR 0004)

## 2. Prerequisites

Phase 1 done: canonical Parquet `stops`, `patterns`, `trips`, `stop_times`, plus the walk network
with stops snapped.

## 3. Research before starting

- **Delling, Pajor, Werneck (2012), *Round-Based Public Transit Routing*** (Transportation Science
  / Microsoft Research TR). Read sections on basic RAPTOR, the marking/route-collection step,
  footpaths, local and target pruning, and **rRAPTOR** (range queries). This is required reading.
  Work through the paper's example by hand on paper.
- Conveyal's write-up on **R5's use of RAPTOR for accessibility** (range-RAPTOR over a departure
  window, percentiles of travel time). It explains why accessibility uses *distributions*, not a
  single departure.
- The basics of **McRAPTOR** (multi-criteria), so you know what you are *not* doing yet.
- *The Rust Book* chapters 8 (collections) and 16 (concurrency); the [Rayon](https://docs.rs/rayon) README.
- [PyO3 user guide](https://pyo3.rs/) + [maturin](https://www.maturin.rs/) "mixed Rust/Python
  projects"; [numpy crate for PyO3](https://docs.rs/numpy) (returning arrays without copies).
- Background: how [OpenTripPlanner](https://docs.opentripplanner.org/) and R5 build transfers
  (stop-to-stop walking within N metres).

## 4. Decisions you must make

| Decision | Guidance | Your choice |
|---|---|---|
| Max rounds (transfers) | 4–5 rounds (= 3–4 transfers) is typical | **4 rounds (3 transfers)** |
| Walking speed | 1.2–1.3 m/s (Assumed) | **1.2 m/s** |
| Max access/egress walk | 800–1000 m | **800 m** |
| Max transfer walk | 300–500 m | **400 m** (one walking leg between vehicles, shortest path on the M4 network) |
| Min transfer time | 60–120 s (Assumed, per mode?) | **60 s**, all modes |
| Optimisation criteria (v1) | earliest arrival with a Pareto on transfers (standard RAPTOR) | **as guided** |
| Validation reference | R5 via r5py (Python, free) or OTP 2, run once offline | **20-pair sanity set** (`docs/validation/`, Estimated); no R5/OTP |

_Decisions recorded 2026-10-06 from the Phase 2 handoff; all Assumed. Toy networks: `docs/validation/raptor-toy-networks.md`._

## 5. Your hands-on tasks

- [ ] Hand-compute answers for the three PRD §58 toy networks (A→B→C; A→B, B→C; diamond with a
      faster branch). Write them down. They become test expectations.
- [ ] Pick 20 real OD pairs you know (e.g. Majestic → Electronic City at 08:30) and note plausible
      travel times from Google Maps/Namma Yatri/experience as a sanity set.
- [ ] Optional: install r5py (needs Java) and produce reference travel times for about 200 OD pairs.

## 6. Agent tasks

1. **M1 — Timetable data structure** (`crates/raptor`): pattern-based routes; flat arrays
   `route_stops`, `route_trips`, `stop_times` (arrival/departure `u32`), `stop_routes`, `footpaths`.
   Builder from in-memory columns; validates that trips within a pattern don't overtake (split
   patterns if they do).
2. **M2 — Basic RAPTOR**: one-to-all earliest arrival with k rounds, marking, route scanning,
   footpath relaxation, local pruning. Tests on the toy networks.
3. **M3 — Journey reconstruction**: per-round parent pointers → legs (walk/transit, boarding and
   alighting stops, trip id, times); compute walking/waiting/in-vehicle/transfer breakdown.
4. **M4 — Access/egress**: multiple origin stops with initial walk times; target pruning for
   one-to-one queries.
5. **M5 — Range RAPTOR**: departures across a window (e.g. 07:00–09:00, every minute), reusing labels
   between iterations; outputs travel-time distributions per destination stop.
6. **M6 — PyO3 bindings** (`crates/raptor-py`, maturin): `Timetable.from_arrow(...)`,
   `route(origin, dest, departure)`, `travel_times(origins, departures) -> ndarray`; release
   the GIL and parallelise across origins with Rayon; deterministic output order.
7. **M7 — Python integration**: build the timetable from Phase 1 Parquet; transfers/footpaths from
   the walk network (stop-to-stop shortest walks ≤ max transfer walk, computed in Rust or with
   a CSR graph + Dijkstra, never NetworkX); zone-centroid → stop access times.
8. **M8 — Benchmarks & validation**: criterion benchmarks; compare against your sanity set and R5
   references; write `docs/validation/routing.md`.

CI: add a maturin build step to the Python job once M6 lands.

## 7. Kickoff prompt

```text
We are starting Phase 2 (Routing Engine) of Glacies. Read CLAUDE.md, docs/adr/0004-raptor-in-rust.md
and docs/phases/02-routing-engine.md, including my parameter decisions in section 4 and the
hand-computed toy-network answers I added.

Implement milestone M<N> only. First explain the data layout or algorithm step you are about to
write and how it maps to the RAPTOR paper (Delling et al. 2012). Then:
- write the toy-network tests first (they must fail), then the implementation;
- no unsafe, no per-stop heap allocations in hot loops, deterministic results;
- keep the core crate free of PyO3; bindings live in a separate crate;
- small Conventional Commits on branch phase/02-m<N>; all CLAUDE.md checks green;
- open a PR and include benchmark numbers if relevant.
```

## 8. Deliverables

- `crates/raptor/` (core), `crates/raptor-py/` (bindings), `src/glacies/routing/` (Python glue)
- Toy-network test suite in Rust; Python integration tests on the toy GTFS fixture
- `POST /api/route` can be wired in Phase 7 using `route()`
- `docs/validation/routing.md`

## 9. Definition of done

- [ ] All toy-network tests pass, including transfer, footpath, overtaking and after-midnight cases.
- [ ] A one-to-one query on Bengaluru answers in < 50 ms; one-to-all in < 200 ms (targets; record actuals).
- [ ] All-zones × 120-minute window travel-time matrix completes in < 30 min on your laptop with
      < 8 GB RAM (target; record actuals).
- [ ] 90 % of the sanity/R5 OD pairs are within ±20 % (or ±5 min) of the reference; outliers explained.
- [ ] Same input ⇒ identical output arrays across runs and thread counts.

## 10. Risks & pitfalls

- **Overtaking trips** break RAPTOR's "earliest trip" assumption. Split those patterns.
- **Footpath transitivity**: RAPTOR assumes transitively closed footpaths, or a single walk leg.
  Pick one and test it.
- **Off-by-one in rounds** (round 0 = walking only).
- **Departure-time semantics** (depart-at vs. arrive-by). Depart-at only in v1.
- **Premature optimisation.** Get correctness on toys first, then profile.
- PRD Risk 4 ordering: toy → simple GTFS → single city → multimodal → full Bengaluru.

**Core:** RAPTOR, footpaths, access/egress, reconstruction, rRAPTOR, bindings.
**Later:** McRAPTOR (fare/comfort criteria), arrive-by queries, frequency-based RAPTOR variants.
**Never (for now):** road-network car routing, real-time delays.
