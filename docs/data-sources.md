# Data sources registry

Single source of truth for every external dataset. The machine-readable copy for Bengaluru is
`cities/bengaluru/city.toml`; keep the two in sync.

> **Status legend.** ✅ verified by hand (URL, license, coverage) · ⚠️ from PRD/research and not yet
> verified · ❓ source not yet identified. Nothing is ✅ until Phase 1 is done.

| Dataset | Role | Source | License | Status | Nature |
|---|---|---|---|---|---|
| BMTC bus GTFS | Bus network & schedules | [Vonter/bmtc-gtfs](https://github.com/Vonter/bmtc-gtfs) | ODbL-1.0 | ⚠️ | Observed (incomplete) |
| BMRCL metro GTFS | Metro network & schedules | ❓ find in Phase 1 | ❓ | ❓ | Observed |
| BMRCL hourly ridership | Demand calibration target | [Vonter/bmrcl-ridership-hourly](https://github.com/Vonter/bmrcl-ridership-hourly) | ❓ check repo | ⚠️ | Observed |
| OpenStreetMap | Walk network, POIs, stations | [Geofabrik](https://download.geofabrik.de/asia/india.html) | ODbL-1.0 | ⚠️ | Observed |
| WorldPop India 100 m constrained 2020 (UN-adj.) | Trip origins | [WorldPop Hub](https://hub.worldpop.org/) | CC-BY-4.0 | ⚠️ | Estimated (modelled raster) |
| Google Open Buildings | Employment proxy (floor area) | [Open Buildings](https://sites.research.google/open-buildings/) | CC-BY-4.0 / ODbL-1.0 | ⚠️ | Estimated (ML-detected) |
| ESA WorldCover 10 m | Employment proxy (land use) | [ESA WorldCover](https://esa-worldcover.org/) | CC-BY-4.0 | ⚠️ | Estimated (classified) |

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
