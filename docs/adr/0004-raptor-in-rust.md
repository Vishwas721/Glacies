# ADR 0004 — Implement RAPTOR in Rust, exposed to Python via PyO3

- **Status:** Accepted
- **Date:** 2026-10-03

## Context

Accessibility and assignment need on the order of 10⁶–10⁸ origin × departure-time queries per
scenario. A pure-Python router is far too slow, and NetworkX graphs blow the memory budget. External
engines (OpenTripPlanner, R5) work, but they are black boxes for scenario mutation and add a JVM
dependency.

## Decision

- Implement RAPTOR (Delling, Pajor, Werneck 2012) in Rust over flat, cache-friendly arrays
  (route → stops, route → trips × stop times, stop → routes, footpaths).
- Expose a narrow batch API to Python with PyO3/maturin: build timetable from Arrow/NumPy arrays,
  then many-to-many travel-time queries. Results come back as arrays, not Python objects.
- Use Rayon for parallelism across origins, with deterministic ordering of outputs.
- Validate against R5/OTP on a sample of OD pairs as an external check (Phase 2), not as a
  runtime dependency.

## Consequences

- Rust becomes a required toolchain.
- A build step (maturin) sits between Rust changes and Python tests.
- Correctness depends on our own tests, so toy networks with hand-computed answers are mandatory.
