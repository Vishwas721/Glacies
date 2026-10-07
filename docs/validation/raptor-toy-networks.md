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

## Toy 4 — boarding time (station access)

```
A ──T1/T2──→ C        boarding at A takes 4 min (240 s)
```

| Trip | A | C |
|---|---|---|
| T1 | 08:02 | 08:12 |
| T2 | 08:06 | 08:16 |

Query A → C departing 08:00: without boarding time **arrive 08:12** (T1). With 240 s the
passenger is ready to board at 08:04, misses T1 and **arrives 08:16** (T2).
Boarding time is added to the minimum transfer time after a ride (Toy 2 with 240 s at B: ready
08:10 + 60 s + 240 s = 08:15, T2 still caught; with 241 s it is missed). Staying seated or
alighting at a stop with a boarding time costs nothing.
