# ADR 0007 — Scenario files are versioned diffs keyed by GTFS ids

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

Phase 4 needs a way to describe network changes (PRD §29–31) that planners can write by hand,
review in a pull request, and that the engine can apply deterministically. Two design pressures
pull in different directions: canonical tables use dense `*_idx` indices that change on every
rebuild, while planners know routes and stops by their GTFS ids. Bengaluru's timetables are also
irregular (500-D runs every 5 min at peak with gaps of up to 140 min off-peak), so "change the
headway" has more than one reasonable meaning.

## Decision

- A scenario is a JSON file `scenarios/<city>/<scenario_id>.json` with `schema_version`, a
  `base_network` (only `"baseline"` in v1) and an ordered list of mutations. It never contains
  copied network data. `title`, `description` and `expected_change` are documentation; the
  engine ignores them.
- Mutations are a Pydantic union keyed on `type`: `remove_route`, `modify_headway`,
  `add_route`. Unknown fields are rejected, so a typo cannot be silently ignored.
- References use GTFS ids (`source_route_id`, `source_stop_id`). An optional `feed` (dataset name)
  disambiguates ids present in more than one feed; `resolve` reports every unknown, ambiguous or
  conflicting reference in one error. Mutations may reference only baseline routes, not routes
  added in the same scenario.
- `modify_headway` takes exactly one of:
  - `headway_factor` (**scale**): multiply the gaps between departures, so an irregular timetable
    keeps its shape; `0.5` doubles the frequency.
  - `headway_secs` (**regularise**): replace the trips with evenly spaced departures.
  Either can be limited to a `window`; outside it the timetable is unchanged.
- `add_route` requires an explicit `speed_kmh` and `headway_secs` (Assumed). The return
  direction is `return_stops`, or the outbound stops reversed unless `one_way`.
- `schemas/scenario.schema.json` is generated from the models (`glacies scenario schema`), and a
  test fails when it is stale. Files reference it with `$schema` for editor validation.

## Consequences

- Scenarios stay small and comparable, and survive network rebuilds as long as the GTFS ids
  survive. A new feed snapshot that renames ids makes `glacies scenario check` fail loudly
  rather than apply a scenario to the wrong route.
- A `route_id` is one GTFS route, not a route number: BMTC splits 500-D across 22 route ids.
  Removing a whole line means listing its ids; a route-number selector can be added later.
- Any change to the file format bumps `schema_version`; the loader rejects versions it does not
  know instead of guessing.
