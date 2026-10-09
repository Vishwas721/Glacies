# Synthetic demand — Bengaluru (Phase 5)

Everything here is **Estimated** (demand) or **Simulated** (travel times, journeys, station
flows) unless labelled otherwise. Priors are Assumed and live in `cities/bengaluru/demand.toml`
with their citations. Numbers come from runs on 2026-10-09 on mains power:
`glacies build paths`, `glacies build demand`, `glacies build station-flows`,
`glacies demand calibrate`, `glacies demand sensitivity`.

## M1–M2: trip ends and the gravity model (β provisional)

Settings: home-based work, 08:00–10:00; trip rate 0.10 × transit share 0.45 (Assumed);
friction `exp(-0.05 × p50 minutes)`. **β = 0.05 was a placeholder**; M4 replaced it with
0.0321 (numbers in this section are from the 0.05 run). Zone pairs whose fastest journey is on
foot at half or more of the departures are not transit demand and are left out (ADR 0013).

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

## M4: β calibration

Run: `glacies demand calibrate` (~47 min on mains power: 20 Furness runs at tolerance 1e-4, then
the chosen β at 1e-6). Objective: RMSE of each training station's share of entries, 08:00–10:00,
averaged over 13 Tue–Thu dates in Aug–Sep 2025 (Observed, BMRCL). The Yellow line is excluded
(its service on those dates differs from the routing timetable); the 15 held-out stations were
fixed in `demand.toml` before the search and never evaluated by it (ADR 0014).

**Chosen β = 0.0321 per minute** (1/β = 31 min), now in `demand.toml`. At this β: 354,386
trips, mean 11.8 km (prior 11 km, accepted 8–14) and 74.4 min door to door; Furness converges
in 1,570 iterations.

| Set | Items | RMSE (share) | R² (share) | r | Mean GEH | GEH < 5 | Simulated / observed |
|---|---:|---:|---:|---:|---:|---:|---:|
| Training stations | 53 | 0.0168 | −0.54 | 0.50 | 27.2 | 13 % | 0.41 |
| **Held-out stations** | 15 | 0.0440 | **−1.34** | 0.37 | 25.9 | 20 % | 0.24 |
| Excluded (Yellow line) | 15 | 0.0821 | −7.06 | 0.55 | 15.9 | 33 % | 0.92 |
| Training station pairs | 2,762 | 0.0009 | −0.70 | 0.41 | 4.1 | 71 % | 0.40 |
| Held-out station pairs | 223 | 0.0090 | −0.98 | 0.47 | 5.3 | 61 % | 0.31 |

Station pairs use the two dates with pair data (2025-08-12, 08-13), by exit hour.

Training RMSE over the sweep: 0.01697 at β 0.005, 0.01682 everywhere from 0.027 to 0.037,
0.01694 at 0.052 (the old placeholder), 0.0236 at 0.2. **β is weakly identified**: the objective
is flat over 0.027–0.037 (mean trip 11.3–12.4 km) and changes by less than 1 % over 0.005–0.05.

**Discussion.** R² is negative on every set and at every β: the simulated split of entries
across stations is worse than giving each station the same share. The errors are structural,
not a matter of β:

- *Access by feeder bus, auto and two-wheeler is missing.* The model only lets people walk up
  to 800 m to a stop. The largest misses are terminals and stations with big catchments beyond
  walking distance: Baiyappanahalli 5,393 observed vs 345 simulated (held out), Kengeri 2,023
  vs 37 (held out), Nagasandra 3,607 vs 319, Kadugodi Tree Park 4,365 vs 903, Vijayanagar 5,034
  vs 731.
- *Interchange and rail transfers.* Nadaprabhu Kempegowda Station (Majestic) gets 278 simulated
  entries against 4,578 observed: riders arriving by suburban rail and long-distance bus are not
  in a home-based model.
- *One purpose, part of the city.* Only home-to-work trips from zones with transit access: 3.9
  million people with no stop within 800 m and 727,334 whose stops reach nothing produce no
  trips. Hence the level of 0.24–0.41.
- Where the model does have walk-in catchments it tends to over-predict (Dasarahalli 9.6 %
  observed vs 18.3 % simulated share, Banashankari 6.0 % vs 11.3 %).

The Yellow line's level ratio of 0.92 is not a good fit: its stations are excluded because the
routing timetable runs it differently from the ridership dates.

Busiest simulated entries at the calibrated β: Benniganahalli 4,263 (observed 7,364), Magadi
Road 4,181, Delta Electronics Bommasandra 3,199. Busiest exit: Indiranagar 8,408.

## M5: sensitivity

Run: `glacies demand sensitivity` (~2 h on mains power, one Furness run per β or proxy
variant at tolerance 1e-6). One assumption changes per row. The level rows scale every trip end
by the prior ranges (trip rate 0.08–0.14 × transit share 0.35–0.50) and leave shapes unchanged.
"Hub share" is the share of attracted trips in zones overlapping the hand-drawn hubs.

| Variant | Trips | Mean km | Mean min | Metro share | Entries | R² train | R² held-out | Level (train) | Hub share | Top 5 % zones |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline (β 0.0321) | 354,386 | 11.8 | 74.4 | 17.7 % | 62,574 | −0.54 | −1.34 | 0.41 | 2.9 % | 76.1 % |
| β × 0.5 | 354,386 | 13.6 | 80.7 | 20.5 % | 72,820 | −0.55 | −1.54 | 0.48 | 2.9 % | 76.1 % |
| β × 2 | 354,386 | 9.0 | 62.9 | 12.7 % | 45,108 | −0.61 | −1.07 | 0.31 | 2.9 % | 76.1 % |
| proxy previous-baseline | 354,386 | 11.4 | 74.2 | 16.0 % | 56,797 | −0.39 | −1.20 | 0.37 | 2.5 % | 69.0 % |
| proxy poi-led | 354,386 | 12.3 | 74.8 | 19.2 % | 67,879 | −0.71 | −1.63 | 0.46 | 3.2 % | 82.6 % |
| proxy pois-only | 352,245 | 13.1 | 75.8 | 21.2 % | 74,818 | −0.96 | −2.16 | 0.51 | 3.7 % | 92.3 % |
| proxy area-only | 354,386 | 11.0 | 74.9 | 13.5 % | 47,678 | −0.32 | −1.66 | 0.29 | 1.8 % | 58.0 % |
| proxy baseline-c75 | 354,386 | 11.8 | 74.3 | 17.6 % | 62,380 | −0.54 | −1.32 | 0.41 | 2.9 % | 75.7 % |
| trip rate × share low | 220,507 | 11.8 | 74.4 | 17.7 % | 38,935 | −0.54 | −1.34 | 0.26 | 2.9 % | 76.1 % |
| trip rate × share high | 551,267 | 11.8 | 74.4 | 17.7 % | 97,337 | −0.54 | −1.34 | 0.65 | 2.9 % | 76.1 % |

(pois-only has 352,245 trips because its proxy gives no attraction to some reachable zones.)

**Ranges to quote instead of single numbers:**

| Quantity | Range |
|---|---|
| AM-peak transit trips (Estimated) | 220,507–551,267 |
| Mean trip length | 9.0–13.6 km |
| Share of trips using the metro | 12.7–21.2 % |
| Simulated metro entries, 08:00–10:00 | 38,935–97,337 (observed at all 83 stations: 156,524 a day, mean of the 13 dates) |
| Held-out R² of station entry shares | −2.16 to −1.07 |

**Reading.** The employment proxy moves the station shape more than β does: area-only gives
the best training R² (−0.32) but a worse held-out one; β × 2 gives the best held-out R² (−1.07)
but a worse training one. No variant gets a positive R², which supports the M4 conclusion that
station access, not distribution, limits the fit. The level ratio stays at 0.26–0.65 even with
both priors at the top of their ranges.
