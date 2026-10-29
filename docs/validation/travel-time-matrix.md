# Travel-time matrix — Bengaluru baseline (2026-10-07 run)

Output of `uv run glacies build tt-matrix` (copied from
`data/processed/bengaluru/tt_matrix/baseline/BUILD_REPORT.md`), followed by checks. Times are
**Simulated**; every parameter is **Assumed**.

Builder 0.1.0 · 10,661 zones · 2,087,632 origin-destination rows in 42 parts

## Method (all parameters Assumed)

- Departures every 60 s from 07:30 to before 09:30 (120 departures).
- Percentiles p25, p50, p75 of the door-to-door time over the departures, nearest rank; a departure that does not reach the zone counts as infinitely long.
- Pairs whose p25 exceeds 120 min are not stored; higher percentiles above it are null.
- Zone points: 136 centre, 10,525 population (population-weighted where people live, else the cell centre).
- Walks at 1.2 m/s: to and from stops ≤ 800 m, between stops ≤ 400 m, zone to zone without transit ≤ 2000 m; a zone reaches itself in 0 s.
- Router: ≤ 4 vehicles, 60 s minimum transfer, station entry metro 240 s.

## Coverage

- Zones with a stop within 800 m walk: 3,465 of 10,661, holding 68.8% of the population (Estimated). The others reach only zones within walking distance.
- Mean destination zones reached within 60 min at the median: 21.7.

## Cut-off zones (checked 2026-10-29)

Each zone joins the network at one point: population-weighted, else the cell centre. Where that
point sits behind something the walk network cannot cross (a railway, a lake, a gated layout,
or a gap in OpenStreetMap), the whole zone reaches no stop, even with stops close by.
`uv run python scripts/cut_off_zones.py` lists these zones. Of the 7,196 zones with no stop
within the 800 m walk (3,910,957 residents, Estimated), **143 have a stop within 400 m in a
straight line (272,887 residents)**. Distances below are along the walk network (Simulated).

- Most are just over the limit, not walled off: the walk to the nearest stop is 1,013 m in the
  median. 66 zones (135,993 residents) are within 1,000 m and 98 (207,211) within 1,200 m.
- Some are real detours. The Whitefield (Kadugodi) zone `886189218dfffff` (5,651 residents) is
  229 m from the Kadugodi Bridge stop and the Whitefield metro station, but its point needs
  1,633 m on foot to reach any stop. One zone reaches no stop within 5 km.
- This is a limit of one point per zone, not of the router: these residents get no transit in
  accessibility, demand or assignment. Several points per zone would fix it, at the cost of
  rebuilding every result; it is left for Phase 8.

The script writes `data/processed/<city>/reports/cut_off_zones.geoparquet` (hexagons) and
`cut_off_zones_links.geoparquet` (a line from each zone's point to its nearest stop) for QGIS,
plus `cut_off_zones.csv`. Checking them against imagery tells real barriers from map gaps.

## Run

- 371 s on the development machine (24 GB RAM), of which about 183 s is computing the walks
  for all zone points; peak memory 1,089 MB. Phase target: < 30 min and < 8 GB.
- 2,087,632 rows, 11 MB of Parquet.

## Checks

- Toyville: every origin-destination row equals an independent Python recomputation (per
  departure arrivals + egress walks + nearest rank), and rebuilds are byte-identical.
- Best-connected origin: the Majestic zone reaches 424 zones within 60 min and 1,927 within
  120 min (median departure).
- Majestic → Whitefield zone: p25 81, p50 83, p75 86 min, against 80 min in the sanity set
  (Estimated).
- The city-wide mean (21.7 zones within 60 min) is low because only 3,465 of 10,661 zones
  (68.8 % of the population) have a stop within an 800 m walk. The other zones reach, and are
  reached from, only zones within walking distance. Accessibility results will therefore be
  driven by the 800 m access limit; see `routing-analysis.md` for that decision.
