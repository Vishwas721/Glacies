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

http://localhost:5173 opens the landing page (ADR 0024): the simulated morning rush moving over
the city, and two ways in. For a general audience, start with **Easy** (below, at the end); this
walkthrough uses **Pro**, http://localhost:5173/pro. The sun or moon button switches between
the light and dark themes.

The Pro screen (ADR 0023): a rail with four modes (Explore, Design, Compare, Data), the mode's panel
on the left, the map, a dock under it for runs and flow playback, and an inspector on the right
for what is selected and for the comparison. A label on the map always says which network it
shows.

## 1. Load the Bengaluru baseline network

Open the app (Explore). The map shows every bus and metro stop-to-stop segment, wider where more
vehicles run in the 07:30-09:30 window (timetable: **Observed**): buses slate, metro pale. Lines
are straight between stops: the feeds have no shapes, which the API labels **Assumed**. The
masthead gives the network's size, and the inspector, with nothing selected, says what the map
shows.

## 2. Show current accessibility

Zones: *Accessibility to estimated jobs*, within 45 min at p50. Explain the measure: the share of
the city's **estimated** jobs (a building and job-POI proxy, never a job count) reachable from each
zone by transit and walking. Switch to *Population* and *Estimated employment* to show where people
live and where the proxy puts jobs. Click a zone: the inspector lists its residents, its share of
estimated employment and what it reaches. *Relief* (map controls) raises the zones by the same
value on a tilted map. *Data* lists every source with its licence and what the four labels mean.

## 3. Create the scenario

*Design* → *Open* → **East Bengaluru package** (`bengaluru_demo_east_corridor`, a repository
scenario: it runs as it is, and any edit becomes your own copy). The map draws the draft before
anything runs: removed routes dashed red, routes that run more or less often amber, added routes
ice. It combines the three Phase 4 scenarios:

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
and the run finishes in seconds. Otherwise *Runs* in the dock shows each stage as a track
(applying the changes, the travel-time matrix for the affected origins, accessibility, assignment
with crowding, the comparison) with the worker's own chunk counts, and the run can be cancelled.
The same list shows every earlier run, and Simulate stays off while the scenario is queued or
running.
Demand is the baseline AM-peak OD, assigned onto the changed network (ADR 0019): the comparison
shows route choice, waiting and crowding effects, not new riders.

## 5. Before vs after

*Show results* in *Runs* (or *Compare* → *Results*). The impact ledger in the inspector lists
baseline → scenario and the change for travel time, waiting and transfers per transit trip,
accessibility within 45 minutes, crowding and metro entries, each with its badge, whether the
change is better or worse (metro entries are not judged either way) and what the metric measures.
*All metrics* has the rest.

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

*Show* → *Change*, then *Fit the changed routes* (map controls). Blue zones gained, red lost, in
the classes of `glacies scenario compare`; unchanged zones are not drawn. The changed routes are
drawn on top: removed dashed red, added wide ice, modified amber. *Lens* puts baseline and
scenario accessibility side by side on one colour scale; drag the divider across a zone. In the run, 22 zones gain at the headline (45 min, p50): 18 of them lie
closest to 500-D, 3 to the feeder. 15 lose: 9 lie closest to the removed 304-K, the rest nearer
500-D or the feeder, because a journey can lose a leg anywhere along it; changed zones are up to
6 km from a changed route.

## 7. What changed and why?

*Routes changed* lists each change with its trips and boardings before and after; *Where riders
moved* shows the routes whose boardings changed most. In the run: 500-D +2,946 boardings, the feeder
+2,783, 304-K −1,471, and the parallel V-500CK (−689) and V-500CA (−493) lose riders to 500-D
and the feeder. Then *Passenger loads*: peak-hour crowding,
and *Flow playback* in the dock in 15-minute frames from 08:00. Frames outside 08:30-09:30 are marked partial:
nobody in the model leaves home outside 08:00-10:00, so the network fills and drains.

Close with *How far to trust the loads* in the inspector: metro entries against observed gate counts (training
and held-out stations) and the share of bus passengers on segments loaded past what could board.
Capacity is soft, so those corridors show where demand piles up, not real loads.

## The same story in the Easy view

For an audience that has never seen a transport model (about three minutes), from the landing
page choose **Easy**:

1. *Where does your morning start?* Type a stop or metro station, or tap the map. The map shows
   only the areas reached within 45 minutes, in three bands of door-to-door time, and the panel
   gives how many areas that is and their share of estimated jobs and residents (**Simulated**).
2. *What would you like to test?* Pick a question already answered, e.g. the East Bengaluru
   package, or change one bus route and run the model.
3. *The answer.* For your place: areas that come within reach (blue) or drop out (red). For the
   city: how many areas reach more or fewer jobs, waiting and journey times before and after,
   crowding, where riders moved, and how far to trust it. The address bar now holds the place
   and the question: copy it to share the answer.
