# CLAUDE.md — guide for coding agents working on Glacies

Glacies is an urban public-transit digital twin: real data → canonical network → RAPTOR routing →
synthetic demand → assignment/crowding → scenarios → accessibility analytics → visualisation.
The full product spec is the PRD (`docs/prd.md`); the working plan is `docs/phases/`. **Read the phase doc you are
asked to work on before writing code.**

## Repository map

| Path | What lives there |
|---|---|
| `src/glacies/` | Python package: `ingest`, `validate`, `model`, `demand`, `assignment`, `scenario`, `analytics`, `api` |
| `crates/raptor/` | Rust RAPTOR core and walking distances (no PyO3) |
| `crates/raptor-py/` | PyO3 bindings, packaged as `glacies-raptor` (maturin); `uv sync` builds it |
| `web/` | React + TypeScript + Vite frontend (MapLibre/deck.gl from Phase 7) |
| `cities/<city>/city.toml` | Everything city-specific: bbox, CRS, timezone, data sources |
| `data/` | Local only, gitignored: `raw/` → `interim/` → `processed/` |
| `docs/phases/` | Phase plans with kickoff prompts and definitions of done |
| `docs/adr/` | Architecture decision records — add one when a design decision changes |

## Non-negotiable rules

1. **City-agnostic engine.** No Bengaluru-specific constants, IDs, or URLs in `src/` or `crates/`.
   Put them in `cities/<city>/city.toml` and read them through config.
2. **Raw data is never consumed by the engine.** Pipeline is download → archive (with
   `DatasetManifest`) → validate → normalise → canonical dataset in `data/processed/`.
3. **Determinism.** Same data + scenario + config + seed ⇒ identical output. Pass seeds explicitly,
   sort before iterating over sets/dicts when order affects results, never use wall-clock time in
   computations.
4. **Label every quantity** as Observed / Estimated / Simulated / Assumed (`glacies.provenance.DataNature`).
   "Estimated employment" is never called "employment".
5. **No NetworkX (or any per-node Python object graph) for city-scale networks.** Use columnar
   arrays (NumPy/Arrow/Polars) in Python and flat `Vec`s in Rust.
6. **Large results go to Parquet**, queried with DuckDB. PostgreSQL/PostGIS holds geometry and
   metadata, not OD matrices.
7. **Toy networks first.** Any routing/assignment change gets a hand-checkable test on a tiny
   synthetic network before it touches Bengaluru data.
8. **Never fabricate results.** Numbers in docs, UI copy, or PR descriptions must come from a run.
9. **Scope discipline.** Microscopic traffic, GTFS-RT, weather, emissions, LLM interfaces and cloud
   deployment are out of scope (PRD §70). If a task drifts there, stop and ask.

## Commands

```bash
# Python
uv sync                       # install / update env
uv run ruff check --fix && uv run ruff format
uv run mypy                   # strict
uv run pytest                 # add -m "not slow" to skip city-scale tests

# Rust
cargo fmt --all
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace

# Web (from web/)
pnpm install
pnpm lint && pnpm typecheck && pnpm test && pnpm build

# Data archive (see data/README.md)
uv run glacies ingest list | register | fetch | verify
uv run glacies validate gtfs <dataset>    # report in data/processed/<city>/reports/
uv run glacies build-city bengaluru --clean   # everything below, from raw, + BUILD.json
uv run glacies build transit              # canonical network in data/processed/<city>/transit/
uv run glacies build walk                 # OSM walk network + stop snapping in .../walk/
uv run glacies build zones                # H3 zones with population, buildings, land cover, POIs
uv run glacies build attraction           # employment proxy (Estimated) + hub check, sensitivity
uv run glacies build tt-matrix            # zone travel-time percentiles over the AM window (Simulated)
uv run glacies build accessibility        # estimated jobs / population reachable per zone + summaries
uv run glacies accessibility bengaluru     # report: maps, Markdown/HTML, GeoParquet for QGIS
uv run glacies load postgis               # copy zones/stops/pattern lines to PostGIS for QGIS
uv run glacies route LAT,LON LAT,LON --at 08:30   # plan journeys (Simulated)
uv run glacies validate routing | bench routing   # sanity set / performance reports in docs/validation
uv run glacies scenario check scenarios/bengaluru/<id>.json   # validate, apply, report trip changes
uv run glacies scenario calibrate         # measure [scenario] detour_factor for added routes
uv run glacies scenario run scenarios/bengaluru/<id>.json     # apply + tt-matrix + accessibility, cached; --full skips reuse
uv run glacies scenario compare baseline scenarios/bengaluru/<id>.json   # metrics, zone deltas, map, report
uv run glacies scenario schema            # regenerate schemas/scenario.schema.json

# Infra
docker compose up -d          # PostGIS :5433 (host), Redis :6379
uv run uvicorn glacies.api.app:app --reload   # API on :8000

# Everything the hooks check
uv run pre-commit run --all-files
```

All of these must pass before a commit; CI runs the same checks and gates merges on `ci-ok`.

## Workflow

- Branch from `main` (`feat/…`, `fix/…`, `docs/…`, `chore/…`); never push to `main` directly.
- **Atomic Conventional Commits** — one logical change per commit, e.g.
  `feat(raptor): add route scanning loop`, `test(validate): cover orphaned trips`.
  Commit as you go rather than one big commit at the end.
- Open a PR using the template; CI must be green before merge.
- Code style: Python is strictly typed (mypy strict), pydantic models at boundaries; Rust is
  `unsafe`-free with clippy pedantic warnings; TypeScript is `strict` with `noUncheckedIndexedAccess`.
- Match the comment density of surrounding code: docstrings explain *why*, not *what*.
