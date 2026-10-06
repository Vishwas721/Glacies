# Routing validation — analysis of the 2026-10-06 run

Generated results: `routing.md` (sanity set) and `routing-benchmark.md` (performance). This file
explains them; numbers quoted here come from those runs.

## Sanity set: 11 of 20 within ±20 % / ±5 min (target 90 % — not met)

Every failing journey was inspected leg by leg. **All of them are feasible itineraries on the
2026-10-13 timetable; no router error was found.** The gaps fall into three groups.

### 1. Metro journeys are faster than the reference (#9, #11, #13, #15, #16)

Each uses the metro, often with the real Green ↔ Yellow interchange at Rashtreeya Vidyalaya
Road (e.g. #11 Yeshwanthpur → Electronic City: bus 96-G, Green line Mahalakshmi → RV Road,
Yellow line → Konappana Agrahara: 65 min vs 140 min expected).

Likely causes, in order:

- **No station access time.** Entering a Bengaluru metro station (entrance, security check,
  stairs or escalators to the platform) takes several minutes that the model does not include:
  a stop is boarded as soon as its platform is reached on the walk network.
- **The reference may predate the Yellow line** (opened 2025) or reflect a bus-only choice.

→ **Decision needed:** add an Assumed station access time for metro boarding (and alighting),
e.g. 3–5 min, configured in `city.toml [routing]`. Re-run `glacies validate routing` after.

### 2. Bus timetables do not include traffic (#1, #8)

#1 Doddaballapur → Majestic is one direct bus scheduled at 94 min; the reference expects 150
min around midday. #8 Banashankari → Jayanagar is scheduled at 15 min vs 25 expected. GTFS
schedules (Observed) are optimistic relative to Bengaluru road conditions; a schedule-based
model inherits that. Fixing it needs observed running times (out of scope for Phase 2).

### 3. Reference or stop-matching uncertainty (#5, #7)

- #7 Indiranagar → MG Road: the matched origin (Indiranagara 100ft Road) is 1.3 km from the
  metro station, so the router needs a bus to reach the Purple line (28 min). The reference
  probably starts at the station (Purple line alone is 6 min). The match is flagged for review.
- #5 Majestic → Shivajinagar: 25 min with one change vs 12 expected; no direct trip runs in
  that minute in the feed. The 12 min is likely an in-vehicle time or a car estimate.

## Performance: all targets met

| Target (phase doc §9) | Result |
|---|---|
| one-to-one < 50 ms | 21.9 ms median, 31.9 ms p95 |
| one-to-all < 200 ms | 25.1 ms median |
| all-zones × 120-min matrix < 30 min | ≈ 13.4 min (extrapolated from 200 parallel origins) |
| < 8 GB | 1.44 GB peak (router alone: 681 MB, built in 2.8 s) |

Range searches vary widely by origin (median 113 ms, p95 812 ms): central origins reach far
more of the network than peripheral ones.

## Next steps

1. Review the flagged stop matches in `bengaluru-sanity-set.csv` (rows with `review_note`).
2. Decide on a metro station access time; re-run the sanity check.
3. Treat the sanity set as a plausibility check, not ground truth: its times are Estimated.
