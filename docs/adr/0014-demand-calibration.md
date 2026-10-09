# ADR 0014 — Calibrate β on the shape of metro station entries

- **Status:** Accepted
- **Date:** 2026-10-09

## Context

The gravity model's β is the one free parameter of Phase 5 demand. The only strong observation
is BMRCL ridership: hourly entries and exits per station for 2025-08-01..09-30 (with
08-19..08-31 missing) and hourly station-pair counts for 2025-08-01..08-18 only. The model
covers home-to-work trips from zones within an 800 m walk of a stop; metro riders also arrive
by feeder bus, auto and two-wheeler and travel for other purposes, so simulated entries are a
fraction of observed ones.

## Decision

- **Ridership enters the engine through `glacies build ridership`** (canonical, Observed): dates
  as dates, station names matched to the network's stations (an unknown name fails the build),
  hours validated, duplicates rejected. File layouts are named formats (`vonter-hourly`), set
  per source in `city.toml`. In that format the station-pair hour is the *exit* hour (per exit
  station it sums exactly to the exit counts), so pair targets use exit hours.
- **Objective: shape, not level.** RMSE between simulated and observed shares of entries per
  station over the 08:00–10:00 window, averaged over the configured dates. The level ratio is
  reported, never fitted.
- **Station sets are fixed before the search.** Stations whose every line is in
  `exclude_lines` (service at the ridership dates differs from the routing timetable) are
  excluded; `held_out_stations` are never evaluated during the search; the rest train β. Shares
  are normalised within each set, so held-out counts cannot enter the objective through a
  denominator.
- **Search:** a log-spaced grid of β (ascending, each Furness run warm-started from the previous
  one), then golden-section steps on log β around the best grid point, at a coarser Furness
  tolerance; the chosen β is re-run at the configured tolerance. A best grid point at either end
  of the range is flagged.
- **Fit statistics** per set: share RMSE, R² of shares, Pearson r, GEH of counts after scaling
  the simulated total to the observed one (GEH is meant for hourly counts; these are two-hour
  means), and the level ratio. Station pairs whose two stations are in one set are a secondary
  check on the dates that have pair data.
- The chosen β is written into `demand.toml` by hand (with the calibration date), so a demand
  build never depends on whether a calibration happened to run.

## Consequences

- Calibration costs about 20 Furness runs (~47 min for Bengaluru); the station flows of each
  run are a join on the path table (ADR 0013).
- First result (2026-10-09): β = 0.0321 per minute, but the objective is flat over 0.027-0.037
  and R² of station shares is negative on training (−0.54) and held-out (−1.34) stations. The
  misfit comes from what the model leaves out (feeder, auto and two-wheeler access; rail
  transfers at interchanges; other purposes), so a better fit needs a richer access model, not
  a different β (docs/validation/demand.md).
- The result describes the fit of an all-or-nothing, crowding-free assignment of one trip
  purpose; Phase 6 assignment and more purposes may move β.
