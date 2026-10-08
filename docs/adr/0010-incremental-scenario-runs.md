# ADR 0010 — Incremental scenario runs: affected origins and cached walks

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

A full scenario run on Bengaluru rebuilds walks for all 10,661 zones (about 57 s) and routes
from every origin (about 45 s). Most scenarios change a few routes, and none changes stops or the
walk network. The phase plan asks for incremental recomputation that equals a full recompute,
with a full fallback.

## Decision

- **Changed trips by content, not by mutation type.** A trip is identified by feed, source id,
  piece, route and its full stop/arrival/departure sequence. Trips present in only one of the
  baseline and scenario networks are changed; their stops are the *changed stops*. Retimed trips
  count, so future mutations need no special handling.
- **Affected origins.** A journey can only change if it boards a changed trip. Up to that
  boarding it uses trips present in both networks, so the boarding stop is reached in the
  baseline no later. An origin is therefore affected only if, in the baseline, it reaches a
  changed stop by `last departure + max travel time`. One range search from the first departure
  decides this, because earliest arrival is monotone in departure time. All other origins' rows
  are copied from the baseline matrix.
- **Safety checks, else full.** Incremental runs require an unchanged stop table and a baseline
  matrix whose builder version, routing and accessibility settings, input manifests and output
  hashes all match. Otherwise the run is full and `run.json` says why (`full_reason`).
- **Cached walks.** Zone walks are stored under `results/_walks/<key>/`, keyed by the walk and
  zones manifests, the routing and accessibility settings and the engine (as for results). Only
  incremental runs read them; `--full` recomputes walks too, so comparing incremental with full
  also checks the cache. A dirty tree neither reads nor writes them.
- **Bytes, not just values.** Matrix parts are rechunked before writing: a part stitched from
  copied and recomputed rows otherwise gets one Parquet row group per chunk once a chunk exceeds
  about 100k rows (Bengaluru parts do; toy parts do not), giving equal values in different bytes.

## Consequences

- Correctness is tested as equality with `--full` on the toy city (five scenario shapes) and on
  the three Bengaluru scenarios, byte for byte on every Parquet output.
- For corridor-scale changes most transit-served origins can still reach a changed stop within
  120 minutes, so the routing saving is modest; most of the speed-up comes from cached walks.
