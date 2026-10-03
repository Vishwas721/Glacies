## What & why

<!-- One or two sentences. Link the phase doc / issue: docs/phases/NN-*.md, #123 -->

## How it was verified

<!-- Commands run, toy network used, numbers compared against, screenshots. -->

## Checklist

- [ ] Commits are atomic and use Conventional Commit messages
- [ ] Tests added/updated (toy network first for routing/assignment changes)
- [ ] No city-specific constants in engine code (they belong in `cities/<city>/`)
- [ ] Outputs are labelled **Observed / Estimated / Simulated / Assumed** where shown
- [ ] Deterministic: seeds explicit, no unordered iteration affecting results
- [ ] No datasets or large files committed (`data/` stays local)
- [ ] Docs / ADR updated if a design decision changed
