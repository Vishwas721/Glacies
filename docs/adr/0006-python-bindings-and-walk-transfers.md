# ADR 0006 — Python bindings package and walking transfers in Rust

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Phase 2 M6–M7 connects the Rust RAPTOR core to the Python pipeline. Two choices were needed:
how to ship the extension, and how to compute stop-to-stop walking transfers and point access
on a 1.47 M-node walk network.

## Decision

- **Bindings** live in `crates/raptor-py` (PyO3 0.29, abi3 for Python ≥ 3.11) and ship as the
  separate package `glacies-raptor`, built by maturin. The main project depends on it through a
  uv path source, so `uv sync` compiles it; `tool.uv.cache-keys` rebuilds it when Rust sources
  change. Typed stubs (`glacies_raptor.pyi`) keep mypy strict. The core crate stays PyO3-free.
- **Walking distances** are computed in Rust (`WalkGraph`): bounded Dijkstra on a CSR graph,
  with stops attached at their snapped position on an edge (fraction along it plus snap
  offset), parallel across sources with Rayon. scipy's Dijkstra was rejected because it returns
  a dense row per source (1.47 M nodes each).
- **Transfers** are all stop pairs within `routing.max_transfer_walk_m` on the network, in
  whole seconds rounded up at `routing.walking_speed_m_s`.
- **Arbitrary points** (journey origins, later zone centroids) attach to the nearest node of
  the main walk component via a KD-tree. OSM nodes average ~33 m apart, so this costs a few
  metres at most and avoids keeping a 1.6 M-geometry R-tree in memory.

## Consequences

- A Rust toolchain is needed for `uv sync`, locally and in the CI Python job (which now runs
  when `crates/` changes too).
- Bengaluru: router built in ~5 s from processed Parquet, with 27,394 transfer walks.
- Station platforms are joined through the walk network rather than GTFS `pathways.txt`;
  revisit if metro interchange times look wrong in M8 validation.
