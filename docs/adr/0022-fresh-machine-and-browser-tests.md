# ADR 0022 — Fresh-machine setup, browser tests and the basemap fallback

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Phase 7 is done when the PRD §73 demonstration works from a browser on a fresh machine and an
end-to-end smoke test passes in CI. The app has four moving parts (API, web app, worker, queue)
and a scenario run takes minutes on Bengaluru, which CI cannot hold. Scenario results are cached
by a key that includes the engine's git commit (ADR 0009), and a container has no checkout. The
phase plan also suggested a self-hosted PMTiles basemap as a fallback for OpenFreeMap.

## Decision

- **Browser tests on Toyville.** `web/e2e` (Playwright) builds Toyville from the test fixtures with
  demand and assignment (`python -m tests.e2e_city`, about 10 s), starts the real API and the Vite
  app (blank basemap, no network), and walks the demo story: map, accessibility, a frequency
  change, save, simulate, results, change map, playback, model checks. The worker runs in burst
  mode inside the test once the simulation is queued, so no long-lived process is needed; the
  queue is Redis/Valkey database 15, emptied first. Locally the tests drive the installed Chrome,
  in CI Playwright's Chromium with a Valkey service. The test city lives in `.e2e/` at the
  repository root: under `web/`, Vite's file watcher kept Windows from renaming result folders.
- **One image, two services.** `docker compose --profile app up -d --build` runs `api` (which also
  serves the built web app) and `worker` from one image; `data/`, `cities/` and `scenarios/` are
  mounted, never baked in.
- **Engine commit recorded at build.** The image build runs the runner's own rule
  (`git_state` over `ENGINE_PATHS`) on the copied checkout and stores the commit and dirty flag;
  the entrypoint exports them and `engine_versions` uses them when there is no checkout. Without
  this every image would share one cache key and reuse results computed by older code.
- **One engine version per run.** The job's child process reads the engine version once and
  passes it to both the run and the comparison. Read twice, an edit to the source tree during a
  long run changed the key in between and the comparison could not find the result (this
  happened on Bengaluru while developing M9).
- **No self-hosted basemap.** The fallback is `VITE_BASEMAP=blank`, a plain background: every
  layer, number and label of Glacies works without tiles. A self-hosted vector basemap would also
  need its style, fonts and sprites served locally and a regional extract kept up to date, for a
  backdrop the analysis does not use. OpenFreeMap needs no key and has no request limits; if it
  goes away, the blank style is one setting.

## Consequences

- CI proves the full stack on Toyville, not Bengaluru timings or loads; Bengaluru figures in
  `docs/demo.md` come from runs on the development laptop.
- A fresh machine still needs the raw data archive (`data/raw/`); some sources are manual
  downloads (`data/README.md`).
- The container and a clean host checkout of the same commit compute the same cache key, so each
  reuses the other's results: the demo scenario run in the container (190 s on Bengaluru) was
  then reused by the host in 4 s.
- Same platform, same bytes; across platforms, the same numbers to rounding. The Linux image and
  Windows give an identical travel-time matrix (whole seconds), while floating-point outputs differ
  in the last bit (accessibility shares by at most 9e-19, loads by 9e-13 passengers), most likely
  because the platforms' maths libraries round functions such as `exp` differently (not traced). Sharing results between them is therefore safe; comparing
  their files byte for byte is not.
