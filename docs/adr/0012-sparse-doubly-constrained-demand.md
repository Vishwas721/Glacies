# ADR 0012 — Sparse doubly constrained demand with attainable attractions

- **Status:** Accepted
- **Date:** 2026-10-09

## Context

Phase 5 needs an AM-peak transit OD matrix from a doubly constrained gravity model (PRD §22).
The Phase 3 travel-time matrix stores only pairs reached within 120 minutes, and only 3,465 of
Bengaluru's 10,661 zones have a stop within the 800 m access walk. On that support the targets
cannot all be met: the employment proxy gives some zones more attraction than the origins that
reach them by transit can send, and some clusters of zones reach only each other. On the first
Bengaluru run Furness did not converge: a max flow showed 5,428 trips (1.4 %) that no matrix on
the reachable pairs could place, and the balancing factors overflowed after about 100
iterations.

## Decision

- Productions and attractions come only from zones with a stop within the access walk (the
  same walks the matrix uses). Intrazonal pairs are excluded. Zones that cannot reach or be
  reached by another such zone are dropped and counted.
- The model is sparse: parallel arrays of pairs, sums by `np.bincount`; never a dense n x n.
- **Attainable attractions.** Before Furness, a max flow on the pair support finds the
  bottleneck (the minimal min cut). Pairs from outside the bottleneck's origins into its
  destinations carry no trips in the limit of Furness on infeasible targets (Gietl & Reffel
  2017), so they are dropped, and each side becomes a block whose attractions are rescaled to
  its productions. Blocks are split until each is feasible. Productions never change. The trips
  of attraction moved, the number of blocks and the pairs dropped are reported.
- Furness then has to converge to the configured tolerance, or the build fails. It also stops
  if its factors become non-finite, rather than looping.

## Alternatives considered

- **Accept non-convergence and stop after N iterations.** The result depends on N, and the
  factors overflow before the column error settles.
- **Give unreachable pairs a small friction.** Always feasible, but it puts trips on pairs that
  transit cannot serve within the matrix cut-off, which assignment would then have to drop.
- **Production-constrained model.** It is always feasible, but destination totals would no
  longer follow the employment proxy anywhere, not only where the network forces it.

## Consequences

- Row sums equal `O` exactly; column sums equal the attainable `D`, which differs from the
  proxy-scaled `D` by a reported amount (Bengaluru baseline: 7,373 trips, 1.9 %, in 238 blocks).
  Both columns are kept in `trip_ends.parquet`.
- Furness needs about 1,600 iterations on Bengaluru (~85 s). Calibration sweeps over β will want
  warm starts or a coarser tolerance.
