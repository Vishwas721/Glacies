# Phase 4 — Scenario Engine

## 1. Goal & why

Make Glacies **counterfactual**: describe a network change as a small diff, apply it to the
baseline, recompute only what changed, and compare scenario vs. baseline. After this phase you
have the MVP core: modify the network → accessibility before/after. (PRD §29–31, §53–54, §66)

## 2. Prerequisites

Phase 2 timetable builder; Phase 3 accessibility pipeline producing a baseline.

## 3. Research before starting

- How existing tools model scenarios: **Conveyal Analysis "modifications"** (add trip pattern,
  adjust frequency, remove trips, reroute, adjust speed/dwell). Read their docs; it is the closest
  prior art to what you are building.
- GTFS-editing libraries (e.g. `gtfs-kit`, partridge) for ideas on frequency → trip expansion.
- **JSON Schema / Pydantic discriminated unions** for typed mutation lists.
- Content-addressed caching (hash of inputs → result) to understand "incremental recomputation".
- Read PRD §29–31 again and decide which mutation types matter for your demo story (PRD §73).

## 4. Decisions you must make

| Decision | Guidance | Your choice |
|---|---|---|
| v1 mutation types | `remove_route`, `modify_headway`, `add_route` (MVP), then `remove_stop`, `add_stop`, `adjust_speed` | |
| How new routes get times | given stop sequence + headway + span + speed (km/h) or explicit run times | |
| Scenario storage | JSON files in `scenarios/<city>/` + rows in PostGIS (metadata) | |
| Cache key | sha256(baseline BUILD.json + mutations + config + engine versions) | |
| Comparison metrics v1 | accessibility deltas (zone + city), mean/percentile travel time, transfers | |

## 5. Your hands-on tasks

- [ ] Write 3 realistic Bengaluru scenarios as JSON by hand. For example: double frequency on a
      trunk route along Outer Ring Road; remove two routes that overlap a metro line; add a feeder
      from a metro station to a tech park. These become fixtures and the demo story.
- [ ] For each, write down the *expected direction* of change (which zones should gain or lose).
      This is PRD validation level 5 (logical plausibility).
- [ ] Review the first comparison output against your expectations.

## 6. Agent tasks

1. **M1 — Scenario schema**: Pydantic models with a discriminated `Mutation` union, JSON
   Schema export, versioning (`schema_version`), and validation against the baseline (route ids
   exist etc.).
2. **M2 — Mutation engine**: pure functions `apply(baseline_tables, mutations) -> scenario_tables`
   on canonical Parquet tables (no DB copy); headway modification regenerates trips; add-route
   builds a new pattern + trips; deterministic IDs for new entities.
3. **M3 — Run orchestration**: `glacies scenario run <file>` → timetable build → travel times →
   accessibility. A content-addressed cache in `data/processed/<city>/results/<hash>/`, plus a
   `run.json` reproducibility record (PRD §53: scenario id, dataset versions, engine versions, seed,
   config, timestamp).
4. **M4 — Incremental recomputation (pragmatic)**: reuse the cached baseline; recompute only origins
   whose reachable stop set touches modified routes (conservative superset), with a full-recompute
   fallback and a test showing incremental == full.
5. **M5 — Comparison**: `glacies scenario compare <a> <b>` producing a table like PRD §31, zone-level
   delta Parquet and a Markdown report.

## 7. Kickoff prompt

```text
We are starting Phase 4 (Scenario Engine) of Glacies. Read CLAUDE.md and docs/phases/04-scenario-engine.md,
plus the three hand-written scenarios in scenarios/bengaluru/ and my expected directions of change.

Implement milestone M<N> only. Rules:
- scenarios are diffs, never copies of the baseline;
- mutation functions are pure and deterministic; new IDs are derived deterministically;
- tests use the toy GTFS: e.g. halving a headway must reduce expected wait in the toy accessibility
  result, and removing the only route must make the destination unreachable;
- every run writes a run.json reproducibility record;
- small Conventional Commits on branch phase/04-m<N>; all checks green; open a PR.
```

## 8. Deliverables

`src/glacies/scenario/{schema,mutations,runner,compare}.py`, `scenarios/bengaluru/*.json`,
`schemas/scenario.schema.json`, CLI commands, comparison report.

## 9. Definition of done

- [ ] The three hand-written scenarios run end-to-end and produce comparison reports.
- [ ] Re-running a scenario hits the cache; changing one mutation invalidates it.
- [ ] The incremental result equals the full recompute on test scenarios.
- [ ] The direction of change matches your expectations, or the difference is explained.
- [ ] The same scenario + seed produces identical outputs (byte-level on Parquet).

## 10. Risks & pitfalls

- **Overly ambitious incremental logic**: correctness first; the full recompute is always available.
- **Unrealistic added routes**: require explicit speed/run times; label them Assumed.
- **Headway changes on routes with irregular timetables**: define the semantics (scale vs. regularise)
  and test both.
- **Schema churn**: version the schema from day one.

**Core:** remove/modify-headway/add route, caching, comparison, reproducibility.
**Later:** stop add/remove/move, speed changes, metro expansion, express patterns.
**Never:** copying the whole DB per scenario.
