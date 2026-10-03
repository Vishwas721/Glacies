# Contributing

Glacies is currently a solo project, but the workflow is the same one a team would use, so `main`
is always in a working state.

## One-time setup

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), Rust (via rustup — the version is
pinned in `rust-toolchain.toml`), Node 22 + pnpm, Docker.

```bash
uv sync                        # Python env + dev tools
uv run pre-commit install      # run hooks on every commit
(cd web && pnpm install)
cp .env.example .env
docker compose up -d
```

## Day-to-day flow

1. `git switch -c feat/<short-name>` from an up-to-date `main`.
2. Make small, atomic commits with [Conventional Commit](https://www.conventionalcommits.org/)
   messages:

   | Type | Use for |
   |---|---|
   | `feat` | new capability |
   | `fix` | bug fix |
   | `test` | tests only |
   | `docs` | documentation only |
   | `refactor` | no behaviour change |
   | `perf` | performance |
   | `build` | dependencies, packaging |
   | `ci` | workflows |
   | `chore` | tooling, housekeeping |

   Scopes follow the code layout: `core`, `ingest`, `validate`, `model`, `raptor`, `demand`,
   `assignment`, `scenario`, `analytics`, `api`, `web`, `cities`, `data`.
3. `git push -u origin HEAD` and open a PR (`gh pr create --fill`).
4. Wait for **ci-ok** to go green, review your own diff on GitHub, then **squash or rebase merge**.
   Rebase-merge keeps every atomic commit on `main`.
5. Delete the branch.

## What CI checks

| Job | Runs when | Checks |
|---|---|---|
| Hygiene | always | whitespace, EOF, YAML/TOML/JSON, merge markers, private keys, files > 500 KB |
| Python | `src/`, `tests/`, `pyproject.toml`, `uv.lock` change | ruff, ruff format, mypy strict, pytest + coverage |
| Rust | `crates/`, `Cargo.*` change | rustfmt, clippy `-D warnings`, cargo test |
| Web | `web/` changes | eslint + prettier, tsc, vitest, vite build |
| **ci-ok** | always | passes only if none of the above failed. This is the required check on `main` |

## Adding a design decision

Copy `docs/adr/0001-record-architecture-decisions.md`, number it, and describe the context,
decision, and consequences. Reference it from the PR.
