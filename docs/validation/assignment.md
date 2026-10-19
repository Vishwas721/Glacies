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
