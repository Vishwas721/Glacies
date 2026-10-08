# ADR 0009 — Content-addressed scenario results with a run record

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

A scenario run rebuilds the travel-time matrix and accessibility on the scenario network (about
6 minutes for Bengaluru with a full recompute). Re-running an unchanged scenario should be free,
any change that can alter results must force a recompute, and every result must say exactly what
produced it (PRD §53).

## Decision

- Results live in `data/processed/<city>/results/<key>/` with `transit/`, `tt_matrix/`,
  `accessibility/` and `run.json`. They are written to a staging directory and renamed into
  place, so a crashed run never leaves a half-written result that looks valid.
- `key` = sha256 of canonical JSON holding: a key version; the city id; the manifest hashes of
  the baseline stages the run reads (transit, walk, zones, attraction); the hash of the
  mutations; the full city config; the glacies and glacies-raptor versions, git commit and
  dirty flag; and the seed.
  - Stage manifests rather than `BUILD.json`: they are what the run actually reads, and they
    stay correct when a stage is rebuilt on its own.
  - The whole city config rather than chosen sections: a little over-conservative, but a new
    parameter can never be forgotten in the key.
  - Titles, descriptions and expected changes are excluded, so editing prose keeps the cache.
- A source tree with uncommitted changes never reads the cache (the commit no longer describes
  the code). Its results are still written, under a key that includes the dirty flag, so they
  can never be served to a clean run. `--force` recomputes.
- `run.json` records the scenario file and its hash, the key and everything in it, the raw
  dataset versions from `BUILD.json`, per-mutation trip changes, output manifest hashes, the
  headline, and start/finish timestamps. Timestamps appear only in `run.json`, never in
  computed outputs, so recomputing gives byte-identical Parquet.

## Consequences

- Cache hits are a file read. Cache entries are never cleaned automatically; `build-city
  --clean` removes them with the rest of `processed/<city>/`.
- Changing any part of `city.toml`, even a source note, invalidates every cached result.
