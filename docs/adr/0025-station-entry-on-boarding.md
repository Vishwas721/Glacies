# ADR 0025 — Station entry is paid to board, and comes from the baseline

- **Status:** Accepted
- **Date:** 2026-10-29
- **Amends:** the station entry rule of 2026-10-07 (`docs/validation/routing-analysis.md`)

## Context

`[routing] station_entry_s` (metro 240 s, Assumed) stands for a metro station's gates, security
and stairs. The router added it whenever a walk reached a platform from the origin or from
outside the station, and `station_entries` set it from the modes *serving* each stop on the
network being routed.

Closing the Purple Line (scenario `purple-line-closed`) failed the comparison's direction
check: removing trips sped up 687 zone pairs, by 17 s in the median and 113 s at most. Replaying
one pair (zone 3006 → 2995) at each of the 120 departures found two that changed. On the
baseline, a bus to Indian Express and a second bus arrived at 09:51. With the line closed, the
same first bus, then a walk to the Cubbon Park platform and a walk on to the destination,
arrived at 09:50. The closed line's platforms had no service, so they lost their entry time and
the walk through them became cheaper. Both halves were wrong: nobody pays a metro's security to
walk past a station, and a station does not lose its gates when its trains stop.

## Decision

- **Entry is paid to board.** Each stop keeps a third label per round, the arrival on foot
  without entry (`foot`), beside the ride arrival and the ready-to-board walk arrival (`walk`,
  entry included). Journeys end, and earliest arrivals and travel times are taken, from `ride`
  and `foot`; boarding still reads `walk`. The labels differ by a fixed time per walking edge,
  so the search stays exact; walking between platforms of one station stays free.
- **Entry times come from the baseline.** `load_router` takes station entries from the city's
  baseline `transit/` even when routing a scenario network. Entry is a property of the place.
  Scenarios do not change stops, so every stop keeps its baseline station and seconds.

## Consequences

- Removing trips can no longer make an arrival earlier (a property test on 1,000 random
  networks, single and range searches), so a removal-only scenario's direction check holds by
  construction rather than by luck.
- Travel times to zones whose nearest stops are metro platforms can fall slightly on the
  baseline itself (a walk past a platform no longer pays 240 s). Every result built before
  this change is out of date: the travel-time matrix, accessibility, demand inputs, assignment
  and all scenario runs are rebuilt.
- A scenario that adds a metro route over bus stops gives those stops no entry time; boarding
  that route there is free. No current scenario does this; if one does, the scenario format
  would need to say where its stations are.
