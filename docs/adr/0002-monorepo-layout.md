# ADR 0002 — Single monorepo with Python package, Rust workspace and web app

- **Status:** Accepted
- **Date:** 2026-10-03

## Context

The PRD calls for Python (ingestion, demand, API), Rust (routing core), and TypeScript (UI). A solo
developer needs one place to change an interface end-to-end and one CI pipeline.

## Decision

- One repository with three toolchains side by side:
  - `src/glacies/`: a **single** Python package managed by uv, with sub-packages per pipeline
    stage. No multi-package workspace until there is a real reason to publish parts separately.
  - `crates/`: a Cargo workspace. `raptor` is pure Rust. The PyO3 extension is a separate crate
    built with maturin (Phase 2), so the core stays testable without Python.
  - `web/`: a Vite + React + TypeScript app managed by pnpm.
- City-specific data lives in `cities/<city>/` as configuration, never in code.
- CI path-filters per toolchain, and a single `ci-ok` job is the required check.

## Consequences

- One PR can change the Rust core, the Python binding, and the UI together.
- Contributors need three toolchains locally, mitigated by pinned versions and `CONTRIBUTING.md`.
- If the Python package grows too large, split it into a uv workspace (new ADR).
