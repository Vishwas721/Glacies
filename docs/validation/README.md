# Validation references

| File | What | Label | Used in |
|---|---|---|---|
| `raptor-toy-networks.md` | Three hand-computed toy timetables and their exact answers | Assumed (hand-built) | Phase 2 M1–M3 tests |
| `bengaluru-sanity-set.txt` | 20 real Bengaluru OD pairs with expected transit times | **Estimated** | Phase 2 M8 |
| `bengaluru-sanity-set.csv` | The same 20 pairs matched to canonical stops (coordinates, source stop ids, review notes) | **Estimated** | `glacies validate routing` |
| `routing.md` | Latest sanity-set comparison, written by `glacies validate routing` | Simulated vs Estimated | Phase 2 DoD |
| `employment-proxy.md` | Employment proxy hub check, sensitivity table and analysis (copy of the `glacies build attraction` report) | Estimated (weights Assumed) | Phase 3 M1 |
| `travel-time-matrix.md` | Baseline zone travel-time matrix run: coverage, run time, spot checks | Simulated | Phase 3 M2 |
| `accessibility.md` | Baseline accessibility: headline, distribution, checks, interpretation | Simulated (opportunities Estimated) | Phase 3 M3 |
| `../../cities/bengaluru/validation/employment_hubs.geojson` | 8 hand-drawn employment hub polygons (QGIS, 2026-10-07) | Assumed (hand-drawn) | Phase 3 hub check |

## About the Bengaluru sanity set

- Entries 4–20 come from Google Maps Transit, which is itself a model, so the times are
  **Estimated**, not Observed. Entries 1–3 come from local knowledge and are also Estimated.
- Places are matched to stops in `bengaluru-sanity-set.csv`: the most-served stop with the place's
  name, preferring bus stations. The user reviewed all 20 matches on 2026-10-06, accepted them
  and removed the `review_note` column.
- It is a plausibility check (PRD §57 level 2), not ground truth: Google's timetable data, walking
  assumptions and live traffic differ from Glacies's scheduled GTFS model.
