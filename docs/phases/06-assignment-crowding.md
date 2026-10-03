# Phase 6 — Assignment & Crowding

## 1. Goal & why

Put the synthetic OD demand onto actual scheduled trips: **which journeys people take, how full each
bus/train segment gets, and how crowding pushes people to alternatives.** This produces passenger
flows, route utilisation, load factors and realistic waiting/transfer metrics for baseline and
scenarios. (PRD §26–28, §65; ADR 0003)

## 2. Prerequisites

Phase 2 RAPTOR with journey reconstruction; Phase 4 scenario runner; Phase 5 OD matrix (with
departure-time profile).

## 3. Research before starting

- **Spiess & Florian (1989), *Optimal strategies: a new assignment model for transit networks***.
  This is the classic frequency-based approach; understand "strategies" and why they matter for
  high-frequency buses.
- **Schedule-based assignment** (Nuzzolo, Crisalli; Hamdouch & Lawphongpanich). Since we route on
  timetables, this is our family. Read about capacity constraints and fail-to-board.
- **Method of Successive Averages (MSA)** for iterative crowding equilibrium: convergence, step
  sizes, relative gap.
- Crowding penalty functions: in-vehicle time multipliers by load factor (e.g. Wardman & Whelan's
  review of crowding valuations).
- Bus/metro **capacities**: BMTC fleet types (standard, Volvo, electric) and seated/standing
  capacity; metro train-set capacity. Each one is an Assumed parameter with a source.

## 4. Decisions you must make

| Decision | Guidance | Your choice |
|---|---|---|
| Departure-time profile | spread OD over the window using BMRCL hourly shape (Estimated) | |
| Route choice v1 | all-or-nothing on best RAPTOR journey → then MSA with crowding penalty | |
| Choice set | best + k alternatives from rRAPTOR/Pareto set | |
| Capacities | per mode/vehicle type, Assumed with source | |
| Crowding penalty | e.g. multiplier 1.0 → 2.0 as load factor 0.8 → 1.5 | |
| Hard capacity | v1: soft penalty only; later: fail-to-board/denied boarding | |
| Convergence | max iterations + relative-gap threshold | |

## 5. Your hands-on tasks

- [ ] Compile capacities and the crowding curve with sources into `cities/bengaluru/assignment.toml`.
- [ ] Sanity-check the loads: do the heaviest simulated segments match corridors you know are crowded
      (e.g. Majestic–Silk Board, ORR, Purple Line core)?
- [ ] Compare simulated metro station boardings (after assignment) with BMRCL ridership. This is
      validation level 4.

## 6. Agent tasks

1. **M1 — All-or-nothing assignment**: sample departure times per OD (seeded), route with RAPTOR,
   accumulate passengers per trip segment `(trip_id, from_stop_seq)` → loads Parquet.
2. **M2 — Metrics**: per-OD travel/wait/walk/transfer, per-route utilisation, per-segment load factor,
   boardings/alightings per stop, and city aggregates. Every metric is labelled Simulated.
3. **M3 — Crowding loop (MSA)**: generalised cost with crowding multiplier on loaded segments →
   reroute → average flows; convergence diagnostics; toy test with two parallel routes where one
   saturates and demand shifts.
4. **M4 — Performance**: batch the routing in Rust (assignment loop in Rust if Python is the
   bottleneck), stream results to Parquet, and stay within memory.
5. **M5 — Scenario integration**: the scenario runner gains an assignment stage; comparison adds
   crowding, flows and wait deltas.
6. **M6 — Validation report**: station boardings vs. BMRCL; top crowded segments; convergence plot.

## 7. Kickoff prompt

```text
We are starting Phase 6 (Assignment & Crowding) of Glacies. Read CLAUDE.md, docs/adr/0003-macroscopic-assignment.md,
docs/phases/06-assignment-crowding.md and cities/bengaluru/assignment.toml.

Implement milestone M<N> only. Rules:
- start from toy networks with hand-checkable loads (e.g. 100 passengers, two parallel routes,
  capacity 60) and assert the expected split after the crowding loop;
- aggregate flows only, never per-passenger Python objects; seeded sampling;
- write loads and metrics to Parquet, labelled Simulated;
- small Conventional Commits on branch phase/06-m<N>; all checks green; open a PR with
  convergence diagnostics.
```

## 8. Deliverables

`src/glacies/assignment/{aon,msa,metrics}.py` (and/or Rust in `crates/`), `cities/bengaluru/assignment.toml`,
loads/flows Parquet per run, `docs/validation/assignment.md`.

## 9. Definition of done

- [ ] Toy assignment tests pass (conservation: Σ boardings = Σ assigned trips, per-segment loads correct).
- [ ] The MSA converges below the gap threshold on Bengaluru within the stated iterations, or the
      non-convergence is documented.
- [ ] A full baseline + scenario assignment finishes on your laptop (record time/RAM).
- [ ] Station-boarding comparison vs. BMRCL is reported.
- [ ] Scenario comparison now includes crowding, waiting and flow deltas (PRD §31 table complete).

## 10. Risks & pitfalls

- **Demand conservation bugs**: assert totals at every stage.
- **Oscillation** in crowding loops: use MSA or a smaller step, and log the gap.
- **Frequency vs. schedule mismatch** in feeds with `frequencies.txt`: use the expanded trips from Phase 1.
- **Overinterpreting loads**: bus feed coverage is incomplete (PRD Risk 1), so missing routes make
  other routes look overloaded. State this in reports.

**Core:** AON, MSA with crowding penalty, metrics, scenario integration.
**Later:** fail-to-board, strategy-based (Spiess–Florian) choice for high-frequency buses, dwell-time effects.
**Never (for now):** microscopic vehicle simulation.
