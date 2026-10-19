# ADR 0017 — All-or-nothing assignment with expected flows and design/crush capacity

- **Status:** Accepted
- **Date:** 2026-10-19

## Context

Phase 6 puts the demand OD onto scheduled trips (PRD §26–28, ADR 0003). Its first milestone is
all-or-nothing on the fastest journey, which reproduces what the Phase 5 station flows assumed
(ADR 0013), now as loads on every trip segment. Three choices shape every later milestone: how
trips are spread over departure times, whether passengers are sampled, and what "capacity"
means. The phase handoff proposed seeded sampling, a 2,000-passenger metro train and a 70-
passenger bus; checking the sources showed the train figure is the crush capacity at 8 standees
per m² (BMRCL Phase-3 DPR, p. xviii), not the design capacity, and no source gives 70 per bus.

## Decision

- **Window and profile.** Trips leave home 08:00–09:59, the demand definition and the BMRCL
  tap-in hours used for calibration, one departure per minute. Each hour's share comes from
  BMRCL entries by tap-in hour (0.465 / 0.535 in September 2025, Estimated), spread evenly within
  the hour. Crowding is reported for vehicles leaving a stop 08:30–09:29: earlier and later
  vehicles miss riders who left outside the window.
- **Expected flows, not samples.** An OD pair's trips are split over the departures that reach
  the destination within the time limit in proportion to the profile, and each departure takes
  its fastest journey (`crates/raptor/src/choice.rs`, shared with the matrix and the path
  table). OD pairs carry 0.30 trips on average, so sampled passengers would mostly be noise;
  expected values keep every total exact and runs byte-identical without a seed.
- **Same access as demand.** Assignment uses demand's walks and board-only rides to stations
  (ADR 0015), so trips only take journeys the demand model costed.
- **Loads on segments.** The router returns rides as `(trip, board position, alight position,
  passengers)`; loads per segment are the running sum of boardings minus alightings per trip.
  Conservation is checked on every run: transit + walked + unreached = OD trips, Σ boardings =
  Σ alightings, nobody left on board at a trip's end.
- **Capacity.** Vehicles are seats plus standing area (`assignment.toml`); capacity is at the
  design standing density (6/m²: BMRCL planning standard, AIS-052 bus body code) and crush
  capacity at 8/m². Standees are whole people. Load factor = load / capacity; crush factor =
  load / crush capacity. The bus feed does not say which vehicle runs a trip, so buses get one
  default with overrides by route prefix.

## Consequences

- M1 measures loads only; nothing reacts to crowding or fares until M3 (generalised cost with
  fares and a crowding multiplier by standee density, TAG M3.2, over a fixed choice set).
- Loads are as good as the bus feed: missing routes push riders onto others (PRD Risk 1).
- The window shifts from the 07:30–09:30 departures of the path table, so pairs reached by
  transit there can be walked or unreached here; both are counted, not dropped.
