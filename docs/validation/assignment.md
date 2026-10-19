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
