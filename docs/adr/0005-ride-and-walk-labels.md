# ADR 0005 — Separate ride and walk arrival labels in RAPTOR

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Glacies applies a minimum transfer time (60 s, Assumed) between alighting and boarding another
vehicle, but not after walking. Standard RAPTOR keeps one earliest-arrival label per stop and
round. With an asymmetric transfer rule that loses journeys: a stop reached by vehicle at 08:10
(ready to board at 08:11) and on foot at 08:10:30 (ready at 08:10:30) keeps only 08:10, so a
departure at 08:10:45 looks missed.

## Decision

- Keep two labels per stop and round: `ride` (alighted from a vehicle) and `walk` (access walk
  or footpath). Boarding uses `min(walk, ride + min_transfer_time)`.
- Relax footpaths only from `ride` labels: a journey never has two walking legs in a row
  (footpaths are shortest walks, so chaining them would only add detours).
- Prune each label against its own earlier value; target pruning uses the best destination
  arrival.

## Consequences

- Exact under the transfer rule: verified against an independent Connection Scan oracle on
  3,000 random networks. A planted single-label variant of the router fails that test, so
  the test can detect this class of bug.
- Twice the label memory per round (two `u32` arrays), negligible next to the timetable.
- Journey reconstruction follows the label kind recorded at boarding (`boarded_via`).
