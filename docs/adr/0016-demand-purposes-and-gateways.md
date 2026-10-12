# ADR 0016 — Further trip purposes and terminal gateways in demand

- **Status:** Accepted
- **Date:** 2026-10-09

## Context

After rides to stations (ADR 0015), demand still had one purpose (home-based work) and only
home zones produced trips. Two groups of morning metro riders were missing: students (education
is 15 % of trips in the CMP 2020 household survey; WRI India 2023 found 22 % of Bengaluru metro
riders travel for education) and passengers arriving at rail and long-distance bus terminals.
The metro stations at terminals (Majestic, KSR railway station) were under-predicted.

## Decision

- **Purposes.** `[[demand.purposes]]` adds purposes balanced exactly like the main one
  (doubly constrained gravity, attainable attractions, Furness), each with its own trip rate,
  transit share and attractor (a column of `zones.parquet`, e.g. `poi_education`). They share
  β and the cost with the main purpose, an Assumed simplification that keeps calibration
  one-dimensional. Trips of all purposes add up in `od.parquet`, which gains a `purpose`
  column; each extra purpose writes `trip_ends_<name>.parquet`.
- **Gateways.** `[demand.gateways]` sends `factor x daily_passengers` trips from the zone
  containing each terminal, to the main purpose's attractions weighted by the friction
  (singly constrained). The factor stands for unpublished quantities (share of arrivals in the
  window, arrivals per counted passenger, share continuing by transit), so `glacies demand
  calibrate` fits it on the training stations: trips are linear in the factor, so at each β
  the best factor comes from station counts without another Furness run. `enabled = false`
  keeps the stations on record without building trips.
- **Sensitivity** varies each purpose's level by its own priors; gateway trips keep their
  factor.

## Consequences

- For Bengaluru, education was kept: it barely changes the station-share fit (held-out R² 0.39
  either way) but adds the students who are a quarter of metro riders (model 27.6 % of metro
  trips, WRI 24 % of work and education riders).
- Gateways were built, fitted and **switched off**: one factor for all terminals fixed Majestic
  (a training station) but over-predicted Yeshwantpur (held out), lowering held-out R² from
  0.39 to 0.31. Deciding this on the held-out result uses that set once for a yes/no model
  choice; the docs say so. Terminal arrival counts per station would be needed to try again.
- Calibration fails no longer when a station set has no counts (e.g. no excluded lines), which
  matters for a second city.
