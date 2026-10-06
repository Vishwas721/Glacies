# Validation references

| File | What | Label | Used in |
|---|---|---|---|
| `raptor-toy-networks.md` | Three hand-computed toy timetables and their exact answers | Assumed (hand-built) | Phase 2 M1–M3 tests |
| `bengaluru-sanity-set.txt` | 20 real Bengaluru OD pairs with expected transit times | **Estimated** | Phase 2 M8 |
| `bengaluru-sanity-set.csv` | The same 20 pairs matched to canonical stops (coordinates, source stop ids, review notes) | **Estimated** | `glacies validate routing` |
| `routing.md` | Latest sanity-set comparison, written by `glacies validate routing` | Simulated vs Estimated | Phase 2 DoD |

## About the Bengaluru sanity set

- Entries 4–20 come from Google Maps Transit, which is itself a model, so the times are
  **Estimated**, not Observed. Entries 1–3 come from local knowledge and are also Estimated.
- Places are matched to stops in `bengaluru-sanity-set.csv`: the most-served stop with the place's
  name, preferring bus stations. Rows with a `review_note` involve an ambiguous place (e.g. two
  "Indiranagara" stops, or no single "Whitefield" stop) and must be checked by a person; edit the
  stop name and coordinates in the CSV if a match is wrong.
- It is a plausibility check (PRD §57 level 2), not ground truth: Google's timetable data, walking
  assumptions and live traffic differ from Glacies's scheduled GTFS model.
