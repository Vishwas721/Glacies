# Phase 7 — API, Jobs & Visualisation

## 1. Goal & why

Turn the pipeline into the **Glacies experience** (PRD §73): load the baseline, see accessibility,
build a scenario in the UI, run it asynchronously, and explore before/after differences on a map.
(PRD §38–50, §67)

## 2. Prerequisites

Phases 3–6 produce Parquet outputs and a scenario runner callable from Python.

## 3. Research before starting

- [FastAPI](https://fastapi.tiangolo.com/): background tasks vs. a real queue; dependency injection;
  streaming responses.
- Job queues on Redis: **RQ** (simplest), **arq** (async), Dramatiq. Pick one, given you have one
  worker process on one machine.
- [MapLibre GL JS](https://maplibre.org/) + free basemap options without API keys (OpenFreeMap,
  Protomaps PMTiles self-hosted, or OSM raster with attribution rules).
- [deck.gl](https://deck.gl/): `H3HexagonLayer`, `PathLayer`, `TripsLayer`, `ArcLayer`; binary
  attributes and pre-aggregation for performance (PRD §42).
- Serving vector data: GeoJSON for small layers, **FlatGeobuf/GeoArrow/MVT** (e.g.
  `ST_AsMVT` from PostGIS) for big ones.
- Data-viz basics for diverging colour scales (Δ accessibility) and colour-blind-safe palettes.
- TanStack Query for server state in React.

## 4. Decisions you must make

| Decision | Guidance | Your choice |
|---|---|---|
| Queue library | RQ (recommended for simplicity) | |
| Basemap | OpenFreeMap or self-hosted PMTiles (zero cost, no key) | |
| Network data transport | GeoJSON per route on demand + MVT for zones | |
| State management | TanStack Query + local component state (avoid Redux) | |
| Playback | 15-min time slices of aggregated segment flows | |
| Auth | none (local tool) | |

## 5. Your hands-on tasks

- [ ] Sketch the 3-panel UI (PRD §39) on paper and decide which metrics appear in the right panel.
- [ ] Choose the colour scales: sequential for levels, diverging for deltas.
- [ ] Rehearse the PRD §73 demo story with the three scenarios from Phase 4 and note what the UI
      must show at each step.
- [ ] Usability pass: can someone else run a scenario without your help?

## 6. Agent tasks

1. **M1 — Read API**: `/api/cities`, `/api/routes`, `/api/routes/{id}`, `/api/stops`, `/api/network`
   (from PostGIS / Parquet via DuckDB), with Pydantic response models, OpenAPI, and tests.
2. **M2 — Routing API**: `POST /api/route` (PRD §43) backed by the PyO3 engine kept warm in-process.
3. **M3 — Scenario CRUD**: `POST/GET/PATCH/DELETE /api/scenarios` storing the Phase 4 JSON + metadata.
4. **M4 — Simulation jobs**: `POST /api/simulations` → Redis queue → worker runs scenario pipeline
   with progress updates; `GET /api/simulations/{id}` states QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED;
   results endpoints `/metrics`, `/accessibility`, `/flows`, `/crowding` served from Parquet via DuckDB.
5. **M5 — Map**: MapLibre basemap + deck.gl layers for routes, stops, population, employment
   (labelled *Estimated*), accessibility hexes; layer toggles.
6. **M6 — Scenario builder UI**: route list with toggles (remove), headway editor, simple add-route
   (pick stops on the map); validate client-side against the JSON Schema.
7. **M7 — Comparison UI**: baseline/scenario/Δ views, metrics panel (PRD §31/§39), removed/added/
   modified route styling (PRD §41), and a data-nature badge on every number.
8. **M8 — Flow playback**: time-slider over aggregated segment flows (PRD §42).
9. **M9 — E2E**: Playwright smoke test of the demo story; docker compose profile running api + worker.

## 7. Kickoff prompt

```text
We are starting Phase 7 (API, Jobs & Visualisation) of Glacies. Read CLAUDE.md, docs/phases/07-api-visualisation.md
(with my decisions and UI sketch notes) and the PRD sections 38–50.

Implement milestone M<N> only. Rules:
- API responses use Pydantic models; large data is served from Parquet via DuckDB or as MVT, never
  by loading whole tables into memory per request;
- the frontend never receives per-passenger data; aggregate on the server;
- every displayed number shows its data-nature label (Observed/Estimated/Simulated/Assumed);
- no paid map services or API keys; include OSM and dataset attributions in the UI;
- tests: pytest for endpoints, vitest for components; Playwright for the end-to-end flow (M9);
- small Conventional Commits on branch phase/07-m<N>; all checks green; open a PR with screenshots.
```

## 8. Deliverables

`src/glacies/api/routers/*`, `src/glacies/worker.py`, `web/src/{map,scenario,compare,playback}/`,
compose services for `api` and `worker`, `docs/demo.md` (the demo script).

## 9. Definition of done

- [ ] The full PRD §73 demonstration works from the browser on a fresh machine following the README.
- [ ] Simulations run asynchronously with visible progress and can be cancelled.
- [ ] The map stays responsive (≥ 30 fps panning) with all zones and routes loaded.
- [ ] Every number in the UI has a data-nature label; attributions are visible.
- [ ] The E2E smoke test passes in CI.

## 10. Risks & pitfalls

- **Shipping raw data to the browser**: pre-aggregate and tile.
- **Long synchronous requests**: anything > 1 s goes through the queue.
- **UI scope creep**: no auth, no multi-user, no styling rabbit holes until the demo works.
- **Basemap terms**: some "free" tile servers forbid heavy use. Prefer self-hosted PMTiles.

**Core:** endpoints in PRD §43–46, job queue, map layers, scenario builder, comparison, playback.
**Later:** shareable scenario links, export (CSV/GeoParquet), report PDF.
**Never:** LLM-first scenario interface, cloud deployment.
