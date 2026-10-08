# Accessibility — Bengaluru baseline (2026-10-08 run)

Output of `uv run glacies build accessibility` (copied from
`data/processed/bengaluru/accessibility/baseline/BUILD_REPORT.md`), followed by checks and an
interpretation. Reach is **Simulated**; jobs and population are **Estimated**; all parameters
are **Assumed**. Employment-proxy weights are 0.50/0.50 since 2026-10-08 (2.3 % headline under
the previous 0.70/0.30, see the sensitivity table).

Builder 0.1.0 · 127,932 rows · 2,470 edge zones

## Headline (Simulated; jobs Estimated)

Residents can reach on average **2.7% of the city's estimated jobs** within 45 min by transit and walking (median over 07:30-09:30 departures; population-weighted mean over all zones).

## Population-weighted mean share reachable

| Measure | Percentile | 15 min | 30 min | 45 min | 60 min |
|---|---|---:|---:|---:|---:|
| Estimated jobs | p25 | 0.1% | 0.9% | 3.4% | 8.4% |
| Estimated jobs | p50 | 0.09% | 0.8% | 2.7% | 6.9% |
| Estimated jobs | p75 | 0.08% | 0.6% | 2.2% | 5.8% |
| Population | p25 | 0.07% | 0.6% | 2.1% | 5.1% |
| Population | p50 | 0.06% | 0.5% | 1.6% | 4.2% |
| Population | p75 | 0.06% | 0.4% | 1.3% | 3.4% |

p25 is a good day (a quarter of departures do at least this well), p75 a bad one.

## Distribution of estimated jobs reachable (p50)

Quantiles are over residents, not zones: q10 means 10 % of residents reach less.

| Scope | Threshold | Mean | q10 | q25 | q50 | q75 | q90 | Gini | Residents < 1 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all zones | 15 min | 0.09% | 0.00% | 0.01% | 0.03% | 0.09% | 0.2% | 0.71 | 99.2% |
| all zones | 30 min | 0.8% | 0.01% | 0.03% | 0.2% | 0.9% | 2.4% | 0.70 | 76.4% |
| all zones | 45 min | 2.7% | 0.01% | 0.04% | 0.4% | 3.7% | 9.1% | 0.73 | 59.6% |
| all zones | 60 min | 6.9% | 0.01% | 0.04% | 0.8% | 11.5% | 23.6% | 0.71 | 51.0% |
| excluding edge zones | 15 min | 0.10% | 0.00% | 0.01% | 0.04% | 0.10% | 0.2% | 0.69 | 99.2% |
| excluding edge zones | 30 min | 0.8% | 0.01% | 0.05% | 0.3% | 1.0% | 2.6% | 0.68 | 74.3% |
| excluding edge zones | 45 min | 3.0% | 0.01% | 0.07% | 0.6% | 4.4% | 9.7% | 0.71 | 56.0% |
| excluding edge zones | 60 min | 7.6% | 0.01% | 0.08% | 1.6% | 13.0% | 24.5% | 0.68 | 46.7% |

## Sensitivity to the employment-proxy weights (p50, weights Assumed)

Population-weighted mean share of estimated jobs reachable under each weighting of the proxy (see the attraction report). The population row is a reference, not a proxy.

| Weighting | 15 min | 30 min | 45 min | 60 min | Change at 45 min | Gini at 45 min |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0.09% | 0.8% | 2.7% | 6.9% | +0.00 pp | 0.73 |
| previous-baseline | 0.08% | 0.7% | 2.3% | 5.8% | -0.43 pp | 0.71 |
| poi-led | 0.1% | 0.9% | 3.2% | 8.0% | +0.43 pp | 0.75 |
| pois-only | 0.1% | 1.0% | 3.8% | 9.7% | +1.08 pp | 0.77 |
| area-only | 0.06% | 0.5% | 1.7% | 4.2% | -1.08 pp | 0.68 |
| baseline-c75 | 0.09% | 0.8% | 2.7% | 6.9% | -0.03 pp | 0.73 |
| population (reference, not a proxy) | 0.06% | 0.5% | 1.6% | 4.2% | -1.10 pp | 0.67 |

## Notes and labels

- Opportunities: `est_jobs` is the employment proxy (Estimated; weights Assumed) and population is WorldPop (Estimated). Reach is Simulated from the travel-time matrix.
- `est_opportunity_index` = share x 5,000,000 (Assumed base): an index for display, not a count of jobs.
- Edge zones: point within 5000 m of the study-area bbox (Assumed). Their destinations outside the bbox are missing, so they are flagged and summarised separately.
- Every zone reaches itself, so a zone's own jobs and residents always count.

Column labels:

- `est_jobs_share`: simulated
- `est_opportunity_index`: simulated
- `population_share`: simulated
- `edge_zone`: assumed

## Checks

- 4-zone toy: shares per threshold and percentile, weighted quantiles, Gini, the headline and
  the sensitivity rows all match hand calculations (`tests/test_accessibility.py`).
- Toyville end to end: shares stay in [0, 1], never fall as the threshold grows, and the good-day
  p25 always reaches at least as much as the bad-day p75; the baseline sensitivity row equals
  the headline.
- Best-served zones (p50, 45 min): Vidhana Soudha / Cubbon Park (12.978, 77.590) at 23.8 %, KR
  Market (12.956, 77.577) at 23.5 %, Majestic at 23.3 %.
- The map and the GeoParquet were reviewed by the user in a browser and in QGIS (2026-10-08).

## Interpretation

- **The headline depends on the proxy weights**: 1.7 % (area only) to 3.8 % (POIs only); 2.7 %
  with the chosen 0.50/0.50. Quote it with its weighting.
- **The mean hides a very unequal distribution** (Gini 0.73 at 45 min; 0.68 to 0.77 under any
  weighting). The best-served zones reach almost a quarter of the city's estimated jobs within
  45 min, but the median resident reaches 0.4 % and 59.6 % of residents reach less than 1 %.
- **Coverage drives the low end.** 79.9 % of estimated jobs lie in zones whose point has a stop
  within an 800 m walk, but 31.2 % of residents live in zones without one (see
  `travel-time-matrix.md`). Those residents reach only what is within a 2 km walk.
- **Reliability**: from a good day (p25) to a bad one (p75), the 45-min headline moves from
  3.4 % to 2.2 %.
- **Edge zones** (2,470 within 5 km of the bbox, 8.1 % of residents) barely change the headline
  (2.7 % → 3.0 % when excluded).
- Bus times come from schedules without traffic (see `routing-analysis.md`), so real reach at
  peak hour is probably lower than simulated.
