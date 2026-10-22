# ADR 0020 — The API reads Parquet through DuckDB and labels every number it returns

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Phase 7 puts an HTTP API in front of the pipeline for the map UI (PRD §43–46). The phase plan
suggested serving the network "from PostGIS / Parquet via DuckDB" and zones as MVT tiles. PostGIS
runs in Docker, which is usually not running on the development machine, and the PostGIS tables
are a copy of the Parquet outputs made by `glacies load postgis` for QGIS. The outputs differ a
lot in size: 10,661 zones, 9,964 stops and 17,348 stop-to-stop segments, but 1.5M trip-segment
loads and 1.8M assigned OD pairs. The canonical network keeps no GTFS shapes.

## Decision

- **Parquet is the source.** Endpoints query `data/processed/<city>/` with DuckDB (pinned to
  1.5.x; 2.0.0 was a day old when this was written), one in-memory connection per query, file
  paths from the city configuration only. PostGIS stays the QGIS copy; the API does not need
  Docker until the job queue (M4, ADR 0021).
- **City-scoped paths.** `/api/cities/{city}/routes` and so on, not the PRD's `/api/routes`:
  the engine is city-agnostic, so the city is part of every request.
- **Map layers by size.** Routes, stops and segments are GeoJSON (gzip shrinks them about ten
  times: the segments are 3.8 MB raw, 0.4 MB gzipped). Zones are columns of H3 cell ids and
  values; the browser draws the hexagons, so no vector tiles are needed. Per-trip, per-OD and
  per-passenger tables are never sent; later endpoints aggregate them first.
- **Straight lines.** Without shapes, lines join consecutive stops; responses label that
  geometry Assumed.
- **Labels in every response.** Responses with numbers carry `fields`: unit, data nature and
  meaning per numeric field. A test walks each response and fails on an unlabelled number.
- **Routing in-process.** `POST /route` builds the router on first use (and at startup in the
  background) and keeps it; a plan takes tens of milliseconds, under the one-second limit above
  which work goes through the queue.
- **Scenarios are files.** The API stores the Phase 4 JSON documents, nothing else, so a scenario
  made in the UI is exactly what `glacies scenario run` reads. Repository scenarios
  (`scenarios/<city>/`) are read-only; the user's live in `data/scenarios/<city>/`, outside
  `processed/`, which clean builds delete. Writes are checked against the schema and the baseline
  network's route and stop ids.

## Consequences

- The API needs only the processed folder to answer; it is as current as the last build.
- Map layers are cached in memory per file version, so a rebuild is picked up without a restart.
- Scenario edits from the UI are not versioned beyond the file on disk.
