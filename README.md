# Glacies

[![CI](https://github.com/Vishwas721/Glacies/actions/workflows/ci.yml/badge.svg)](https://github.com/Vishwas721/Glacies/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**An urban public-transit digital twin and scenario simulation platform.** Starting city: Bengaluru.

Glacies builds a computational model of a city's transit network from open data, generates
synthetic passenger demand, assigns it to scheduled services, and lets you ask:
*"What would happen if we changed the network?"* It answers by comparing travel time, waiting,
transfers, crowding and accessibility against the baseline.

```
GTFS + OSM + Population + Employment proxy
                 ↓
          Canonical network
                 ↓
            Rust RAPTOR
                 ↓
        Synthetic OD demand
                 ↓
       Passenger assignment  →  capacity / crowding
                 ↓
          Scenario engine
                 ↓
     Accessibility analytics  →  visualisation
```

> **Status:** Phase 0 (foundation). No simulation results exist yet. See the
> [phase plan](docs/phases/README.md).

## Principles

- **Zero cost, open data, open source**, and it runs on a laptop (~24 GB RAM).
- **City-agnostic engine.** Cities are data under `cities/<city>/`, not code.
- **Reproducible.** Same data + scenario + config + seed ⇒ identical results.
- **Transparent.** Every number is labelled **Observed**, **Estimated**, **Simulated** or **Assumed**.
- **Macroscopic, not microscopic.** Schedule-based assignment, no vehicle physics
  ([ADR 0003](docs/adr/0003-macroscopic-assignment.md)).

## Repository layout

| Path | Contents |
|---|---|
| `src/glacies/` | Python: ingestion, validation, canonical model, demand, assignment, scenarios, analytics, FastAPI |
| `crates/raptor/` | Rust RAPTOR routing core |
| `web/` | React + TypeScript + Vite frontend |
| `cities/bengaluru/` | City configuration and data-source registry |
| `data/` | Local datasets (gitignored): `raw/` → `interim/` → `processed/` |
| `docs/phases/` | Phase-by-phase plan with research lists and agent kickoff prompts |
| `docs/adr/` | Architecture decision records |

## Quickstart

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), Rust (rustup), Node 22 + pnpm, Docker.

```bash
git clone https://github.com/Vishwas721/Glacies.git && cd Glacies
cp .env.example .env
uv sync && uv run pre-commit install
(cd web && pnpm install)
docker compose up -d                            # PostGIS + Valkey (the simulation queue)

uv run glacies ingest verify                    # raw archive matches its manifests
uv run glacies build-city bengaluru --clean     # network, walk, zones, attraction (~5 min)
for stage in tt-matrix accessibility demand-matrix paths demand assignment; do
  uv run glacies build $stage                   # what the app and simulations read
done

uv run uvicorn glacies.api.app:app --reload     # http://localhost:8000/api/health
uv run glacies worker                           # runs simulations queued from the UI
(cd web && pnpm dev)                             # http://localhost:5173 (VITE_BASEMAP=blank: no tiles)
```

On Windows, `scripts\start-glacies.bat` (double-click it) does the last three lines and the
Docker step: it shows the battery and free memory, opens the API, worker and web app in their own
windows and opens the Easy view. `start-glacies browse` leaves out the worker (less memory, for
looking at finished results); `start-glacies stop` closes the windows.

The demonstration is scripted in [docs/demo.md](docs/demo.md).

### On a machine with only Docker

With a built `data/` folder (copied over, or built as above), one command runs the app:

```bash
docker compose --profile app up -d --build      # API + web app on http://localhost:8000, worker, Valkey
```

The first build compiles the Rust core (about 12 minutes on the development laptop); data, city
configuration and scenarios are mounted from the checkout, not copied into the image.

Run all checks:

```bash
uv run ruff check && uv run mypy && uv run pytest
cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
(cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm build)
(cd web && pnpm e2e)       # the demo story in Chrome on Toyville; needs Valkey (docker compose up -d redis)
```

## Documentation

- [Phase plan](docs/phases/README.md): what to research, decide and build in each phase
- [Data sources](docs/data-sources.md): datasets, licences, known risks
- [Glossary](docs/glossary.md): transit terms and data-nature labels
- [Contributing](CONTRIBUTING.md): branch/commit/PR workflow and CI
- [CLAUDE.md](CLAUDE.md): rules for coding agents

## Data attribution

Glacies uses data from OpenStreetMap contributors (ODbL), the unofficial BMTC GTFS by
[Vonter](https://github.com/Vonter/bmtc-gtfs) (ODbL), WorldPop (CC-BY 4.0), Google Open Buildings,
and ESA WorldCover. See [docs/data-sources.md](docs/data-sources.md). Code is MIT-licensed; data keeps
its original licences.
