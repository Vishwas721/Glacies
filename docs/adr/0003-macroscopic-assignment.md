# ADR 0003 — Macroscopic/mesoscopic transit assignment, not microscopic simulation

- **Status:** Accepted
- **Date:** 2026-10-03

## Context

The original concept included animated vehicle simulation. Microscopic traffic simulation (car
physics, signals, lane changes) needs calibration data that does not exist openly for Bengaluru,
large compute, and many person-months of work. The questions Glacies answers (waiting, travel time,
crowding, accessibility under network changes) are answered by schedule-based assignment.

## Decision

- Model passengers as **aggregate OD flows** assigned to **scheduled transit trips** found by RAPTOR.
- Represent crowding with **load ÷ capacity per trip segment** and iterative penalties/rerouting.
- Vehicles run exactly to the GTFS schedule (or scenario-modified schedule). Road congestion affects
  buses only through the schedule.
- "Playback" in the UI animates aggregated flows per time slice, not individual agents.

## Consequences

- City-scale runs fit in about 24 GB RAM on a laptop.
- Bus bunching, signal priority, and congestion feedback cannot be studied. This is documented as a
  limitation in every results view.
- Revisiting this needs a new ADR, and stays out of scope until the deterministic pipeline is
  validated (PRD §70).
