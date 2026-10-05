# Data sources registry

Single source of truth for every external dataset. The machine-readable copy for Bengaluru is
`cities/bengaluru/city.toml`; keep the two in sync.

> **Status legend.** ✅ URL and licence verified by hand · ⚠️ not yet verified · ❓ source not yet
> identified. Verification: Phase 1 handoff, 2026-10-04.

| Dataset | Role | Source | Version used | License | Status | Nature |
|---|---|---|---|---|---|---|
| BMTC bus GTFS | Bus network & schedules | [Vonter/bmtc-gtfs](https://github.com/Vonter/bmtc-gtfs) | feed 20260907 | ODbL-1.0 | ✅ | Observed (incomplete) |
| BMRCL metro GTFS | Metro network & schedules | [Vonter/bmrcl-gtfs](https://github.com/Vonter/bmrcl-gtfs) | feed 20260817 | ODbL-1.0 | ✅ | Observed |
| BMRCL metro GTFS (frequencies) | Reference only | [Vonter/bmrcl-gtfs](https://github.com/Vonter/bmrcl-gtfs) | feed 20260817 | ODbL-1.0 | ✅ | Observed |
| BMRCL hourly ridership | Demand calibration (station entries/exits **and station-pair OD**) | [Vonter/bmrcl-ridership-hourly](https://github.com/Vonter/bmrcl-ridership-hourly) | downloaded 2026-10-04 | ODbL-1.0 | ✅ | Observed |
| OpenStreetMap | Walk network, POIs, stations | [Geofabrik](https://download.geofabrik.de/asia/india.html), southern zone | 2026-10-02 | ODbL-1.0 | ✅ | Observed |
| WorldPop India 100 m constrained | Trip origins | [WorldPop Hub](https://hub.worldpop.org/) | 2021, R2025A | CC-BY-4.0 | ✅ | Estimated (modelled raster) |
| Google Open Buildings | Employment proxy (floor area) | [Open Buildings](https://sites.research.google/open-buildings/) | v3, custom polygon export | CC-BY-4.0 / ODbL-1.0 | ✅ | Estimated (ML-detected) |
| ESA WorldCover 10 m | Employment proxy (land use) | [ESA WorldCover](https://esa-worldcover.org/) | 2021 v200, tile N12E075 | CC-BY-4.0 | ✅ | Estimated (classified) |

### Facts measured from the downloaded files (Observed)

| Feed | GTFS routes | Trips | Stops | Calendar |
|---|---|---|---|---|
| BMTC | 4,434 | 57,836 | 9,960 | one `service_id`, all 7 days, 2026-09-07 → 2027-09-07 |
| BMRCL | 3 | 3,279 | 488 (incl. platforms/entrances) | `weekday` (Tue–Sat), separate Monday, Sunday and holiday services |

GTFS route rows are **not** a coverage measure: one BMTC route number can appear as several GTFS
routes (directions/variants).

### Validation results (`glacies validate gtfs`, validator 0.1.0)

| Feed | Errors | Warnings | Notes |
|---|---:|---:|---|
| BMTC 20260907 | 0 | 6 rules | 2,693 distinct route numbers vs. 2,200–2,492 reference (**unverified**) → 108–122 %; 358 of 57,836 trips (0.6 %) have impossible speeds between stops; 1,885 of 9,948 stops lie outside the study bbox (stops reach lat 17.8°, lon 75.1°) |
| BMRCL 20260817 | 0 | 0 | 25 after-midnight trips (info) |

Full reports: `data/processed/bengaluru/reports/<dataset>/<snapshot>/gtfs_validation.md`.

## Known risks

- **BMTC feed coverage gap (high probability, high impact).** The feed is derived from the Namma
  BMTC app and omits routes without working telematics. Phase 1 must *measure* coverage, for example
  by comparing route counts against BMTC's published route list or OSM `route=bus` relations,
  and report it in the validation report. Every result must state the feed version used.
- **Upstream disappearance.** The unofficial feeds can vanish. `data/raw/` is append-only and must
  be backed up outside the repo.
- **Attribution obligations.** ODbL and CC-BY require attribution, and ODbL share-alike applies to
  derived *databases*. The UI footer and any exported dataset must credit OSM contributors, BMTC
  (via Vonter), WorldPop, Google, and ESA.
- **Population vintage.** WorldPop 2020 predates current Bengaluru growth. Treat it as Estimated
  and record the year in every manifest.

## Adding a dataset

1. Add a `[sources.<id>]` entry to the city's `city.toml`.
2. Add a row above, with status ⚠️ until verified.
3. Implement the downloader in `glacies.ingest` so it writes a `DatasetManifest`.
4. Add a validator and include its summary in the data-quality report.
