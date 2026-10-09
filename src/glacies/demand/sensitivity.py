"""How demand's headline numbers move with its assumptions (Phase 5 M5).

Synthetic demand is a set of assumptions, so it is reported as a range. Each variant changes
one thing against the baseline (the configured β and the baseline employment proxy):

* β halved and doubled (the calibrated value is uncertain; see the sweep);
* every alternative employment-proxy weighting in ``[attraction]`` of city.toml;
* trip rate and transit share at both ends of their ranges. These only scale the level of
  demand (each purpose's trip ends by its own priors' factor; gateway trips are fitted and
  stay), so they are derived from the baseline rather than re-run.

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
from glacies.cities import DemandConfig, Prior
from glacies.demand.calibrate import HELD_OUT, TRAINING, Targets, set_fit, station_table
from glacies.demand.metro import station_flows
from glacies.demand.od import GATEWAY, DemandModel, ModelBuild, build_model
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
    end: int | None = None  # level variants: 0 = low, 1 = high end of every purpose's ranges


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


def _level(trip_rate: Prior, transit_share: Prior, end: int) -> float:
    return trip_rate.range[end] * transit_share.range[end] / (trip_rate.value * transit_share.value)


def level_factors(demand: DemandConfig, build: ModelBuild, end: int | None) -> dict[str, float]:
    """Multiplier per purpose: 1, or both priors at one end of their ranges (gateways stay)."""
    factors = {name: 1.0 for name, _ in build.parts()}
    if end is None:
        return factors
    factors[build.main_name] = _level(demand.priors.trip_rate, demand.priors.transit_share, end)
    for purpose in demand.purposes:
        factors[purpose.name] = _level(purpose.trip_rate, purpose.transit_share, end)
    return factors


def _result(
    variant: Variant,
    build: ModelBuild,
    targets: Targets,
    hub_zones: set[int],
    factors: dict[str, float],
) -> VariantResult:
    trips = metro = entries = km = minutes = 0.0
    simulated = None
    stations = None
    for name, od in build.parts():
        f = factors[name] if name != GATEWAY else 1.0
        flows = station_flows(od, targets.reach, targets.paths, targets.stations)
        table, _ = station_table(od, targets)
        part = float(od["trips"].sum())
        trips += f * part
        metro += f * flows.stats.trips_using_metro
        entries += f * flows.stats.entries
        km += f * float((od["trips"] * od["distance_km"]).sum())
        minutes += f * float((od["trips"] * od["cost_s"]).sum()) / 60
        values = table["simulated"].to_numpy() * f
        simulated = values if simulated is None else simulated + values
        stations = table
    if stations is None or simulated is None:
        raise DemandError("the build has no purposes")
    stations = stations.with_columns(pl.Series("simulated", simulated))
    attracted = build.main.ends.table.select("zone_idx", "destination")
    total = float(attracted["destination"].sum())
    hub = float(attracted.filter(pl.col("zone_idx").is_in(sorted(hub_zones)))["destination"].sum())
    top = attracted["destination"].sort(descending=True).head(max(1, attracted.height // 20))
    training = set_fit(stations, TRAINING)
    return VariantResult(
        name=variant.name,
        kind=variant.kind,
        beta_per_min=variant.beta_per_min,
        proxy=variant.proxy,
        trips=trips,
        mean_km=km / trips if trips else 0.0,
        mean_cost_min=minutes / trips if trips else 0.0,
        metro_trip_share=metro / trips if trips else 0.0,
        station_entries=entries,
        r2_training=training.r2_share,
        r2_held_out=set_fit(stations, HELD_OUT).r2_share,
        level_ratio_training=training.level_ratio,
        hub_trip_share=hub / total if total else 0.0,
        top5_zone_trip_share=float(top.sum()) / total if total else 0.0,
    )


def run_variants(
    prepare: Callable[[str], DemandModel],
    demand: DemandConfig,
    targets: Targets,
    proxies: list[str],
    hub_zones: set[int],
    *,
    on_variant: Callable[[VariantResult], None] | None = None,
) -> list[VariantResult]:
    """``prepare(proxy)`` gives the β-independent model for an employment-proxy weighting;
    ``proxies[0]`` is the baseline. Gateways keep the configured factor throughout."""
    beta = demand.gravity.beta_per_min
    base = proxies[0]
    variants = [
        Variant("baseline", "baseline", beta, base),
        Variant("beta x 0.5", "beta", beta / 2, base),
        Variant("beta x 2", "beta", beta * 2, base),
        *(Variant(f"proxy {name}", "proxy", beta, name) for name in proxies[1:]),
    ]
    results: list[VariantResult] = []
    models: dict[str, DemandModel] = {}
    baseline_build: ModelBuild | None = None

    def record(variant: Variant, build: ModelBuild) -> None:
        factors = level_factors(demand, build, variant.end)
        results.append(_result(variant, build, targets, hub_zones, factors))
        if on_variant is not None:
            on_variant(results[-1])

    for variant in variants:
        if variant.proxy not in models:
            models[variant.proxy] = prepare(variant.proxy)
        build = build_model(models[variant.proxy], variant.beta_per_min)
        if variant.kind == "baseline":
            baseline_build = build
        record(variant, build)
    if baseline_build is None:
        raise DemandError("the baseline variant did not run")
    for name, end in (
        ("trip rate and transit share low", 0),
        ("trip rate and transit share high", 1),
    ):
        record(Variant(name, "level", beta, base, end), baseline_build)
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
