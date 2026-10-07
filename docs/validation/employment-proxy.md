# Employment proxy — Bengaluru validation (2026-10-07 run)

Output of `uv run glacies build attraction` (copied from
`data/processed/bengaluru/attraction/BUILD_REPORT.md`), followed by an analysis. Every score is
**Estimated**; weights, POI categories and the index base are **Assumed**.

Builder 0.1.0 · 10,661 zones

## Formula (Estimated; weights Assumed)

`employment_score = 0.7 x building-area share + 0.3 x job-POI share`

- Building area: Open Buildings footprints, confidence ≥ 0.65 (Estimated; all uses, no heights).
- Job-type POIs (OpenStreetMap, Observed; categories Assumed): craft, education, food, health, industrial, office, shop.
- Each part is a share of the city total, so the score is a share of the city's estimated employment and sums to 1. Transit stops are not an input (no circularity).
- `opportunity_index` = score x 5,000,000 (Assumed base): an **Estimated Opportunity Index**, not a count of jobs.

## Hub check

**PASSED**: 96% of 28 hub zones rank in the top 20% of zones (rule: ≥ 80%). Top 5%: 64%. Hub zones hold 1.50x their share of population.

Hub zones are the cells overlapping each hand-drawn polygon.

| Hub | Zones | In top 20% | In top 5% | Best rank |
|---|---:|---:|---:|---:|
| Bagmane Tech Park | 1 | 1 | 0 | top 6.4% |
| Electronic City | 3 | 3 | 0 | top 6.1% |
| ITPL Whitefield | 4 | 4 | 2 | top 1.9% |
| Koramangala | 3 | 3 | 3 | top 0.2% |
| Manyata Tech Park | 3 | 3 | 2 | top 2.1% |
| ORR Bellandur Kadubeesanahalli | 8 | 7 | 5 | top 0.7% |
| Peenya Industrial Area | 5 | 5 | 5 | top 2.8% |
| RMZ Ecoworld | 1 | 1 | 1 | top 1.7% |

## Sensitivity (weights Assumed)

Rank correlation (Spearman) and top-10% overlap are against the baseline. The population row is not an employment proxy: it shows how much of the hub check a map of residents alone would pass.

| Weighting | Area | POIs | Confidence | Rank corr. | Top-10% overlap | Hubs in top 20% | Hubs in top 5% | Concentration |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 0.7 | 0.3 | 0.65 | 1.000 | 100% | 96% | 64% | 1.50x |
| equal | 0.5 | 0.5 | 0.65 | 0.998 | 96% | 96% | 64% | 1.84x |
| poi-led | 0.3 | 0.7 | 0.65 | 0.993 | 92% | 96% | 61% | 2.19x |
| pois-only | 0 | 1 | 0.65 | 0.635 | 79% | 96% | 64% | 2.70x |
| area-only | 1 | 0 | 0.65 | 0.996 | 95% | 96% | 50% | 0.98x |
| baseline-c75 | 0.7 | 0.3 | 0.75 | 0.999 | 98% | 96% | 61% | 1.50x |
| population (reference, not a proxy) | - | - | - | 0.921 | 89% | 96% | 46% | 1.00x |

## Top 10 zones (Estimated)

| Rank | H3 cell | Lat, lon | Score | Opportunity index |
|---:|---|---|---:|---:|
| 1 | `8861892ec3fffff` | 12.9783, 77.6410 | 0.4931% | 24,654 |
| 2 | `8861892ecbfffff` | 12.9708, 77.6450 | 0.4103% | 20,517 |
| 3 | `88618920a3fffff` | 12.9631, 77.7166 | 0.3677% | 18,385 |
| 4 | `88618925a7fffff` | 12.9710, 77.6029 | 0.3374% | 16,871 |
| 5 | `8861892e9bfffff` | 12.9784, 77.6072 | 0.3215% | 16,077 |
| 6 | `8860145b3bfffff` | 13.0011, 77.5529 | 0.3152% | 15,762 |
| 7 | `8861892553fffff` | 12.9184, 77.6484 | 0.3053% | 15,267 |
| 8 | `8861892eddfffff` | 12.9709, 77.6366 | 0.3004% | 15,021 |
| 9 | `88618925c7fffff` | 12.9335, 77.6149 | 0.2978% | 14,888 |
| 10 | `88618925a5fffff` | 12.9709, 77.6113 | 0.2923% | 14,614 |

## Column labels

- `building_share`: estimated
- `job_poi_share`: observed
- `employment_score`: estimated
- `opportunity_index`: estimated
- `score_rank`: estimated
- `population`: estimated

## Analysis

- **The hub check passes, but the rule is lenient.** 96 % of the 28 hub zones rank in the top
  20 % under every weighting. A map of residents alone (population row) also scores 96 %:
  with 10,661 zones, many of them rural, the top 20 % covers most of the built-up city. The top
  5 % separates better: 64 % for the baseline vs 46 % for population.
- **Footprint area behaves like population.** Area alone gives hub zones 0.98x their
  population share, and its ranking is almost the same as the baseline's (rank correlation
  0.996). Open Buildings has no use type or height, so homes dominate the footprint.
- **The job signal comes from POIs.** Hub zones hold 1.50x their population share under the
  baseline, rising to 2.70x with POIs only. Shifting weight to POIs raises the concentration
  without lowering the hub check.
- **Building confidence barely matters**: 0.65 vs 0.75 gives rank correlation 0.999.
- **Weakest hubs**: Electronic City and Bagmane Tech Park reach the top 20 % but not the top
  5 % (best ranks: top 6.1 % and 6.4 %). Both are weak on both inputs. Electronic City has 31
  job POIs over 3 zones and Bagmane has 10 in 1 zone, while the median top-5 % zone has 31.
  Their best footprint-area ranks are only top 7.1 % and 6.5 %, because campus buildings do not
  outweigh dense housing by footprint. Campuses with few mapped POIs are the proxy's blind spot.
- **Not yet handled**: zones near the bbox edge (M3 will flag them), and how the headline
  accessibility metric moves under these weightings (M5).
