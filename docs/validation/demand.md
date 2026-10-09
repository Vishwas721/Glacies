# Synthetic demand — Bengaluru (Phase 5)

Everything here is **Estimated** unless labelled otherwise. Priors are Assumed and live in
`cities/bengaluru/demand.toml` with their citations. The numbers below come from
`uv run glacies build demand` on 2026-10-09 (`data/processed/bengaluru/demand/baseline/`).

## M1–M2: trip ends and the gravity model (β provisional)

Settings: home-based work, 08:00–10:00; trip rate 0.10 × transit share 0.45 (Assumed);
friction `exp(-0.05 × p50 minutes)`. **β = 0.05 is a placeholder** until the M4 calibration
against BMRCL ridership replaces it.

| Quantity | Value |
|---|---|
| Zones with a stop within 800 m walk | 3,465 of 10,661 (68.7 % of population) |
| Origin / destination zones | 3,443 / 3,439 |
| People left out (no stop / stop but no reachable destination) | 3,910,957 / 13,613 |
| Trips (ΣO = ΣD) | 386,504 (240,491–601,228 with both priors at their range ends) |
| Attraction moved to make the targets attainable (ADR 0012) | 7,373 trips (1.9 %), 238 blocks |
| Pairs with trips / pairs dropped as unattainable | 1,472,198 / 42,585 |
| Furness | converged in 1,590 iterations, row error 1.0e-6, column error 5e-15 |
| Mean door-to-door time (p50, Simulated) | 55.9 min |
| Mean distance (straight line 7.7 km × 1.15 detour) | 8.8 km — within the accepted 8–14 km, below the 11 km prior |
| Rerun | byte-identical `trip_ends.parquet` and `od.parquet` |

Trips by door-to-door time: ≤15 min 3.8 %, 15–30 23.5 %, 30–45 12.9 %, 45–60 16.2 %,
60–90 27.6 %, 90–120 16.0 %.

**Hubs.** The 28 zones overlapping the 8 hand-drawn employment hubs receive 2.7 % of trips while
holding 1.4 % of the population. RMZ Ecoworld receives none: no zone overlapping it has a stop
within the 800 m walk. The ten largest destinations lie in Indiranagar, the MG Road / CBD area,
Koramangala, Marathahalli and the Rajajinagar area.

**Reading.** Long transit trips are common (44 % over an hour) and the mean distance sits at the
low end of the accepted range, so β will probably fall when calibrated; that is for M4 to show.
