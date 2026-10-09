# ADR 0015 — Rides to stations at the home end of demand trips

- **Status:** Accepted
- **Date:** 2026-10-09

## Context

The β calibration (ADR 0014) left the station-entry shares worse than a uniform guess (held-out
R² −1.34). The largest misses are terminals and stations with big catchments beyond the 800 m
access walk: in the model only people who walk can use transit, while in Bengaluru many metro
riders arrive by auto, shared auto, two-wheeler or feeder bus. A quick test that added the
population 0.8–4 km from each station to simulated entries (one weight fitted on training
stations) raised held-out R² to 0.03. The access walk itself (`[routing] max_access_walk_m`)
cannot simply be raised: it drives accessibility (Phase 3) and scenarios (Phase 4), applies at
both ends of every trip and to every bus stop, and a "blended" walk/auto speed describes no
real traveller.

## Decision

- **A ride is a separate, board-only access leg.** `[demand.ride_access]` in `demand.toml`
  gives each zone a ride to every platform of the calibration mode (the metro) within `max_km`
  straight line, costing `penalty + distance x detour / speed` (all Assumed). In the router a
  board-only access may only be used to board a vehicle at that stop: the stop does not count
  as reached, so "ride to a station and walk out" is never a transit journey. A stop the zone
  can walk to keeps the walk. The single-departure `search` (journey planner) rejects
  board-only access, because its rounds inherit round 0's arrivals.
- **Home end only.** Trips start with a walk or a ride but end with a walk: zones reached only
  by the ride produce trips and attract none. The work end of an AM commute is rarely an auto
  ride from the metro in this model's terms, and the PRD's accessibility stays walk-based.
- **Demand has its own matrix.** `glacies build demand-matrix` writes
  `demand_matrix/<scenario>` with the rides; when rides are configured, `paths` and `demand`
  use it instead of `tt_matrix`. Accessibility and scenarios keep the walk-only matrix, so their
  published numbers do not move.
- **The ride share is reported, not fitted.** `glacies build station-flows` reports the share
  of metro trips whose journey starts with a ride; a published access-mode split for the city
  is a check on the speed, penalty and radius.

## Consequences

- One more matrix build (minutes) before paths; calibration and sensitivity reuse it.
- Ride parameters are Assumed until a station access survey replaces them; they are a new
  source of uncertainty alongside β and the employment proxy.
- Rides go only to metro stations, not to bus stops; a feeder-bus model would be a separate
  decision.
- First result (2026-10-09, 4 km at 15 km/h + 5 min): held-out R² of station entry shares rose
  from −1.34 to 0.40 and training R² from −0.54 to 0.12 (β recalibrated to 0.0259); it stays
  0.30–0.45 across the sensitivity variants. 84 % of simulated metro trips start with a ride,
  above a quoted 59 % first/last-mile IPT share, so rides are probably too attractive in an
  all-or-nothing assignment (docs/validation/demand.md).
