# Phase 1 — Data Foundation

## 1. Goal & why

A **trustworthy, reproducible Bengaluru dataset**: one command rebuilds every canonical dataset
from archived raw inputs, and each input has a provenance manifest and a validation report.
Everything downstream inherits the quality, or the errors, of this phase. (PRD §9–17, §55, §62)

## 2. Prerequisites

Phase 0 merged; `docker compose up -d` healthy; about 30 GB free disk.

## 3. Research before starting

**GTFS**
- [GTFS Schedule reference](https://gtfs.org/schedule/reference/): read `stops`, `routes`,
  `trips`, `stop_times`, `calendar`, `calendar_dates`, `frequencies`, `shapes`. Pay attention to
  times > 24:00:00, `location_type` (stations vs. platforms), and `frequencies.exact_times`.
- The [Vonter/bmtc-gtfs](https://github.com/Vonter/bmtc-gtfs) README: how it is generated, update
  cadence, known gaps, licence.
- Look at the [MobilityData gtfs-validator](https://github.com/MobilityData/gtfs-validator) rule list.
  Glacies's validator should cover the same classes of errors (we write our own lightweight one, but
  can run theirs as a cross-check).
- Find a **metro GTFS** for BMRCL. Search Vonter's repos, Transitland, and Mobility Database. If
  none exists, the fallback is hand-building metro GTFS from the published line maps and timetable
  (a small, well-defined job: 2–4 lines, about 80 stations).

**OSM**
- [Geofabrik India extracts](https://download.geofabrik.de/asia/india.html): which extract covers
  Bengaluru (India is split into zones, so pick the smallest that contains the bbox).
- [osmium-tool](https://osmcode.org/osmium-tool/manual.html): `extract --bbox`, `tags-filter`.
- [pyrosm](https://pyrosm.github.io/) *or* [OSMnx](https://osmnx.readthedocs.io/): how to get a
  walk network as edge/node tables. Use them for extraction only, never as the canonical graph.

**Rasters & buildings**
- WorldPop *constrained* vs *unconstrained*, and *UN-adjusted*: what each means for totals.
- Google Open Buildings v3: fields (`area_in_meters`, `confidence`), how to download by S2 cell or tile.
- ESA WorldCover classes (built-up = 50 etc.).
- Concepts: CRS, why to compute areas/distances in a projected CRS (UTM 43N, EPSG:32643), raster
  zonal statistics.

**Zoning**
- [H3](https://h3geo.org/docs/core-library/restable): resolutions 7, 8, 9 (cell area and edge
  length). Read the trade-offs: resolution 8 (about 0.74 km²) gives about 3–4k cells for Bengaluru,
  which is manageable for OD matrices.

## 4. Decisions you must make

| Decision | Options / guidance | Your choice |
|---|---|---|
| Study area | bbox in `city.toml` vs. official BBMP/BDA boundary polygon | **bbox in `city.toml`** for now; official polygon later (Assumed) |
| Zone resolution | H3 r8 (recommended), r9 finer but about 7× more cells | **H3 r8** (Assumed) |
| Metro source | found GTFS / hand-built GTFS | **Found:** Vonter/bmrcl-gtfs (exact timetable feed; frequency-based variant archived for reference) |
| Service date | one representative weekday (e.g. a Tuesday) to freeze the timetable | **Typical non-holiday Tuesday** in the feed range. BMTC feed has one 7-day service, so this only affects metro (Assumed) |
| Storage split | PostGIS for geometry + metadata; Parquet for big tables (recommended) | **PostGIS + Parquet** split |
| Canonical schema format | Parquet tables + Pydantic/Arrow schema (recommended) | **Parquet + Pydantic/Arrow** |

_Decisions recorded 2026-10-04 from the Phase 1 handoff._

## 5. Your hands-on tasks

- [ ] Verify every source in `docs/data-sources.md`: open the URL, confirm the licence, flip ⚠️ → ✅.
- [ ] Download anything behind click-through terms yourself and place it in `data/raw/…`.
- [ ] Open the BMTC GTFS stops and the clipped OSM in **QGIS** (free) and eyeball it: are stops on
      roads? Do major corridors (Outer Ring Road, Hosur Road, Bellary Road) have service?
- [ ] Estimate **coverage**: compare the number of routes in the feed against a reference (BMTC
      website route count, OSM `route=bus` relations). Write the figure in the validation report notes.
- [ ] Back up `data/raw/` outside the repo.

## 6. Agent tasks

Milestones. Do one PR per milestone.

1. **M1 — Ingest framework:** `glacies ingest <dataset>` CLI (Typer); reads `city.toml`; downloads
   into `data/raw/<city>/<dataset>/<date>/`; writes a `manifest.json` (`DatasetManifest`); skips if
   the checksum is unchanged.
2. **M2 — GTFS validator:** structural checks (required files/fields, ID integrity, orphans,
   duplicates) and semantic checks (time monotonicity per trip, times > 24h handled, coordinates
   inside bbox, calendar validity, speeds between consecutive stops < threshold). Outputs a
   JSON + Markdown report like PRD §55, with error/warning severity.
3. **M3 — Canonical transit model:** GTFS → canonical Parquet tables (`stops`, `routes`, `patterns`,
   `trips`, `stop_times`, `services`) using integer IDs, a service day filter, and a mapping back to
   source IDs. Source-agnostic schema (PRD §17), with merged bus + metro feeds and a `mode` column.
4. **M4 — OSM walk network:** clip with osmium, extract the pedestrian network to Parquet
   (`nodes`, `edges` with length in metres), snap stops to the network, and flag stops > 300 m away.
5. **M5 — Spatial layers** (⚠️ needs an Open Buildings re-export for the enlarged bbox first, see `docs/data-sources.md`): H3 zones over the study area; WorldPop zonal sum per zone; Open
   Buildings footprint area per zone; WorldCover built-up share per zone; OSM POIs by category per
   zone. Load zones + stops + routes into PostGIS.
6. **M6 — Rebuild command:** `glacies build-city bengaluru` runs all of the above idempotently and
   writes `data/processed/bengaluru/BUILD.json` listing every input manifest and processor version.

Libraries: polars or pyarrow for tables, duckdb for SQL over Parquet, geopandas/shapely for
geometry, rasterio + exactextract or rasterstats for zonal stats, h3, pyrosm or osmium bindings,
psycopg + geoalchemy/SQL for PostGIS, typer for the CLI. Add them in their own `build(py)` commits.

## 7. Kickoff prompt

```text
We are starting Phase 1 (Data Foundation) of Glacies. Read CLAUDE.md, docs/phases/01-data-foundation.md
(including my decisions in section 4), docs/data-sources.md and cities/bengaluru/city.toml.

Implement milestone M<N> only. Before coding, show me a short plan: modules, file layout, schemas
(column names + types), and which libraries you will add. After I approve:
- write tests first using tiny fixture files under tests/fixtures/ (a 3-route toy GTFS, a small
  OSM extract or synthetic edges, a tiny raster), never the real city data;
- keep everything city-agnostic: city-specific values come from city.toml;
- every downloaded or derived dataset gets a DatasetManifest;
- make small Conventional Commits as you go on branch phase/01-m<N>;
- run all checks from CLAUDE.md before each commit;
- finish by opening a PR with the template filled in, then summarise what I need to verify by hand.
```

## 8. Deliverables

- `src/glacies/ingest/`, `src/glacies/validate/gtfs.py`, `src/glacies/model/` (canonical schema)
- `glacies` CLI entry point in `pyproject.toml`
- `data/processed/bengaluru/{transit,walk,zones}/*.parquet` + PostGIS tables
- `data/processed/bengaluru/reports/gtfs_validation.{json,md}`
- `tests/fixtures/toy_gtfs/`, with tests per validator rule

## 9. Definition of done

- [ ] On a clean `data/` directory, `glacies build-city bengaluru` rebuilds everything from
      `data/raw/` with no manual steps (PRD §62 DoD).
- [ ] Running it twice produces byte-identical Parquet files (determinism).
- [ ] A validation report exists for each GTFS feed, with counts, warnings and estimated coverage.
- [ ] The sum of zone population ≈ WorldPop total for the bbox (within 1 %).
- [ ] Every Parquet has a matching manifest; `BUILD.json` lists them.
- [ ] Stops, routes and zones render correctly in QGIS from PostGIS.

## 10. Risks & pitfalls

- **Times > 24:00:00.** Store as seconds since service-day midnight (`u32`), never as `datetime.time`.
- **`frequencies.txt`.** Expand frequency-based trips into explicit trips for routing (and keep
  the headway for scenarios).
- **Duplicate/near-duplicate stops** across bus and metro feeds. Don't merge; create footpaths
  later (Phase 2).
- **Memory.** Do not load the whole Karnataka/zone PBF in Python. Clip with osmium first.
- **CRS mistakes.** All areas and distances use EPSG:32643; storage stays EPSG:4326.
- **Scope creep.** No GTFS-RT, no road speeds, no elevation.

**Core:** BMTC + metro GTFS, walk network, population, buildings, land cover, POIs, H3 zones,
validation, rebuild command. **Later:** official boundary polygons, census ward data, multiple
service days. **Never (for now):** GTFS-RT, weather, elevation.
