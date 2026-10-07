# Routing sanity check

City `bengaluru`, timetable of 2026-10-13, max 4 vehicles, 60 s minimum transfer, walking 1.2 m/s (access ≤ 800 m, transfers ≤ 400 m). Station entry (free when changing within a station): metro 240 s.

**13 of 20 pairs within ±20% or ±5 min** (target: 90 %). Simulated times are door to door from the departure time, including the wait for the first vehicle.

| # | From → To | Depart | Expected (Estimated) | Simulated fastest | Transfers | Fewest-transfer option | Within | Note |
|---:|---|---|---:|---:|---:|---:|:---:|---|
| 1 | Doddaballapur → Majestic | 11:35 | 150 min | 100 min | 0 | 100 min | ❌ |  |
| 2 | Yelhanka Old Town → Bellahalli Cross | 08:30 | 18 min | 19 min | 0 | 19 min | ✅ |  |
| 3 | NES Office → Hebbala | 11:50 | 26 min | 21 min | 0 | 21 min | ✅ |  |
| 4 | Majestic → Yeshwanthpur | 08:30 | 25 min | 21 min | 0 | 21 min | ✅ |  |
| 5 | Majestic → Shivajinagar | 09:00 | 12 min | 26 min | 1 | 27 min | ❌ |  |
| 6 | Majestic → Nelmangala | 09:30 | 90 min | 78 min | 1 | 80 min | ✅ |  |
| 7 | Indiranagar → MG Road | 08:30 | 15 min | 35 min | 1 | 66 min | ❌ |  |
| 8 | Banashankari → Jayanagar | 09:00 | 25 min | 15 min | 1 | 20 min | ❌ |  |
| 9 | Majestic → Electronic City | 08:30 | 73 min | 66 min | 1 | 69 min | ✅ |  |
| 10 | Majestic → Whitefield | 08:30 | 80 min | 67 min | 0 | 67 min | ✅ |  |
| 11 | Yeshwanthpur → Electronic City | 08:30 | 140 min | 74 min | 2 | 491 min | ❌ |  |
| 12 | Whitefield → Silk Board | 08:30 | 65 min | 75 min | 2 | 90 min | ✅ |  |
| 13 | Kengeri → Indiranagar | 08:30 | 95 min | 65 min | 1 | 65 min | ❌ |  |
| 14 | Whitefield → Yeshwanthpur | 08:30 | 105 min | 91 min | 1 | 91 min | ✅ |  |
| 15 | Banashankari → Whitefield | 08:30 | 100 min | 89 min | 1 | 146 min | ✅ |  |
| 16 | KR Puram → Majestic | 08:30 | 60 min | 45 min | 2 | 55 min | ❌ |  |
| 17 | Marathahalli → Majestic | 08:30 | 50 min | 60 min | 0 | 60 min | ✅ |  |
| 18 | HSR Layout → Majestic | 08:30 | 62 min | 55 min | 1 | 55 min | ✅ |  |
| 19 | Silk Board → Yeshwanthpur | 08:30 | 66 min | 62 min | 2 | 176 min | ✅ |  |
| 20 | Electronic City → Indiranagar | 08:30 | 80 min | 65 min | 1 | 67 min | ✅ |  |

Stops used: see `bengaluru-sanity-set.csv`. Pairs with a review note involve an ambiguous
place and should be confirmed before drawing conclusions from them.
