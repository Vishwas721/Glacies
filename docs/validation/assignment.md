# Transit assignment — Bengaluru (Phase 6)

## M1: all-or-nothing assignment (ADR 0017)

Every OD trip (work + education, 822,775, Estimated) leaves home 08:00–09:59 in proportion to
BMRCL's hourly entry shares (0.465 / 0.535), only at minutes whose departures reach the
destination within 120 min, and takes its fastest journey: the Phase 5 rule, now as loads on
every trip segment. Same walks and rides to metro stations as demand. Capacities and their
sources are in `cities/bengaluru/assignment.toml` (Assumed).

Run 2026-10-19 on mains power (`glacies build assignment`): **302 s, peak RAM 1.57 GiB**;
a rerun (235 s, 1.78 GiB) wrote byte-identical Parquet.

| Quantity | Value |
|---|---:|
| OD trips | 822,775 |
| on transit | 822,199 (99.9 %) |
| walking all the way is as fast (at 08:00–10:00) | 575 |
| not reached in the window | 0 |
| boardings | 2,038,054 |
| transfers per transit trip | 1.48 |
| passenger-hours in vehicles | 555,269 |
| segments leaving a stop 08:30–09:29 | 114,251 |
| ... above design capacity | 17,615 (15.4 %) |
| ... above crush capacity | 14,947 (13.1 %) |

Conservation checks passed (transit + walked + unreached = OD trips per pair; Σ boardings =
Σ alightings; nobody on board at a trip's end).

**Continuity with Phase 5.** Metro flows over the busiest links match the Phase 5 station-flow
estimate (which used 07:30–09:30 departures with equal weights):

| Link (all trips of the window) | M1 assignment | Phase 5 station flows | BMRCL, exit hours 8–9 |
|---|---:|---:|---:|
| Purple: Majestic → Central College | 59,306 | 57,247 | 37,926 |
| Green: Sampige Road → Majestic | 44,423 | 43,650 | 21,636 |
| Yellow: Hongasandra → Bommanahalli | 37,686 | 37,406 | 2,879 |

BMRCL columns are means of 12–13 Aug 2025; the Yellow Line then ran far fewer trains than the
2026 timetable, so its figures are not comparable.

**Peak hour (vehicles leaving 08:30–09:29), metro:**

| Line | Segments | Mean load | Max load | Max load factor | Above capacity | Above crush |
|---|---:|---:|---:|---:|---:|---:|
| Green | 584 | 830 | 2,586 | 1.64 | 15.1 % | 8.4 % |
| Purple | 754 | 772 | 2,706 | 1.72 | 10.7 % | 2.7 % |
| Yellow | 238 | 900 | 2,238 | 1.42 | 8.8 % | 2.1 % |

Majestic → Central College carries 1,024 per train on average in the peak hour (21 trains),
up to 2,663: above the 2,004 crush capacity.

**Buses.** 15.5 % of peak bus segments are above capacity (66) and 13.2 % above crush (77),
while the median loaded segment is at 0.18. The heaviest are single express and airport trips
carrying 1,100–2,200 people (VV-EXP 298MN 2,194, KIA-8A 1,537, route 22 1,684). This is the
all-or-nothing rule at work: every departure minute whose fastest journey is that trip piles
onto it, with no limit. These loads are not predictions; M3's crowding penalty and choice set
are meant to spread them. Missing routes in the bus feed (PRD Risk 1) would add to it.

**Transfers.** 1.48 per transit trip (2.48 vehicles) is high: the fastest journey uses extra
vehicles whenever they save a minute. A transfer penalty in M3's generalised cost addresses it.

**Metro boardings** are 442,373 (Purple 199,431, Green 153,340, Yellow 89,602) against
357,270 gate entries in Phase 5: boardings count line changes inside Majestic and RV Road
again (they are the two busiest, 50,835 and 35,890).

## M2: metrics (PRD §31) and metro gate entries against BMRCL

The router now returns, per OD pair, the minutes its transit trips spend in vehicles, waiting
(at the origin, at stops and while changing), walking and riding to a station, and every metro
*segment* as one fare-gate pass (entry and exit station; changes inside a station are not a new
entry, the Phase 5 rule). New tables: `routes.parquet` (boardings, passenger-km and -hours, peak
utilisation and load factor), `stations.parquet` (gate entries and exits, with the observed
entries and station set) and `station_pairs.parquet`. Distances are straight lines between
consecutive stops (Estimated).

Run 2026-10-19 on mains power: **122 s, peak RAM 1.88 GiB**, rerun byte-identical. Loads are
unchanged from M1.

**City summary** (per transit trip; Simulated, all-or-nothing on the fastest journey):

| Metric | Value |
|---|---:|
| travel time, door to door | 75.2 min |
| ... in vehicles | 42.1 min |
| ... waiting | 13.9 min |
| ... walking | 13.3 min |
| ... riding to a station | 5.8 min |
| transfers | 1.48 |
| trips starting with a ride to a station | 36.6 % |
| passenger-km (straight line) | 12,859,509 |
| crowding: peak passenger-km above design capacity | 59.8 % |
| peak passenger-km above crush capacity | 52.0 % |
| metro gate entries | 362,058 |

The crowding share is high because the heaviest segments carry most passenger-km: the metro
cores and the express and airport buses that collect every departure for which they are
fastest (VV-EXP 298MN averages 9.7 times its peak capacity over the hour). It is the baseline
that M3's crowding penalty should bring down, not a forecast.

**Metro gate entries against BMRCL** (shares within each set, scored like demand calibration;
simulated trips leave home 08:00–10:00, observed entries are tap-ins in hours 8–9):

| Set | Stations | R² (share) | r | Mean GEH | Simulated / observed |
|---|---:|---:|---:|---:|---:|
| Training | 53 | 0.10 | 0.52 | 22.8 | 2.07 |
| Held-out | 15 | 0.37 | 0.66 | 13.5 | 1.73 |
| Excluded (Yellow Line) | 15 | −1.23 | 0.23 | 13.4 | 7.70 |

These match the Phase 5 station flows (training level 2.05, held-out R² 0.39; 357,270 entries)
despite the shifted window and hourly weights, so the assignment and the path table agree. The
level, about twice the observed entries, is what M3 (fares, transfer penalty, crowding) has to
address.

**Routes with the most passenger-km:** Purple 1,773,690 (peak utilisation 0.48, max load factor
1.72), Green 1,308,267 (0.52, 1.64), Yellow 677,294 (0.58, 1.42); then buses VV-EXP 298MN
332,507, KIA-8 220,952 and VV-EXP TMK-1 181,886, all far above capacity for the reason above.

## M3: crowding loop (ADR 0018)

Each OD pair gets up to three alternatives, routed once: the fastest journey, the fastest on
buses only and the fastest with at most one transfer. Generalised cost: walk 2.0, wait 2.0,
transfer 5 min (DfT TAG M3.2 Table 1), riding to a station 1.0, fares over the value of time
(₹89/h), in-vehicle minutes times the TAG crowding multiplier. Logit between a pair's
alternatives, method of successive averages until segment loads change by under 1 %.

**Toy check** (`tests/test_assignment_msa.py`): 100 trips, a 10-minute metro with room for 60
and a 20-minute bus that never fills. Without crowding the metro would take 76.9; the loop
moves riders to the bus and lands within 0.5 of the equilibrium found by bisection, for logit
scales 0.12 and 0.5, conserving all 100 trips.

**Bengaluru** (2026-10-19, mains power): the choice set holds 3,860,968 alternatives for
1,782,019 pairs (2.17 per pair) and 134,632,599 rides; peak RAM 3.97 GiB. The loop converged in
10 iterations (gap 0.33, 0.10, 0.053, … 0.0097). The first run took 218 s; two later reruns
took 507 s and 1,046 s with the CPU mostly idle (the laptop slowed down; no cause found), and
wrote byte-identical Parquet.

| Run | Metro entries | Training level | Held-out level | Training R² | Held-out R² | Peak segments over capacity | Transfers |
|---|---:|---:|---:|---:|---:|---:|---:|
| All-or-nothing (M2) | 362,058 | 2.07 | 1.73 | 0.10 | 0.37 | 17,615 | 1.48 |
| Crowding loop, no fares | 325,474 | 1.86 | 1.58 | 0.10 | 0.37 | 19,412 | 1.28 |
| With fares, logit 0.06 | 227,596 | 1.31 | 1.03 | −0.07 | 0.36 | 22,657 | 1.36 |
| **With fares, logit 0.12 (baseline)** | **219,565** | **1.26** | **0.98** | −0.14 | 0.31 | 23,093 | 1.36 |
| With fares, logit 0.24 | 211,553 | 1.21 | 0.93 | −0.20 | 0.26 | 23,420 | 1.37 |
| Logit 0.12, curve not held at crush | 290,996 | 1.68 | 1.38 | 0.03 | 0.32 | 22,018 | 1.22 |

- **Fares do most of the work.** Crowding and route choice alone bring the training level from
  2.07 to 1.86 and transfers from 1.48 to 1.28; with fares the level falls to 1.26 and the
  held-out level to 0.98. The shape gets worse (training R² 0.10 → −0.14): fares move riders
  off the metro unevenly across stations.
- **The logit scale is not identified** by the entry level: a fourfold range moves it from 1.31
  to 1.21 and never reaches 1, while held-out R² falls. It stays at 0.12 (Hong Kong MTR,
  Mo et al. 2020) instead of being fitted, a change from the M3 plan.
- **The metro is no longer over capacity** in the peak hour (Purple max load factor 1.06,
  Green and Yellow 1.00; mean loads 491–584 a train), against 1.42–1.72 all-or-nothing.
- **Bus pile-ups remain.** Single trips still carry 1,200–1,700 people (KIA-8A 1,349 at 09:21,
  route 22 1,684). Two reasons: the TAG multiplier is held at crush (2.47), so a bus at 25 times
  its capacity costs no more than one just past crush; and some pairs have only one alternative.
  Letting the curve grow past crush (last row) moves riders back to the metro rather than
  spreading them over buses, and needs 27 iterations; it is a sensitivity option
  (`cap_at = "none"`), not the default. Hard capacity (fail-to-board) is the remedy the phase
  doc leaves for later.

**City summary, baseline** (per transit trip): 77.4 min door to door (46.1 in vehicles, 13.7
waiting, 14.1 walking, 3.5 riding to a station), 1.36 transfers, 22.7 % of trips start with a
ride to a station (36.6 % all-or-nothing: the auto fare now counts), crowding 59.0 % of peak
passenger-km (54.9 % above crush, almost all on buses).

## M5: assignment in scenarios (ADR 0019)

A scenario run now assigns the baseline OD onto the scenario network with the same crowding loop
(demand is fixed: the comparison shows re-routing, not new riders). Its cache key includes the
baseline demand and both settings files. `glacies scenario compare` adds PRD §31's assignment
rows and `route_deltas.parquet`.

**Doubling 500-D on the Outer Ring Road** (`bengaluru_orr_frequency_double`, 2026-10-20, mains
power): run 352 s (travel-time matrix 117 s, assignment about 230 s), peak RAM 3.88 GiB.

| Metric (per transit trip unless stated) | Baseline | Scenario | Change |
|---|---:|---:|---:|
| travel time | 77.40 min | 77.39 min | −0.01 |
| waiting | 13.70 min | 13.69 min | under 0.005 |
| transfers | 1.3633 | 1.3639 | +0.0006 |
| crowding, peak passenger-km above design capacity | 58.99 % | 58.91 % | −0.07 pp |
| peak segments above design capacity | 23,093 | 23,069 | −24 |
| metro gate entries | 219,565 | 219,494 | −71 |
| zones gaining access (45 min, p50) | | 19 | |

500-D gains 3,040 boardings (4,901 → 7,941), mostly from the parallel ORR services: 500-A −452,
V-500D −252, V-500A-KRP-BSK −148, V-500CK −137. City totals barely move, as the scenario
expected: 500-D already runs about every 5 minutes, so the extra trips mostly shift riders
between ORR routes. The accessibility side matches Phase 4 (19 zones up, none down).

The direction check first reported two values falling by 8.7e-19 and 1.7e-18: last-bit float
differences between the baseline accessibility (summed under polars 1.x) and the scenario's
(polars 2). The check now ignores changes under 1e-12.

## M6: validation report

`glacies assignment report` writes `reports/assignment/<scenario>/`: `convergence.png`,
`stations.png` (simulated against observed gate entries, by set), `segments_peak.geoparquet` and
`.png` (each route's stop-to-stop segments with the peak-hour passengers, highest and mean load
factor, for QGIS) and `report.md`. Bengaluru baseline: 59,786 peak segments, written in 4 s.

Peak-hour bus segments (59,622) by mean load factor: 55 % under 0.5 carrying 15 % of bus
passengers, 19 % at 0.5–1.0 (19 %), 9 % at 1.0–1.5 (14 %), and 16 % over 1.5 carrying 52 %.
Passenger-weighted, the mean bus load factor is 2.93: a minority of corridors take most riders, the
soft-capacity model lets them exceed what could board, and the 33-seat / 5.5 m² bus capacity is
Assumed. Metro segments: 132 of 164 under 0.5 mean load factor, none above 1.0.

**What the user checks** (phase doc hands-on): open `segments_peak.geoparquet` in QGIS and see
whether the heaviest corridors match ones known to be crowded (Majestic–Silk Board, ORR, Purple
Line core); compare `stations.png` with knowledge of busy stations.
