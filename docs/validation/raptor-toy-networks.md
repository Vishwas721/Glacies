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
