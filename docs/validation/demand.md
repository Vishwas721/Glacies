# Synthetic demand — Bengaluru (Phase 5)

Everything here is **Estimated** (demand) or **Simulated** (travel times, journeys, station
flows) unless labelled otherwise. Priors are Assumed and live in `cities/bengaluru/demand.toml`
with their citations. Numbers come from runs on 2026-10-09 on mains power:
`glacies build paths`, `glacies build demand`, `glacies build station-flows`.

## M1–M2: trip ends and the gravity model (β provisional)

Settings: home-based work, 08:00–10:00; trip rate 0.10 × transit share 0.45 (Assumed);
friction `exp(-0.05 × p50 minutes)`. **β = 0.05 is a placeholder** until the M4 calibration
replaces it. Zone pairs whose fastest journey is on foot at half or more of the departures are
not transit demand and are left out (ADR 0013).

| Quantity | Value |
|---|---|
| Zones with a stop within 800 m walk | 3,465 of 10,661 (68.7 % of population) |
| Origin / destination zones | 2,704 / 2,706 |
| People left out: no stop / stop that reaches nothing beyond walking distance | 3,910,957 / 727,334 |
| Zone pairs left out as walking pairs | 11,352 of 1,515,315 |
| Trips (ΣO = ΣD) | 354,386 (220,507–551,267 with both priors at their range ends) |
| Attraction moved to make the targets attainable (ADR 0012) | 1,440 trips (0.4 %), 45 blocks |
| Pairs with trips | 1,487,715 |
| Furness | converged in 1,561 iterations, row error 1.0e-6, column error 4e-15 |
| Mean door-to-door time (p50, Simulated) | 67.6 min |
| Mean distance (straight line 8.8 km × 1.15 detour) | 10.1 km — within the accepted 8–14 km, below the 11 km prior |
| Rerun | byte-identical Parquet |

Trips by door-to-door time: ≤15 min 0.6 %, 15–30 6.9 %, 30–45 15.2 %, 45–60 19.4 %,
60–90 34.9 %, 90–120 23.0 %.

**What changed during M3.** The first M2 run (before walking pairs were excluded) had 386,504
trips, 20 % of which turned out to be fastest on foot, a mean of 8.8 km, and 7,373 trips of
attraction moved. 760 zones have a stop within 800 m but reach nothing beyond walking distance
at the median (their stops have little or no service in the window); they no longer produce
transit trips.

**Hubs (first run).** The 28 zones overlapping the 8 hand-drawn employment hubs received 2.7 %
of trips while holding 1.4 % of the population; RMZ Ecoworld received none (no zone overlapping
it has a stop within the 800 m walk).

## M3: simulated metro station flows

All-or-nothing on the fastest journey: each OD pair's trips are spread evenly over the 120
departures (07:30–09:29) that reach it; a metro segment (rides joined only by changes inside one
station) is one entry and one exit.

| Quantity | Value |
|---|---|
| Path table | 1,276,269 OD-to-station-pair rows, built in ~1 min 40 s (paths) |
| Trips using the metro | 52,022 (14.7 %) |
| Station entries | 52,028 (a few journeys enter twice) |
| Trips still fastest on foot (at under half their departures) | 1,000 (0.3 %) |
| Station flows from an OD matrix | 2.6 s (a join; reused for every β in M4) |
| Rerun | byte-identical Parquet |

Busiest simulated entries: Magadi Road 3,590, Benniganahalli 3,547, Delta Electronics
Bommasandra 2,540, Madavara 1,685, Dasarahalli 1,502. Busiest exits: Indiranagar 7,922,
Dr. B. R. Ambedkar Station (Vidhana Soudha) 2,064. Busiest station pair: Benniganahalli →
Indiranagar, 1,053 trips.

**Known limits.** Only home-to-work trips from zones with a stop within 800 m walk are
modelled; people who reach the metro by auto, two-wheeler or a long walk are not. So simulated
entries are well below observed ones, and calibration (M4) fits the *shape* (each station's
share of entries), not the level. Interchanges and terminals that draw riders from rail, long-
distance buses or feeders (Majestic, Baiyappanahalli) are expected to be under-predicted.
