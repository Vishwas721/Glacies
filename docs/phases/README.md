# Glacies phase plan

Glacies is built in ten phases. Each phase doc has the same structure, so you always know what to
do next:

1. **Goal & why**
2. **Prerequisites**
3. **Research before starting**: what *you* should read or understand first
4. **Decisions you must make**: choices the agent should not make for you
5. **Your hands-on tasks**: downloads, checks, judgement calls
6. **Agent tasks**: what the coding agent builds
7. **Kickoff prompt**: copy-paste into Claude Code to start the phase
8. **Deliverables**
9. **Definition of done**: how to verify it
10. **Risks & pitfalls**, plus a **Core / Later / Never** scope list

## Order and dependencies

```
P0 Foundation
  │
P1 Data Foundation ───────────────┐
  │                               │
P2 Routing Engine (Rust RAPTOR)   │
  │                               │
P3 Accessibility ◄────────────────┘   ← first real result (needs population + job proxy)
  │
P4 Scenario Engine                    ← first before/after comparison (MVP core)
  │
P5 Demand (gravity + calibration)
  │
P6 Assignment & Crowding              ← full MVP pipeline
  │
P7 API, Jobs & Visualisation          ← the core demonstration (PRD §73)
  │
P8 Optimisation (NSGA-II)
  │
P9 Advanced research (backlog)
```

### Why this differs from the PRD order

The PRD lists Demand (P3) and Assignment (P4) before the Scenario Engine (P5). Here, **Accessibility
and Scenarios come first**: cumulative-opportunity accessibility needs only routing, population and
the job proxy, not an OD matrix. That gets you to a real, defensible before/after comparison months
earlier and de-risks the scenario engine before demand modelling, the least certain part, enters the
picture. Demand and assignment then add crowding and flows on top of a working scenario loop.

The API and frontend skeleton already exist from Phase 0. Phases 3–6 may add *thin debug views*,
like a CLI report or a quick map in QGIS/kepler.gl. Phase 7 is where the product UI gets built.

## Status

| Phase | Doc | Status |
|---|---|---|
| 0 | [Foundation](00-foundation.md) | ✅ done |
| 1 | [Data Foundation](01-data-foundation.md) | ✅ M1–M6 done (QGIS check pending) |
| 2 | [Routing Engine](02-routing-engine.md) | 🚧 M1–M5 done · M6–M7 in review |
| 3 | [Accessibility](03-accessibility.md) | — |
| 4 | [Scenario Engine](04-scenario-engine.md) | — |
| 5 | [Demand](05-demand.md) | — |
| 6 | [Assignment & Crowding](06-assignment-crowding.md) | — |
| 7 | [API, Jobs & Visualisation](07-api-visualisation.md) | — |
| 8 | [Optimisation](08-optimisation.md) | — |
| 9 | [Advanced Research](09-advanced-research.md) | — |

Update this table in the PR that finishes each phase.

## How to run a phase with the agent

1. Do the **Research** and **Decisions** sections yourself and write your decisions into the phase
   doc (or a `decisions` section in the PR). The agent will use them.
2. Do the **hands-on tasks** that need you: downloads behind click-through licences, visual checks.
3. Create a branch: `git switch -c phase/NN-name`.
4. Paste the **kickoff prompt**. Big phases are split into milestones. Run one milestone per
   session/PR, not the whole phase in one go.
5. Verify the **Definition of done** yourself before merging.
