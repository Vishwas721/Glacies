# Employment proxy — Bengaluru validation (2026-10-08 run)

Output of `uv run glacies build attraction` (copied from
`data/processed/bengaluru/attraction/BUILD_REPORT.md`), followed by an analysis. Every score is
**Estimated**; weights, POI categories and the index base are **Assumed**.

**Weights changed on 2026-10-08** from 0.70/0.30 (Phase 3 handoff) to **0.50/0.50** (user
decision after the M5 sensitivity table). The old weights stay in the table as
`previous-baseline`.

Builder 0.1.0 · 10,661 zones

## Formula (Estimated; weights Assumed)

`employment_score = 0.5 x building-area share + 0.5 x job-POI share`

- Building area: Open Buildings footprints, confidence ≥ 0.65 (Estimated; all uses, no heights).
- Job-type POIs (OpenStreetMap, Observed; categories Assumed): craft, education, food, health, industrial, office, shop.
- Each part is a share of the city total, so the score is a share of the city's estimated employment and sums to 1. Transit stops are not an input (no circularity).
- `opportunity_index` = score x 5,000,000 (Assumed base): an **Estimated Opportunity Index**, not a count of jobs.

## Hub check

**PASSED**: 96% of 28 hub zones rank in the top 20% of zones (rule: ≥ 80%). Top 5%: 64%. Hub zones hold 1.84x their share of population.

Hub zones are the cells overlapping each hand-drawn polygon.

| Hub | Zones | In top 20% | In top 5% | Best rank |
|---|---:|---:|---:|---:|
| Bagmane Tech Park | 1 | 1 | 0 | top 5.9% |
| Electronic City | 3 | 3 | 1 | top 4.8% |
| ITPL Whitefield | 4 | 4 | 2 | top 1.6% |
| Koramangala | 3 | 3 | 3 | top 0.2% |
| Manyata Tech Park | 3 | 3 | 2 | top 1.9% |
| ORR Bellandur Kadubeesanahalli | 8 | 7 | 5 | top 0.7% |
| Peenya Industrial Area | 5 | 5 | 4 | top 3.4% |
| RMZ Ecoworld | 1 | 1 | 1 | top 1.5% |

## Sensitivity (weights Assumed)

Rank correlation (Spearman) and top-10% overlap are against the baseline. The population row is not an employment proxy: it shows how much of the hub check a map of residents alone would pass.

| Weighting | Area | POIs | Confidence | Rank corr. | Top-10% overlap | Hubs in top 20% | Hubs in top 5% | Concentration |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 0.5 | 0.5 | 0.65 | 1.000 | 100% | 96% | 64% | 1.84x |
| previous-baseline | 0.7 | 0.3 | 0.65 | 0.998 | 96% | 96% | 64% | 1.50x |
| poi-led | 0.3 | 0.7 | 0.65 | 0.998 | 96% | 96% | 61% | 2.19x |
| pois-only | 0 | 1 | 0.65 | 0.661 | 83% | 96% | 64% | 2.70x |
| area-only | 1 | 0 | 0.65 | 0.990 | 91% | 96% | 50% | 0.98x |
| baseline-c75 | 0.5 | 0.5 | 0.75 | 0.999 | 99% | 96% | 68% | 1.85x |
| population (reference, not a proxy) | - | - | - | 0.917 | 88% | 96% | 46% | 1.00x |

## Top 10 zones (Estimated)

| Rank | H3 cell | Lat, lon | Score | Opportunity index |
|---:|---|---|---:|---:|
| 1 | `8861892ec3fffff` | 12.9783, 77.6410 | 0.7749% | 38,745 |
| 2 | `8861892ecbfffff` | 12.9708, 77.6450 | 0.6377% | 31,886 |
| 3 | `88618920a3fffff` | 12.9631, 77.7166 | 0.5579% | 27,895 |
| 4 | `88618925a7fffff` | 12.9710, 77.6029 | 0.5228% | 26,141 |
| 5 | `8861892e9bfffff` | 12.9784, 77.6072 | 0.5079% | 25,394 |
| 6 | `8860145b3bfffff` | 13.0011, 77.5529 | 0.4639% | 23,194 |
| 7 | `88618925c7fffff` | 12.9335, 77.6149 | 0.4595% | 22,974 |
| 8 | `8861892553fffff` | 12.9184, 77.6484 | 0.4559% | 22,796 |
| 9 | `8861892eddfffff` | 12.9709, 77.6366 | 0.4533% | 22,665 |
| 10 | `88618925a5fffff` | 12.9709, 77.6113 | 0.4502% | 22,510 |

## Column labels

- `building_share`: estimated
- `job_poi_share`: observed
- `employment_score`: estimated
- `opportunity_index`: estimated
- `score_rank`: estimated
- `population`: estimated

## Analysis

- **The hub check passes, but the rule is lenient.** 96 % of the 28 hub zones rank in the top
  20 % under every weighting, and a map of residents alone (population row) scores the same
  96 %: with 10,661 zones, many of them rural, the top 20 % covers most of the built-up city.
  The top 5 % separates better: 64 % for the baseline vs 46 % for population.
- **Footprint area behaves like population.** Area alone gives hub zones 0.98x their population
  share. Open Buildings has no use type or height, so homes dominate the footprint. This is why
  the weights moved from 0.70/0.30 to 0.50/0.50.
- **The job signal comes from POIs.** Hub zones hold 1.84x their population share under the new
  baseline (1.50x under the previous one), up to 2.70x with POIs only. More POI weight than
  0.50 lowers the top-5 % score (poi-led: 61 %) and leans on OpenStreetMap, which is mapped
  more completely in the centre.
- **Building confidence barely matters**: 0.65 vs 0.75 gives rank correlation 0.999.
- **Weakest hubs**: Bagmane Tech Park has no zone in the top 5 % (best rank top 5.9 %);
  Electronic City now has one (best rank top 4.8 %; none under the previous weights). Campuses
  with few mapped POIs remain the proxy's blind spot.
