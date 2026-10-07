# RAPTOR toy networks

Hand-computed expectations from the Phase 2 handoff (2026-10-06). These are the specification for
the router's first tests: the Rust tests encode exactly these timetables and answers. Change them
only if this file changes too.

All times are on one service day; arrival equals departure at every stop (no dwell).

## Toy 1 — direct trip

```
A ──T1──→ B ──T1──→ C
```

| Trip | A | B | C |
|---|---|---|---|
| T1 | 08:00 | 08:10 | 08:20 |

Query A → C departing 08:00: **arrive 08:20 · 20 min · 0 transfers**.

## Toy 2 — one transfer

```
A ──T1──→ B ──T2──→ C
```

| Trip | A | B | C |
|---|---|---|---|
| T1 | 08:00 | 08:10 | |
| T2 | | 08:15 | 08:25 |

Query A → C departing 08:00: **arrive 08:25 · 25 min · 5 min waiting at B · 1 transfer**.
(The 5 min wait exceeds the 60 s minimum transfer time.)

## Toy 3 — diamond

```
      ┌──Fast──→ B ──Fast──┐
A ────┤                     ├──→ D
      └──Slow──→ C ──Slow──┘
```

| Trip | A | B | C | D |
|---|---|---|---|---|
| Fast | 08:00 | 08:05 | | 08:15 |
| Slow | 08:00 | | 08:10 | 08:30 |

Query A → D departing 08:00: **arrive 08:15 · 15 min · 0 transfers · via B (Fast)**.

## Toy 4 — station entry time

```
A ──T1/T2──→ C        entering station A on foot takes 4 min (240 s)
```

| Trip | A | C |
|---|---|---|
| T1 | 08:02 | 08:12 |
| T2 | 08:06 | 08:16 |

Query A → C departing 08:00: without entry time **arrive 08:12** (T1). With 240 s the
passenger is on the platform at 08:04, misses T1 and **arrives 08:16** (T2).

The entry time is paid when walking onto a platform from the origin or from outside its
station: T1 A 08:00 → B 08:10, walk B → X (120 s), T2 X 08:15 → C 08:25. With 180 s entry at
X the passenger is on the platform at 08:15 and catches T2; with 181 s it is missed. If B and X
are platforms of the same station, the change is free (on X's platform at 08:12). Alighting,
or boarding again at the stop just alighted at, never costs the entry time.

## Toy 5 — zone travel-time percentiles over a window

```
A ──T1/T2──→ B ──T1/T2──→ C       origin: 1 min walk to A
                 zone 1 ← 1 min from B (or 25 min on foot from the origin)
                            zone 0 ← 2 min from C
```

| Trip | A | B | C |
|---|---|---|---|
| T1 | 08:00 | 08:10 | 08:20 |
| T2 | 08:30 | 08:40 | 08:50 |

Departures 07:58, 07:59, 08:00, 08:01. The first two reach A by 08:00 and catch T1; the last
two miss it and take T2.

- Zone 0: 24, 23, 52, 51 min → sorted 23, 24, 51, 52 → **p25 23, p50 24, p75 51** (nearest
  rank: the smallest value with at least p % of the departures at or below it).
- Zone 1: by bus 13, 12, 41, 40 min, on foot 25 → 13, 12, 25, 25 → **p25 12, p50 13, p75 25**.
- With a 30-minute limit zone 0's p75 is "not reached"; with 20 minutes zone 0 is dropped.
