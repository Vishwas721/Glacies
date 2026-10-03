# ADR 0001 — Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-03

## Context

Glacies is a long-running research project with one developer and coding agents. Decisions made
early on (language split, storage, model fidelity) are easy to forget, and agents cannot ask
"why is it like this?".

## Decision

Record every significant design decision as a short ADR in `docs/adr/NNNN-title.md`, using this
template: **Context → Decision → Consequences**, with status `Proposed | Accepted | Superseded by NNNN`.
ADRs are never edited after acceptance except to mark them superseded.

## Consequences

- Each phase that changes architecture adds an ADR in the same PR.
- `CLAUDE.md` points agents here before they change a structural decision.
