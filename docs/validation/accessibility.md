# Accessibility — Bengaluru baseline (2026-10-07 run)

Output of `uv run glacies build accessibility` (copied from
`data/processed/bengaluru/accessibility/baseline/BUILD_REPORT.md`), followed by checks and an
interpretation. Reach is **Simulated**; jobs and population are **Estimated**; all parameters
are **Assumed**.

Builder 0.1.0 · 127,932 rows · 2,470 edge zones

## Headline (Simulated; jobs Estimated)

Residents can reach on average **2.3% of the city's estimated jobs** within 45 min by transit and walking (median over 07:30-09:30 departures; population-weighted mean over all zones).

## Population-weighted mean share reachable

| Measure | Percentile | 15 min | 30 min | 45 min | 60 min |
|---|---|---:|---:|---:|---:|
| Estimated jobs | p25 | 0.09% | 0.8% | 2.9% | 7.1% |
| Estimated jobs | p50 | 0.08% | 0.7% | 2.3% | 5.8% |
| Estimated jobs | p75 | 0.07% | 0.6% | 1.9% | 4.9% |
| Population | p25 | 0.07% | 0.6% | 2.1% | 5.1% |
| Population | p50 | 0.06% | 0.5% | 1.6% | 4.2% |
| Population | p75 | 0.06% | 0.4% | 1.3% | 3.4% |

p25 is a good day (a quarter of departures do at least this well), p75 a bad one.

## Distribution of estimated jobs reachable (p50)

Quantiles are over residents, not zones: q10 means 10 % of residents reach less.

| Scope | Threshold | Mean | q10 | q25 | q50 | q75 | q90 | Gini | Residents < 1 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all zones | 15 min | 0.08% | 0.00% | 0.01% | 0.04% | 0.09% | 0.2% | 0.64 | 99.7% |
| all zones | 30 min | 0.7% | 0.01% | 0.04% | 0.2% | 0.8% | 2.0% | 0.67 | 77.4% |
| all zones | 45 min | 2.3% | 0.01% | 0.05% | 0.4% | 3.3% | 7.4% | 0.71 | 59.7% |
| all zones | 60 min | 5.8% | 0.01% | 0.05% | 0.8% | 9.9% | 19.7% | 0.69 | 51.1% |
| excluding edge zones | 15 min | 0.08% | 0.00% | 0.01% | 0.04% | 0.09% | 0.2% | 0.63 | 99.7% |
| excluding edge zones | 30 min | 0.7% | 0.02% | 0.06% | 0.3% | 1.0% | 2.1% | 0.64 | 75.4% |
| excluding edge zones | 45 min | 2.5% | 0.02% | 0.08% | 0.6% | 3.8% | 7.7% | 0.69 | 56.1% |
| excluding edge zones | 60 min | 6.4% | 0.02% | 0.1% | 1.6% | 10.9% | 20.2% | 0.67 | 46.8% |

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

- 4-zone toy: shares per threshold and percentile, weighted quantiles, Gini and the headline all
  match hand calculations (`tests/test_accessibility.py`).
- Toyville end to end: shares stay in [0, 1], never fall as the threshold grows, and the good-day
  p25 always reaches at least as much as the bad-day p75.
- Majestic zone, p50, 45 min: 18.4496 % of estimated jobs, both in the output and in an
  independent recomputation straight from the matrix and the employment proxy.
- Best-served zones (p50, 45 min): around KR Market (12.956, 77.577) at 18.8 % and Vidhana
  Soudha / Cubbon Park (12.978, 77.590) at 18.6 %.

## Interpretation

- **The mean hides a very unequal distribution** (Gini 0.71 at 45 min). The best-served zones
  reach almost a fifth of the city's estimated jobs within 45 min, but the median resident
  reaches 0.4 % and 59.7 % of residents reach less than 1 %.
- **Coverage drives the low end.** 75.3 % of estimated jobs lie in zones whose point has a stop
  within an 800 m walk, but 31.2 % of residents live in zones without one (see
  `travel-time-matrix.md`). Those residents reach only what is within a 2 km walk.
- **Reliability**: from a good day (p25) to a bad one (p75), the 45-min headline moves from
  2.9 % to 1.9 %.
- **Edge zones** (2,470 within 5 km of the bbox) barely change the headline (2.3 % → 2.5 % when
  excluded): they hold 8.1 % of residents.
- Bus times come from schedules without traffic (see `routing-analysis.md`), so real reach at
  peak hour is probably lower than simulated.
