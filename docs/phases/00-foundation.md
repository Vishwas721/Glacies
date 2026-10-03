# Phase 0 — Foundation

## 1. Goal & why

A repository where every later phase can start writing domain code right away: three toolchains
wired up, local infrastructure running, CI blocking broken merges, and a written plan.
**Status: implemented in PR `chore/project-foundation`.**

## 2. Prerequisites

Installed locally: Python 3.11+, uv, rustup, Node 22, pnpm, Docker Desktop, gh CLI (authenticated).

## 3. Research before starting

- Skim the whole PRD once more, then read `docs/phases/README.md` and the four ADRs in `docs/adr/`.
- [Conventional Commits](https://www.conventionalcommits.org/): how to write commit messages here.
- GitHub docs: *About protected branches* and *required status checks*, so you understand why
  merges are blocked.
- (Optional) uv docs, *Projects* and *Locking*; Cargo book, *Workspaces*.

## 4. Decisions you must make

| Decision | Made in Phase 0 |
|---|---|
| Code licence | MIT (data keeps its own licences, see `docs/data-sources.md`) |
| Merge strategy | PR-only, `ci-ok` required, rebase-merge recommended to keep atomic commits |
| CI vs CD | CI yes, CD no: nothing to deploy (local-first, cloud is a non-goal) |

## 5. Your hands-on tasks

- [ ] Review the foundation PR on GitHub and confirm CI is green.
- [ ] Merge it (rebase-merge keeps the individual commits on `main`).
- [ ] Locally: `uv sync`, `uv run pre-commit install`, `cd web && pnpm install`, `cp .env.example .env`.
- [ ] `docker compose up -d` and check both containers are `healthy` (`docker compose ps`).
- [ ] In repo **Settings → General → Pull Requests**, enable "Automatically delete head branches".
- [ ] Optional: enable "Allow rebase merging" only, so atomic commits are preserved.

## 6. Agent tasks (done)

Repo hygiene files · uv-managed `glacies` package with ruff/mypy/pytest · FastAPI health endpoint ·
`DatasetManifest` + `DataNature` · Cargo workspace + `glacies-raptor` skeleton · Vite/React/TS web
shell with ESLint/Prettier/Vitest · docker-compose (PostGIS 16 + Redis 7) · Bengaluru `city.toml` ·
pre-commit · CI with path filters and `ci-ok` gate · Dependabot · PR/issue templates · CLAUDE.md,
CONTRIBUTING, glossary, data-sources registry, ADRs, these phase docs · branch protection on `main`.

## 7. Kickoff prompt

Already executed. To re-check the foundation later:

```text
Audit the Glacies foundation against docs/phases/00-foundation.md. Run every check listed in
CLAUDE.md (python, rust, web, pre-commit), start docker compose and hit /api/health. Report
anything failing or drifting from the doc, and fix it in atomic commits on a chore/ branch.
```

## 8. Deliverables

See the repository layout in the root `README.md`.

## 9. Definition of done

- [ ] `uv run pytest`, `uv run mypy`, `cargo test`, `cargo clippy -- -D warnings`,
      `pnpm -C web build`, `uv run pre-commit run --all-files` all pass locally.
- [ ] `uv run uvicorn glacies.api.app:app` → `GET http://localhost:8000/api/health` returns `{"status":"ok",…}`.
- [ ] `pnpm -C web dev` shows the three-panel shell.
- [ ] On GitHub, a direct push to `main` is rejected and a PR shows the `ci-ok` check.

## 10. Risks & pitfalls

- **Windows line endings.** `.gitattributes` forces LF; if a tool rewrites CRLF, pre-commit fixes it.
- **TypeScript 7.** typescript-eslint does not support the TS 7 native compiler yet, so TS is pinned
  to 6.x and Dependabot ignores ≥7. Lift that when typescript-eslint supports it.
- **Toolchain drift.** Rust is pinned in `rust-toolchain.toml`, Python in `.python-version`, and pnpm
  in `web/package.json#packageManager`. Bump them deliberately.

**Core:** CI, hooks, layout. **Later:** release tagging, docs site. **Never:** cloud CD.
