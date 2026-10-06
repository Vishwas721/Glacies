# Routing benchmark

City `bengaluru`, 200 seeded random stops (seed 2026).

Machine: 16 logical CPUs. Router build: **2.84 s**
(process memory afterwards 681 MB).

| Query | Runs | Median | p95 |
|---|---:|---:|---:|
| one-to-one plan (08:30) | 200 | 21.9 ms | 31.9 ms |
| one-to-all earliest arrivals (08:30) | 200 | 25.1 ms | 35.3 ms |
| range search, 120 departures 07:30-09:29 | 50 | 113.2 ms | 811.5 ms |

**Parallel range searches:** 200 origins x 120 departures in
15.29 s across all CPUs. Extrapolated to one origin per populated zone
(10,525 zones): **about 13.4 min** for an all-zones
120-minute travel-time matrix (zone access walks add little; Phase 3 measures it for real).
Peak process memory during the run: 1,438 MB.

Targets (docs/phases/02-routing-engine.md §9): one-to-one < 50 ms, one-to-all < 200 ms,
all-zones x 120-min matrix < 30 min with < 8 GB.
