# ADR 0018 — Crowding-aware assignment: fixed choice set, generalised cost, logit and MSA

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

All-or-nothing assignment (ADR 0017) sends every trip on its fastest journey. On Bengaluru it
puts about twice the observed riders through the metro gates, piles thousands of people onto
single express buses and gives 1.48 transfers per trip. RAPTOR finds earliest arrivals only, so
it cannot route on a cost that changes with crowding, and re-routing every iteration of a
crowding loop would repeat the same searches many times.

## Decision

- **Fixed choice set.** Each OD pair gets up to three alternatives, routed once over the
  departure window: the fastest journey, the fastest on buses only (the timetable without metro
  trips) and the fastest with at most one transfer. Each is a *bundle*: the share of its trips
  on every ride `(trip, board, alight)` and the departure-weighted mean of its fixed costs.
  Alternatives that ride exactly the same vehicles are merged. Walking all the way is judged on
  the fastest search, as in all-or-nothing, and is not part of the logit.
- **Generalised cost** (in-vehicle minutes): walk 2.0, wait 2.0, transfer 5 min (inside DfT
  TAG M3.2 Table 1), riding to a station 1.0, fares over the value of time, and in-vehicle
  minutes times the crowding multiplier of every segment ridden (TAG M3.2 Table 3 by standee
  density, held at crush). Metro fares are BMRCL bands by station hops (the 2025 rule), bus
  fares 2 km stages reduced by the free-travel share, and rides to stations pay the auto fare.
- **Logit and MSA.** Trips split between a pair's alternatives by a logit on cost. The loop
  computes loads, multipliers, costs and new shares, and averages shares with step 1/n; loads
  are linear in shares, so this averages the loads exactly. It stops when segment loads change
  by less than 1 % (relative L1) or after 50 iterations. Costs, shares and loads are computed in
  Rust on the stored choice set; loads are summed in a fixed order, so runs are byte-identical.
- **Calibration.** The logit scale has no guidance value; it is fitted on the training
  stations' entry level only, and the held-out stations check it. A run without fares
  separates the fare effect from the crowding effect.

## Consequences

- A traveller cannot switch to an earlier or later vehicle of the same route except through
  the departure spread inside each bundle, nor to a journey outside the three alternatives.
- Overlapping alternatives (sharing most rides) are over-weighted by the logit (IIA); exact
  duplicates are merged, near-duplicates are not.
- Fixed costs are means over the departures each alternative serves, so the logit compares
  alternatives as a whole, not departure by departure.
- Soft capacity only: loads can still exceed crush; their share is reported.
