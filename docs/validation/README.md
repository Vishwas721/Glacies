# Validation references

| File | What | Label | Used in |
|---|---|---|---|
| `raptor-toy-networks.md` | Three hand-computed toy timetables and their exact answers | Assumed (hand-built) | Phase 2 M1–M3 tests |
| `bengaluru-sanity-set.txt` | 20 real Bengaluru OD pairs with expected transit times | **Estimated** | Phase 2 M8 |

## About the Bengaluru sanity set

- Entries 4–20 come from Google Maps Transit, which is itself a model, so the times are
  **Estimated**, not Observed. Entries 1–3 come from local knowledge and are also Estimated.
- Departure times are written in mixed formats (`8.30`, `08:30`) and places are named, not located.
  Before M8 the set will be converted to a CSV with coordinates, matching each place name to a stop
  or station in the canonical network. The user then reviews the matches.
- It is a plausibility check (PRD §57 level 2), not ground truth: Google's timetable data, walking
  assumptions and live traffic differ from Glacies's scheduled GTFS model.
