# The Glacies demonstration (PRD §73)

One story, start to finish, in the browser: the Bengaluru baseline, today's accessibility, a
scenario that changes frequencies, removes duplicated service and adds a corridor, a run of
routing, assignment and accessibility, and what changed where. About ten minutes to present; the
simulation itself takes 6-15 minutes on a laptop, so start it early or use a finished result.

Every number on screen carries a badge: **Observed** (from a dataset), **Estimated** (a model
input built from data, such as population or the employment proxy), **Simulated** (computed by
Glacies), **Assumed** (a parameter someone chose). Say so when you show the first one.

## Before you start

```bash
docker compose up -d redis            # the simulation queue (Valkey)
uv run uvicorn glacies.api.app:app    # API on :8000
uv run glacies worker                 # runs simulations
(cd web && pnpm dev)                  # http://localhost:5173
```

or, on a machine with only Docker and the built `data/`:
`docker compose --profile app up -d --build`, then http://localhost:8000 (the same demo run took
190 s there).

The baseline must be built (`uv run glacies build-city bengaluru --clean`, then the
travel-time matrix, accessibility, demand and assignment: see the README).

## 1. Load the Bengaluru baseline network

Open the app. The map shows every bus and metro stop-to-stop segment, wider where more vehicles
run in the 07:30-09:30 window (timetable: **Observed**). Lines are straight between stops: the
feeds have no shapes, which the API labels **Assumed**.

## 2. Show current accessibility

Zones: *Accessibility to estimated jobs*, within 45 min at p50. Explain the measure: the share of
the city's **estimated** jobs (a building and job-POI proxy, never a job count) reachable from each
zone by transit and walking. Switch to *Population* and *Estimated employment* to show where people
live and where the proxy puts jobs.

## 3. Create the scenario

*Open* → **East Bengaluru package** (`bengaluru_demo_east_corridor`, a repository scenario: it
runs as it is, and any edit becomes your own copy). It combines the three Phase 4 scenarios:

- **Modify frequencies**: 500-D on the Outer Ring Road runs twice as often (route 1066).
- **Remove overlapping service**: 304-K (routes 2255, 2256), which duplicates the Purple Line
  between Hope Farm and KR Pura.
- **Introduce a corridor**: a 10-minute feeder from Kundalahalli metro to the ORR tech parks,
  20 km/h (**Assumed**).

Show the route list (the changed routes at the top), the frequency menu and the added route. To
show building one live: search a route, untick it, *Save*; the builder checks the schema at once
and the server checks every route and stop id.

## 4. Run demand, routing and assignment

*Simulate*. If this scenario has run before with the same code and data, the result is reused
and the run finishes in seconds. Otherwise the status shows each stage (applying the changes, the travel-time matrix for the
affected origins, accessibility, assignment with crowding, the comparison) and can be cancelled.
Demand is the baseline AM-peak OD, assigned onto the changed network (ADR 0019): the comparison
shows route choice, waiting and crowding effects, not new riders.

## 5. Before vs after

*Show results* (or pick the result under *Results*). The panel lists baseline → scenario and the
change for travel time, waiting and transfers per transit trip, accessibility within 45 minutes,
crowding and metro entries, each with its badge. *All metrics* has the rest.

Figures from the run on 2026-10-23 (result `eda5f026…`, 300 s on mains power: 3,030 of 10,661
origins recomputed, zone walks rebuilt for the new code), all **Simulated**:

| | Baseline | Scenario | Change |
|---|---:|---:|---:|
| Trips in the timetable | 58,258 | 58,523 | +265 |
| Travel time per transit trip | 77.40 min | 77.39 min | −0.006 min |
| Waiting per transit trip | 13.698 min | 13.700 min | +0.002 min |
| Transfers per transit trip | 1.3634 | 1.3640 | +0.0007 |
| Estimated jobs within 45 min (p50, population-weighted) | 2.7399 % | 2.7409 % | +0.0010 pp |
| Peak passenger-km above design capacity | 58.99 % | 58.92 % | −0.07 pp |
| Metro gate entries | 219,565 | 219,506 | −60 |

City-wide the package barely moves the averages: three routes out of 4,371. The story is local,
which is what steps 6 and 7 show. Waiting rises a little because the 304-K riders wait longer for
other buses (removing 304-K alone: +0.006 min), which outweighs the shorter waits on 500-D.

## 6. Where did accessibility improve?

*Show: Change*. Blue zones gained, red lost, in the classes of `glacies scenario compare`;
unchanged zones are not drawn. The changed routes are drawn on top: removed dashed red, added wide
blue, modified orange. In the run, 22 zones gain at the headline (45 min, p50): 18 of them lie
closest to 500-D, 3 to the feeder. 15 lose: 9 lie closest to the removed 304-K, the rest nearer
500-D or the feeder, because a journey can lose a leg anywhere along it; changed zones are up to
6 km from a changed route.

## 7. What changed and why?

*Routes changed* lists each change with its trips and boardings before and after; *Where riders
moved* shows the routes whose boardings changed most. In the run: 500-D +2,946 boardings, the feeder
+2,783, 304-K −1,471, and the parallel V-500CK (−689) and V-500CA (−493) lose riders to 500-D
and the feeder. Then *Passenger loads*: peak-hour crowding,
and *Flow playback* in 15-minute frames from 08:00. Frames outside 08:30-09:30 are marked partial:
nobody in the model leaves home outside 08:00-10:00, so the network fills and drains.

Close with *How far to trust the loads*: metro entries against observed gate counts (training
and held-out stations) and the share of bus passengers on segments loaded past what could board.
Capacity is soft, so those corridors show where demand piles up, not real loads.
