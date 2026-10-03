# Phase 5 — Demand (synthetic OD + calibration)

## 1. Goal & why

Estimate **how many people travel from each zone to each zone** in the AM peak, since no real OD
data exists. Calibrate it against the one strong observation available: BMRCL hourly station
ridership. Demand turns "what can people reach" into "where do people go", which assignment needs.
(PRD §22–25, §64; Risks 2–3)

## 2. Prerequisites

Phase 1 zones with population; Phase 3 employment proxy; Phase 2 travel-time matrix (generalised
cost); BMRCL ridership downloaded and validated.

## 3. Research before starting

- **Ortúzar & Willumsen, *Modelling Transport*** (4th ed.), chapters on trip generation and trip
  distribution: gravity models, singly vs. doubly constrained, the Furness method, and calibration
  with the Hyman method. Required reading.
- Friction functions: exponential `exp(-βc)`, power `c^-α`, combined/Tanner. Learn what β means
  (mean trip cost relationship).
- Mode choice basics (multinomial logit). We will **not** build a full mode-choice model in v1, but
  you must decide how to get the *transit share* (see decisions).
- Indian city travel surveys and Bengaluru CMP (Comprehensive Mobility Plan) published figures:
  trip rates per person, mode shares, average trip lengths. These are useful **Assumed** priors.
  Cite the source for each number you use.
- The BMRCL ridership dataset: the structure (station × hour × entries/exits), and which dates it
  covers.

## 4. Decisions you must make

| Decision | Guidance | Your choice |
|---|---|---|
| Trip purpose scope | Home-based work AM peak only (v1) | |
| Trip production rate | trips/person/AM-peak (Assumed, cite CMP or survey) | |
| Transit share | fixed share (Assumed) or a simple logit vs. distance; v1 can be fixed | |
| Friction function | exponential (recommended start) | |
| Cost used | generalised transit cost from Phase 2 (in-vehicle + 2×wait + 2×walk + transfer penalty) | |
| Calibration target | metro station entries 08:00–10:00, averaged over weekdays | |
| Calibration method | 1-D search on β minimising RMSE/GEH vs. station entries; held-out stations for validation | |

## 5. Your hands-on tasks

- [ ] Collect the priors (trip rate, mode share, average trip length) and write them into a
      `cities/bengaluru/demand.toml` with source citations.
- [ ] Choose the calibration period from the BMRCL data, excluding holidays and anomalies.
- [ ] Choose about 20 % of stations as a **held-out validation set** before calibration starts,
      and don't peek.
- [ ] Judge the outcome: does the OD matrix concentrate flows on the known hubs? Is the average
      trip length near your prior?

## 6. Agent tasks

1. **M1 — Productions & attractions**: `O_i` from population × trip rate × transit share;
   `D_j` from the employment proxy scaled so ΣD = ΣO. Labelled Estimated/Assumed.
2. **M2 — Gravity model**: doubly-constrained gravity with Furness balancing in NumPy/Polars
   (vectorised, chunked if needed), with convergence diagnostics; tests on a 3×3 toy with known
   answers.
3. **M3 — Station mapping**: map simulated metro boardings per station (requires a light
   all-or-nothing assignment from Phase 6 M1, or a "first boarding stop" from RAPTOR journeys).
   Coordinate with Phase 6 or implement a minimal version here.
4. **M4 — Calibration**: parameter sweep / optimiser over β (and optionally the transit share)
   against training stations; report fit statistics (R², RMSE, GEH) on held-out stations; save the
   chosen parameters + fit report.
5. **M5 — Sensitivity**: OD matrices under alternative proxies/β values; output how the headline
   metrics move.
6. **M6 — Outputs**: `od/<version>.parquet` (origin, destination, trips, label=Estimated) +
   manifest + calibration report.

## 7. Kickoff prompt

```text
We are starting Phase 5 (Demand) of Glacies. Read CLAUDE.md, docs/phases/05-demand.md and
cities/bengaluru/demand.toml (my priors with citations), and note my held-out validation stations.

Implement milestone M<N> only. Rules:
- every demand quantity is labelled Estimated, every prior Assumed (with its citation carried into
  the output metadata);
- verify the gravity model on a toy 3×3 example with a hand-computed balanced matrix;
- never use held-out stations during calibration; report fit on them separately;
- vectorised/chunked computation only; random seeds explicit;
- small Conventional Commits on branch phase/05-m<N>; all checks green; open a PR.
```

## 8. Deliverables

`src/glacies/demand/{production,attraction,gravity,calibrate}.py`, `cities/bengaluru/demand.toml`,
`data/processed/bengaluru/demand/*.parquet`, `docs/validation/demand.md` (calibration report).

## 9. Definition of done

- [ ] Balanced OD: row sums match `O_i` and column sums match `D_j` within tolerance.
- [ ] Calibrated β is recorded with fit statistics; held-out station R² is reported honestly
      (whatever it is), with discussion.
- [ ] Mean trip length is within a stated range of your prior.
- [ ] The OD matrix is reproducible (same inputs/seed → identical file).
- [ ] The sensitivity analysis is documented.

## 10. Risks & pitfalls

- **Metro ridership ≠ total transit demand**: metro is a fraction of trips. Calibrate *shape*
  (distribution across stations) as well as level, and say so.
- **Intrazonal trips** are not served by transit. Exclude them or treat them explicitly.
- **Furness non-convergence** happens when zones have D>0 but are unreachable. Handle zero-cost/infinite-cost cells.
- **Overfitting β** to a few stations: use the held-out set.
- **False precision**: present demand as ranges/sensitivities, not single truths.

**Core:** HBW AM-peak gravity model, Furness, β calibration on BMRCL, sensitivity.
**Later:** multiple purposes/time periods, logit mode choice, bus ridership if published.
**Never:** presenting synthetic demand as observed.
