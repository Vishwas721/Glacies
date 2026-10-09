"""How demand's headline numbers move with its assumptions (Phase 5 M5).

Synthetic demand is a set of assumptions, so it is reported as a range. Each variant changes
one thing against the baseline (the configured β and the baseline employment proxy):

* β halved and doubled (the calibrated value is uncertain; see the sweep);
* every alternative employment-proxy weighting in ``[attraction]`` of city.toml;
* trip rate and transit share at both ends of their ranges. These only scale the level of
  demand (every trip end is multiplied by the same factor), so they are derived from the
  baseline rather than re-run.

Metrics: trips, mean trip length and door-to-door time, the share of trips using the metro,
station entries, the fit of station entry shares on training and held-out stations, and the
shares of trips attracted by the hand-drawn hub zones and by the top 5 % of zones.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.cities import DemandConfig
from glacies.demand.calibrate import HELD_OUT, TRAINING, Targets, set_fit, station_table
from glacies.demand.metro import station_flows
from glacies.demand.od import DemandBuild, Prepared, balance
from glacies.demand.production import DemandError
from glacies.fsutil import rename_with_retry
from glacies.provenance import DataNature, sha256_file

MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
TABLE_NAME = "sensitivity.parquet"


@dataclass(frozen=True)
class Variant:
    name: str
    kind: str  # "baseline", "beta", "proxy" or "level"
    beta_per_min: float
    proxy: str
    level: float = 1.0  # multiplier on every trip end (trip rate x transit share)


class VariantResult(BaseModel):
    name: str
    kind: str
    beta_per_min: float
    proxy: str
    trips: float
    mean_km: float
    mean_cost_min: float
    metro_trip_share: float
    station_entries: float
    r2_training: float
    r2_held_out: float
    level_ratio_training: float
    hub_trip_share: float
    top5_zone_trip_share: float


def _result(
    variant: Variant, build: DemandBuild, targets: Targets, hub_zones: set[int]
) -> VariantResult:
    flows = station_flows(build.od, targets.reach, targets.paths, targets.stations)
    stations, _ = station_table(build, targets)
    attracted = build.ends.table.select("zone_idx", "destination")
    total = float(attracted["destination"].sum())
    hub = float(attracted.filter(pl.col("zone_idx").is_in(sorted(hub_zones)))["destination"].sum())
    top = attracted["destination"].sort(descending=True).head(max(1, attracted.height // 20))
    training = set_fit(stations, TRAINING)
    level = variant.level
    return VariantResult(
        name=variant.name,
        kind=variant.kind,
        beta_per_min=variant.beta_per_min,
        proxy=variant.proxy,
        trips=total * level,
        mean_km=build.trip_length.mean_km,
        mean_cost_min=build.trip_length.mean_cost_min,
        metro_trip_share=flows.stats.trips_using_metro / flows.stats.trips,
        station_entries=flows.stats.entries * level,
        r2_training=training.r2_share,
        r2_held_out=set_fit(stations, HELD_OUT).r2_share,
        level_ratio_training=training.level_ratio * level,
        hub_trip_share=hub / total if total else 0.0,
        top5_zone_trip_share=float(top.sum()) / total if total else 0.0,
    )


def run_variants(
    prepare: Callable[[str], Prepared],
    demand: DemandConfig,
    targets: Targets,
    proxies: list[str],
    hub_zones: set[int],
    *,
    on_variant: Callable[[VariantResult], None] | None = None,
) -> list[VariantResult]:
    """``prepare(proxy)`` gives the β-independent model for an employment-proxy weighting;
    ``proxies[0]`` is the baseline."""
    beta = demand.gravity.beta_per_min
    base = proxies[0]
    priors = demand.priors
    rate = priors.trip_rate.value * priors.transit_share.value
    variants = [
        Variant("baseline", "baseline", beta, base),
        Variant("beta x 0.5", "beta", beta / 2, base),
        Variant("beta x 2", "beta", beta * 2, base),
        *(Variant(f"proxy {name}", "proxy", beta, name) for name in proxies[1:]),
    ]
    results: list[VariantResult] = []
    prepared: dict[str, Prepared] = {}
    baseline_build: DemandBuild | None = None
    for variant in variants:
        if variant.proxy not in prepared:
            prepared[variant.proxy] = prepare(variant.proxy)
        build, _ = balance(prepared[variant.proxy], demand, variant.beta_per_min)
        if variant.kind == "baseline":
            baseline_build = build
        results.append(_result(variant, build, targets, hub_zones))
        if on_variant is not None:
            on_variant(results[-1])
    if baseline_build is None:
        raise DemandError("the baseline variant did not run")
    low = priors.trip_rate.range[0] * priors.transit_share.range[0] / rate
    high = priors.trip_rate.range[1] * priors.transit_share.range[1] / rate
    for name, factor in (
        ("trip rate and transit share low", low),
        ("trip rate and transit share high", high),
    ):
        variant = Variant(name, "level", beta, base, factor)
        results.append(_result(variant, baseline_build, targets, hub_zones))
        if on_variant is not None:
            on_variant(results[-1])
    return results


# --- outputs ----------------------------------------------------------------------------------


class SensitivityInput(BaseModel):
    stage: str
    manifest_sha256: str


class SensitivityManifest(BaseModel):
    city: str
    scenario: str
    builder_version: str
    nature: DataNature
    inputs: list[SensitivityInput]
    results: list[VariantResult]
    outputs: dict[str, str]


def write_sensitivity(
    results: list[VariantResult],
    out_dir: Path,
    *,
    city: str,
    scenario: str,
    inputs: list[SensitivityInput],
) -> SensitivityManifest:
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    table = pl.DataFrame([r.model_dump() for r in results])
    table.rechunk().write_parquet(staging / TABLE_NAME, compression="zstd", statistics=True)
    manifest = SensitivityManifest(
        city=city,
        scenario=scenario,
        builder_version=__version__,
        nature=DataNature.ESTIMATED,
        inputs=inputs,
        results=results,
        outputs={TABLE_NAME: sha256_file(staging / TABLE_NAME)},
    )
    (staging / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (staging / REPORT_NAME).write_text(report(manifest), encoding="utf-8", newline="\n")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rename_with_retry(staging, out_dir)
    return manifest


def _range(values: list[float], fmt: str) -> str:
    return f"{format(min(values), fmt)} to {format(max(values), fmt)}"


def report(m: SensitivityManifest) -> str:
    rows = m.results
    shape = [r for r in rows if r.kind != "level"]
    return "\n".join(
        [
            f"# Demand sensitivity — `{m.city}` / `{m.scenario}` (Estimated)",
            "",
            f"Builder {m.builder_version}. One assumption changes per row; the baseline uses "
            "the configured β and the baseline employment proxy. The two level rows scale "
            "every trip end and leave shapes unchanged.",
            "",
            "| Variant | β | Proxy | Trips | Mean km | Mean min | Metro share | Entries "
            "| R² train | R² held-out | Level (train) | Hub share | Top-5 % share |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            *(
                f"| {r.name} | {r.beta_per_min:.4f} | {r.proxy} | {r.trips:,.0f} | "
                f"{r.mean_km:.1f} | {r.mean_cost_min:.1f} | {r.metro_trip_share:.1%} | "
                f"{r.station_entries:,.0f} | {r.r2_training:.2f} | {r.r2_held_out:.2f} | "
                f"{r.level_ratio_training:.2f} | {r.hub_trip_share:.1%} | "
                f"{r.top5_zone_trip_share:.1%} |"
                for r in rows
            ),
            "",
            "## Ranges",
            "",
            f"- Trips: {_range([r.trips for r in rows], ',.0f')}.",
            f"- Mean trip length: {_range([r.mean_km for r in shape], '.1f')} km.",
            f"- Share of trips using the metro: "
            f"{_range([r.metro_trip_share for r in shape], '.1%')}.",
            f"- Station entries: {_range([r.station_entries for r in rows], ',.0f')}.",
            f"- Held-out R² (station entry shares): "
            f"{_range([r.r2_held_out for r in shape], '.2f')}.",
            "",
        ]
    )
