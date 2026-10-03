# Phase 3 — Accessibility Engine

## 1. Goal & why

Answer "**how much of the city's opportunity can people reach within X minutes by transit?**" for
every zone, at 15/30/45/60 min, for both jobs (estimated) and population. This is Glacies's
headline metric, and it needs only routing + zones, with no demand model. (PRD §32–33, §60)

## 2. Prerequisites

Phase 1 zones with population, building area, land cover and POIs; Phase 2 zone-to-zone
travel-time matrices over a departure window.

## 3. Research before starting

- **Cumulative-opportunity** vs. **gravity-based** accessibility measures. Read a review such as
  Geurs & van Wee (2004), *Accessibility evaluation of land-use and transport strategies*.
- Conveyal's methodology notes on accessibility with **travel-time percentiles** over a departure
  window (why the median, 25th percentile etc. matter for transit).
- Employment proxies in data-poor cities: papers using building footprints/night lights as job
  proxies. Note how they validate. Search "building footprint employment estimation".
- Known Bengaluru employment hubs (Whitefield/ITPL, Electronic City, Outer Ring Road tech parks,
  Manyata, CBD/MG Road, Peenya industrial area) for a qualitative check.
- Equity framing: population-weighted accessibility and how to report the distribution, not only
  the mean (e.g. Gini/percentiles).

## 4. Decisions you must make

| Decision | Guidance | Your choice |
|---|---|---|
| Departure window | 07:30–09:30 weekday (AM peak) | |
| Travel-time statistic | median over the window (recommended), plus 25th/75th percentile | |
| Thresholds | 15/30/45/60 min (PRD) | |
| Employment proxy formula | e.g. `w1·non-residential floor area + w2·commercial POIs`, by land-use class | |
| Proxy weights | Assumed: document them and run sensitivity checks | |
| Summary metric | population-weighted mean share of jobs reachable within 45 min | |

## 5. Your hands-on tasks

- [ ] Define the employment-proxy formula and weights. Record why, and label it **Estimated/Assumed**.
- [ ] Draw (in QGIS) rough polygons for 6–10 known employment hubs. The proxy must rank these
      zones in the top deciles. This is your qualitative validation.
- [ ] Review the first accessibility map: does it match intuition (CBD and metro corridors high,
      periphery low)? Note surprises; they are often data bugs.

## 6. Agent tasks

1. **M1 — Employment proxy**: `glacies.demand.attraction` (shared later with Phase 5) computing
   `employment_score` per zone from building area, land use and POIs; normalised to a city total
   (e.g. scaled to a stated assumed job total). Sensitivity: alternative weightings.
2. **M2 — Travel-time matrix job**: zone centroids (or population-weighted points) → Phase 2
   range-RAPTOR → percentiles per OD → Parquet `tt_matrix/{p25,p50,p75}`.
3. **M3 — Accessibility metrics**: cumulative jobs/population reachable per zone per threshold;
   city summaries (population-weighted mean, distribution percentiles); outputs to Parquet with
   `DataNature` columns.
4. **M4 — Reporting**: `glacies accessibility bengaluru` CLI producing a Markdown/HTML report with
   static maps (matplotlib/geopandas) and a GeoParquet for QGIS.
5. **M5 — Validation hooks**: hub-polygon check for the proxy; a sensitivity table showing how the
   headline metric moves under different proxy weights.

## 7. Kickoff prompt

```text
We are starting Phase 3 (Accessibility) of Glacies. Read CLAUDE.md and docs/phases/03-accessibility.md,
including my decisions (window, percentiles, employment-proxy formula and weights).

Implement milestone M<N> only. Start with a toy example: 4 zones, a hand-made travel-time matrix and
known jobs, with expected accessibility values computed by hand in the test. Requirements:
- the employment proxy is always labelled Estimated and its weights Assumed, in data and in reports;
- results are written to Parquet and are deterministic;
- large matrices are processed with DuckDB/Polars in chunks, never materialised as Python objects;
- small Conventional Commits on branch phase/03-m<N>; all checks green; open a PR.
```

## 8. Deliverables

`src/glacies/analytics/accessibility.py`, `src/glacies/demand/attraction.py`, CLI command, report
template, `data/processed/bengaluru/accessibility/baseline/*.parquet`.

## 9. Definition of done

- [ ] Baseline accessibility for all zones × 4 thresholds × jobs/population is computed reproducibly.
- [ ] The toy accessibility tests match hand calculations.
- [ ] ≥ 80 % of your hand-drawn hub zones fall in the top 20 % of `employment_score`.
- [ ] The report states which numbers are Observed / Estimated / Simulated / Assumed.
- [ ] A sensitivity table exists for at least 3 proxy weightings.

## 10. Risks & pitfalls

- **Proxy circularity**: don't use transit stop density as a job proxy input.
- **Edge effects**: zones near the bbox edge look artificially poor. Buffer the destination set or flag them.
- **Single-departure artefacts**: always use the window.
- **Overclaiming**: say "estimated jobs", never "jobs".

**Core:** cumulative accessibility, employment proxy, sensitivity. **Later:** gravity-based
accessibility, per-group equity analysis, POI-type opportunities (schools, hospitals).
**Never:** claiming precise job counts.
