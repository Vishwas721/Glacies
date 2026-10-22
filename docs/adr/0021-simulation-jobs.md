# ADR 0021 — Simulations run as child processes of one RQ worker, results stay in the cache

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

A scenario run (apply, travel-time matrix, accessibility, assignment, comparison) takes minutes
on Bengaluru (349 s and 753 s for the same run on the development laptop), so the API queues it
(PRD §45, §47). The phase plan suggested RQ on Redis. RQ supports Unix only; on Windows, where
Glacies is developed, its documentation says to use `SimpleWorker`, which runs jobs inside the
worker process, sends no heartbeats while a job runs and cannot kill a running job; its default
timeout uses `SIGALRM`, which Windows lacks. A run spends most of its time inside Rust, where no
Python exception or signal reaches it. Redis itself is RSALv2/SSPL from 7.4 (redis.io licences
page), while the PRD asks for free and open-source software.

## Decision

- **One RQ worker** (`glacies worker`), `SimpleWorker` with RQ's timer-based timeout, on every
  OS so CI tests what Windows runs. One run at a time: a run uses every core and gigabytes of
  memory.
- **A child process per run.** The job starts `python -m glacies.jobs.child <city> <scenario>`,
  which calls the scenario runner and then writes the comparison with the baseline into the
  result folder (`results/<key>/comparison/`). The child prints its stages and chunk counts as
  JSON lines; the job copies them into the simulation record. Cancelling or the timeout
  (`GLACIES_SIMULATION_TIMEOUT_S`, 45 min, Assumed) terminates the child; the runner's staging
  folder is cleared by the next run.
- **Our own record in Redis** (`glacies:sim:<id>`): status (queued, running, completed, failed,
  cancelled), stage, chunks done, result key, error (the end of the child's log). RQ's own job
  data expires; ours does not. A queued job is cancelled by taking it off the queue, a running
  one by a flag the job checks every half second.
- **Snapshots.** Queuing copies the scenario to `data/simulations/<id>/`, so editing it later
  does not change a queued or running simulation, and the child's log sits next to it.
- **Results are the scenario cache.** A completed simulation points at `results/<key>`; the
  same result is readable as `/api/cities/{city}/results/<key>/…`, the baseline as
  `…/results/baseline/…`. Crowding is per directed stop pair over the report hour (08:30–09:29),
  flows the same pairs in 15-minute frames from 08:00 until the last loaded vehicle, frames
  outside the report hour marked partial (nobody leaves home outside 08:00–09:59, so the network
  fills and drains). Values are rounded (0.01 passenger, 0.001 of capacity) for transport.
- **Valkey** (BSD-3, the Redis protocol) replaces the `redis:7-alpine` image in Compose.

## Consequences

- The API answers everything except simulations without Redis; simulation endpoints return 503
  with the command to start it.
- Two identical simulations reuse the cached result; the second finishes in seconds.
- Results are as durable as the cache: `build-city --clean` deletes them, and the simulation
  records then point at missing folders (404).
