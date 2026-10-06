"""Compare simulated journeys with a reference set of known trips (PRD §57, level 2).

The reference times are Estimated (e.g. Google Maps); the router's are Simulated. A pair passes
when the fastest simulated journey is within ``tolerance_share`` of the expected time or within
``tolerance_min`` minutes, whichever is looser (Phase 2 definition of done: 90 % of pairs).
"""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel

from glacies.routing.network import Router, RouterError, clock, parse_clock


class SanityPair(BaseModel):
    id: int
    origin: str
    origin_stop: str
    origin_lat: float
    origin_lon: float
    destination: str
    destination_stop: str
    destination_lat: float
    destination_lon: float
    departure: str
    expected_min: int
    source: str
    review_note: str = ""


class SanityResult(BaseModel):
    pair: SanityPair
    simulated_min: int | None  # fastest journey, door to door from the departure time
    transfers: int | None
    fewest_transfers_min: int | None
    journeys: int
    error: str | None = None

    def within(self, share: float, minutes: int) -> bool:
        if self.simulated_min is None:
            return False
        allowed = max(self.pair.expected_min * share, minutes)
        return abs(self.simulated_min - self.pair.expected_min) <= allowed


def read_pairs(path: Path) -> list[SanityPair]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [SanityPair.model_validate(row) for row in csv.DictReader(handle)]


def run_pairs(router: Router, pairs: list[SanityPair]) -> list[SanityResult]:
    results = []
    for pair in pairs:
        departure = parse_clock(pair.departure)
        try:
            journeys = router.plan(
                (pair.origin_lat, pair.origin_lon),
                (pair.destination_lat, pair.destination_lon),
                departure,
            )
        except RouterError as exc:
            results.append(
                SanityResult(
                    pair=pair,
                    simulated_min=None,
                    transfers=None,
                    fewest_transfers_min=None,
                    journeys=0,
                    error=str(exc),
                )
            )
            continue
        fastest = journeys[-1] if journeys else None  # plan() orders by vehicles; last is fastest
        fewest = journeys[0] if journeys else None
        results.append(
            SanityResult(
                pair=pair,
                simulated_min=round(fastest.travel_time / 60) if fastest else None,
                transfers=fastest.transfers if fastest else None,
                fewest_transfers_min=round(fewest.travel_time / 60) if fewest else None,
                journeys=len(journeys),
            )
        )
    return results


def report(
    results: list[SanityResult], *, share: float, minutes: int, header: str
) -> tuple[str, int]:
    """Markdown report and the number of pairs within tolerance."""
    passed = sum(r.within(share, minutes) for r in results)
    lines = [
        "# Routing sanity check",
        "",
        header,
        "",
        f"**{passed} of {len(results)} pairs within ±{share:.0%} or ±{minutes} min** "
        f"(target: 90 %). Simulated times are door to door from the departure time, including "
        "the wait for the first vehicle.",
        "",
        "| # | From → To | Depart | Expected (Estimated) | Simulated fastest | Transfers | "
        "Fewest-transfer option | Within | Note |",
        "|---:|---|---|---:|---:|---:|---:|:---:|---|",
    ]
    for r in results:
        p = r.pair
        sim = "—" if r.simulated_min is None else f"{r.simulated_min} min"
        fewest = "—" if r.fewest_transfers_min is None else f"{r.fewest_transfers_min} min"
        note = r.error or p.review_note
        lines.append(
            f"| {p.id} | {p.origin} → {p.destination} | {p.departure} | {p.expected_min} min | "
            f"{sim} | {'—' if r.transfers is None else r.transfers} | {fewest} | "
            f"{'✅' if r.within(share, minutes) else '❌'} | {note} |"
        )
    lines += [
        "",
        "Stops used: see `bengaluru-sanity-set.csv`. Pairs with a review note involve an ambiguous",
        "place and should be confirmed before drawing conclusions from them.",
        "",
    ]
    return "\n".join(lines), passed


__all__ = ["SanityPair", "SanityResult", "clock", "read_pairs", "report", "run_pairs"]
