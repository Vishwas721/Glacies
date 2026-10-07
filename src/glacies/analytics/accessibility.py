"""Cumulative-opportunity accessibility per zone and city summaries (Phase 3 M3).

For every origin zone, percentile and threshold: the share of the city's **estimated** jobs
(the employment proxy) and of its population that can be reached by transit and walking within
the threshold, using the travel-time matrix percentile. These are model outputs (**Simulated**,
built on Estimated opportunities) and are reported as shares of the city, never as job counts.

City summaries weight zones by their residents (the PRD's headline: population-weighted mean
share of estimated jobs reachable within 45 min at the median) and describe the distribution
(weighted percentiles, Gini), because a mean hides who is left out. Zones near the study-area
edge are flagged: destinations beyond the bbox are missing, so they look worse than they are.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.cities import Accessibility
from glacies.demand.attraction import POPULATION_REFERENCE
from glacies.fsutil import rename_with_retry
from glacies.provenance import DataNature, sha256_file

F64 = npt.NDArray[np.float64]
Bbox = tuple[float, float, float, float]
MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
ZONES_TABLE = "accessibility.parquet"
SUMMARY_TABLE = "summary.parquet"
SENSITIVITY_TABLE = "sensitivity.parquet"
MEASURES = ("est_jobs", "population")
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
METRES_PER_DEGREE_LAT = 110_574.0
METRES_PER_DEGREE_LON = 111_320.0  # at the equator; scaled by cos(latitude)

COLUMN_NATURE: dict[str, DataNature] = {
    "est_jobs_share": DataNature.SIMULATED,  # Simulated reach of Estimated jobs
    "est_opportunity_index": DataNature.SIMULATED,
    "population_share": DataNature.SIMULATED,  # Simulated reach of Estimated population
    "edge_zone": DataNature.ASSUMED,  # depends on the Assumed buffer
}


class AccessibilityError(ValueError):
    """Accessibility cannot be computed from the given inputs."""


def edge_zones(lat: F64, lon: F64, bbox: Bbox, buffer_m: float) -> npt.NDArray[np.bool_]:
    """Points within ``buffer_m`` of the bbox edge (local metric approximation, < 1 % error)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    dx = np.minimum(lon - min_lon, max_lon - lon) * METRES_PER_DEGREE_LON * np.cos(np.radians(lat))
    dy = np.minimum(lat - min_lat, max_lat - lat) * METRES_PER_DEGREE_LAT
    result: npt.NDArray[np.bool_] = np.minimum(dx, dy) < buffer_m
    return result


def opportunities(zones: pl.DataFrame, attraction: pl.DataFrame) -> pl.DataFrame:
    """Per destination zone: its share of estimated jobs and of population (each sums to 1)."""
    table = zones.select("zone_idx", "population").join(
        attraction.select("zone_idx", "employment_score"), on="zone_idx", how="left"
    )
    if table["employment_score"].null_count():
        raise AccessibilityError("attraction does not cover every zone; rebuild it")
    population = table["population"].sum()
    if population <= 0:
        raise AccessibilityError("zones have no population")
    return table.sort("zone_idx").select(
        "zone_idx",
        pl.col("employment_score").alias("est_jobs"),
        (pl.col("population") / population).alias("population"),
    )


def cumulative(
    matrix: pl.LazyFrame, opportunity: pl.DataFrame, settings: Accessibility
) -> pl.DataFrame:
    """Long table: zone_idx, percentile, threshold_min, est_jobs_share, population_share.

    The matrix is scanned lazily (one filtered aggregation per percentile and threshold), so
    it is never materialised as Python objects.
    """
    zones = opportunity.select("zone_idx")
    opp = opportunity.lazy().rename({"zone_idx": "dest_zone"})
    frames = []
    for p in settings.percentiles:
        column = f"p{p}_s"
        for t in settings.thresholds_min:
            reached = (
                matrix.filter(pl.col(column) <= t * 60)
                .select("origin_zone", "dest_zone")
                .join(opp, on="dest_zone")
                .group_by("origin_zone")
                .agg(
                    pl.col("est_jobs").sum().alias("est_jobs_share"),
                    pl.col("population").sum().alias("population_share"),
                )
                .collect()
            )
            frames.append(
                zones.join(reached, left_on="zone_idx", right_on="origin_zone", how="left")
                .with_columns(pl.col("est_jobs_share", "population_share").fill_null(0.0))
                .with_columns(
                    pl.lit(p, dtype=pl.UInt8).alias("percentile"),
                    pl.lit(t, dtype=pl.UInt16).alias("threshold_min"),
                )
            )
    return (
        pl.concat(frames)
        .select("zone_idx", "percentile", "threshold_min", "est_jobs_share", "population_share")
        .sort("zone_idx", "percentile", "threshold_min")
    )


def weighted_quantile(values: F64, weights: F64, q: float) -> float:
    """Smallest value whose cumulative weight reaches ``q`` of the total (ties: stable order)."""
    order = np.argsort(values, kind="stable")
    cumulative_weight = np.cumsum(weights[order])
    index = int(np.searchsorted(cumulative_weight, q * cumulative_weight[-1], side="left"))
    return float(values[order][min(index, values.size - 1)])


def weighted_gini(values: F64, weights: F64) -> float:
    """Gini coefficient of ``values`` over people (0 = everyone equal, 1 = one zone has all).

    ``Σ_i Σ_j w_i w_j |x_i - x_j| / (2 W² μ)``, computed in O(n log n) on sorted values.
    """
    order = np.argsort(values, kind="stable")
    x, w = values[order], weights[order]
    total = float(w.sum())
    if total <= 0:
        return 0.0
    mean = float((w * x).sum()) / total
    if mean <= 0:
        return 0.0
    above = total - np.cumsum(w)
    below = np.cumsum(w) - w
    pairs = 2.0 * float((w * x * (below - above)).sum())
    return float(pairs / (2.0 * total**2 * mean))


def summaries(table: pl.DataFrame, population: F64, edge: npt.NDArray[np.bool_]) -> pl.DataFrame:
    """Population-weighted summaries per scope, percentile, threshold and measure."""
    rows = []
    scopes = {"all zones": np.ones_like(edge), "excluding edge zones": ~edge}
    keys = table.select("percentile", "threshold_min").unique().sort("percentile", "threshold_min")
    for scope, keep in scopes.items():
        weights = population[keep]
        for p, t in keys.iter_rows():
            part = table.filter((pl.col("percentile") == p) & (pl.col("threshold_min") == t))
            for measure in MEASURES:
                values = part[f"{measure}_share"].to_numpy()[keep]
                rows.append(
                    {
                        "scope": scope,
                        "percentile": p,
                        "threshold_min": t,
                        "measure": measure,
                        "population_weighted_mean": float((values * weights).sum() / weights.sum()),
                        **{
                            f"q{round(q * 100):02d}": weighted_quantile(values, weights, q)
                            for q in QUANTILES
                        },
                        "gini": weighted_gini(values, weights),
                        "population_share_below_1pct": float(
                            weights[values < 0.01].sum() / weights.sum()
                        ),
                    }
                )
    return pl.DataFrame(rows)


def headline_sensitivity(
    matrix: pl.LazyFrame,
    zone_idx: npt.NDArray[np.uint32],
    population: F64,
    opportunity_sets: dict[str, F64],
    settings: Accessibility,
) -> pl.DataFrame:
    """Headline-percentile reach of each opportunity set, per threshold (Phase 3 M5).

    Every set (e.g. the employment proxy under different weights) is aggregated in one lazy
    pass over the matrix. The first set is the baseline that changes are measured against.
    ``opportunity_sets`` values are shares per zone, in ``zone_idx`` order.
    """
    column = f"p{settings.headline_percentile}_s"
    names = list(opportunity_sets)
    opp = pl.DataFrame(
        {"dest_zone": pl.Series(zone_idx, dtype=pl.UInt32)}
        | {f"o{i}": opportunity_sets[name] for i, name in enumerate(names)}
    )
    reached = (
        matrix.filter(pl.col(column) <= settings.thresholds_min[-1] * 60)
        .select("origin_zone", "dest_zone", column)
        .join(opp.lazy(), on="dest_zone")
        .group_by("origin_zone")
        .agg(
            pl.col(f"o{i}").filter(pl.col(column) <= t * 60).sum().alias(f"o{i}_{t}")
            for i in range(len(names))
            for t in settings.thresholds_min
        )
        .collect()
    )
    full = (
        pl.DataFrame({"origin_zone": pl.Series(zone_idx, dtype=pl.UInt32)})
        .join(reached, on="origin_zone", how="left", maintain_order="left")
        .fill_null(0.0)
    )
    rows = []
    baseline: dict[int, float] = {}
    for i, name in enumerate(names):
        for t in settings.thresholds_min:
            values = full[f"o{i}_{t}"].to_numpy()
            mean = float((values * population).sum() / population.sum())
            baseline.setdefault(t, mean)
            rows.append(
                {
                    "weighting": name,
                    "threshold_min": t,
                    "population_weighted_mean": mean,
                    "q50": weighted_quantile(values, population, 0.5),
                    "gini": weighted_gini(values, population),
                    "change_vs_baseline": mean - baseline[t],
                }
            )
    return pl.DataFrame(rows)


# --- build ------------------------------------------------------------------------------------


@dataclass
class AccessibilityBuild:
    zones: pl.DataFrame
    summary: pl.DataFrame
    headline: float
    edge_count: int
    sensitivity: pl.DataFrame | None = None


def build_accessibility(
    zones: pl.DataFrame,
    attraction: pl.DataFrame,
    matrix: pl.LazyFrame,
    settings: Accessibility,
    *,
    bbox: Bbox,
    index_total: int,
    alternatives: dict[str, F64] | None = None,
) -> AccessibilityBuild:
    """``alternatives``: estimated-job shares per zone under each proxy weighting, baseline
    first, for the headline sensitivity table; population is added as a reference."""
    zones = zones.sort("zone_idx")
    has_point = pl.col("pop_lat").is_not_null()
    lat = zones.select(pl.when(has_point).then("pop_lat").otherwise("lat")).to_series()
    lon = zones.select(pl.when(has_point).then("pop_lon").otherwise("lon")).to_series()
    edge = edge_zones(lat.to_numpy(), lon.to_numpy(), bbox, settings.edge_buffer_m)
    long = cumulative(matrix, opportunities(zones, attraction), settings)
    table = (
        long.join(
            zones.select("zone_idx", "h3_cell").with_columns(pl.Series("edge_zone", edge)),
            on="zone_idx",
        )
        .with_columns((pl.col("est_jobs_share") * index_total).alias("est_opportunity_index"))
        .select(
            "zone_idx",
            "h3_cell",
            "edge_zone",
            "percentile",
            "threshold_min",
            "est_jobs_share",
            "est_opportunity_index",
            "population_share",
        )
        .sort("zone_idx", "percentile", "threshold_min")
    )
    summary = summaries(long, zones["population"].to_numpy().astype(np.float64), edge)
    head = summary.filter(
        (pl.col("scope") == "all zones")
        & (pl.col("percentile") == settings.headline_percentile)
        & (pl.col("threshold_min") == settings.headline_threshold_min)
        & (pl.col("measure") == "est_jobs")
    )["population_weighted_mean"]
    sensitivity = None
    if alternatives:
        population = zones["population"].to_numpy().astype(np.float64)
        sets = dict(alternatives) | {POPULATION_REFERENCE: population / population.sum()}
        sensitivity = headline_sensitivity(
            matrix, zones["zone_idx"].to_numpy(), population, sets, settings
        )
    return AccessibilityBuild(
        zones=table,
        summary=summary,
        headline=float(head[0]),
        edge_count=int(edge.sum()),
        sensitivity=sensitivity,
    )


class AccessibilityInput(BaseModel):
    stage: str
    manifest_sha256: str


class AccessibilityManifest(BaseModel):
    city: str
    scenario: str
    builder_version: str
    inputs: list[AccessibilityInput]
    settings: Accessibility
    opportunity_index_total: int
    headline_est_jobs_share: float
    headline_by_weighting: dict[str, float]
    edge_zones: int
    column_nature: dict[str, DataNature]
    outputs: dict[str, str]


def write_accessibility(
    build: AccessibilityBuild,
    out_dir: Path,
    *,
    city: str,
    scenario: str,
    settings: Accessibility,
    index_total: int,
    inputs: list[AccessibilityInput],
) -> AccessibilityManifest:
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    outputs = {}
    tables = [(ZONES_TABLE, build.zones), (SUMMARY_TABLE, build.summary)]
    if build.sensitivity is not None:
        tables.append((SENSITIVITY_TABLE, build.sensitivity))
    for name, frame in tables:
        frame.write_parquet(staging / name, compression="zstd", statistics=True)
        outputs[name] = sha256_file(staging / name)
    by_weighting = {}
    if build.sensitivity is not None:
        head = build.sensitivity.filter(pl.col("threshold_min") == settings.headline_threshold_min)
        by_weighting = {
            str(w): round(float(v), 6)
            for w, v in head.select("weighting", "population_weighted_mean").iter_rows()
        }
    manifest = AccessibilityManifest(
        city=city,
        scenario=scenario,
        builder_version=__version__,
        inputs=inputs,
        settings=settings,
        opportunity_index_total=index_total,
        headline_est_jobs_share=round(build.headline, 6),
        headline_by_weighting=by_weighting,
        edge_zones=build.edge_count,
        column_nature=COLUMN_NATURE,
        outputs=outputs,
    )
    (staging / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (staging / REPORT_NAME).write_text(
        report(manifest, build.summary, build.zones.height, build.sensitivity),
        encoding="utf-8",
        newline="\n",
    )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rename_with_retry(staging, out_dir)
    return manifest


def _pct(value: float) -> str:
    return f"{value:.1%}" if value >= 0.001 or value == 0 else f"{value:.2%}"


def sensitivity_rows(table: pl.DataFrame, thresholds: list[int], headline: int) -> list[list[str]]:
    """Report rows: weighting, mean share per threshold, change and Gini at the headline."""
    rows = []
    for name in table["weighting"].unique(maintain_order=True):
        part = table.filter(pl.col("weighting") == name).sort("threshold_min")
        means = dict(part.select("threshold_min", "population_weighted_mean").iter_rows())
        at_headline = part.filter(pl.col("threshold_min") == headline)
        rows.append(
            [
                str(name),
                *(_pct(means[t]) for t in thresholds),
                f"{float(at_headline['change_vs_baseline'][0]) * 100:+.2f} pp",
                f"{float(at_headline['gini'][0]):.2f}",
            ]
        )
    return rows


def report(
    m: AccessibilityManifest,
    summary: pl.DataFrame,
    rows: int,
    sensitivity: pl.DataFrame | None = None,
) -> str:
    s = m.settings
    hp, ht = s.headline_percentile, s.headline_threshold_min

    def pick(scope: str, p: int, measure: str) -> pl.DataFrame:
        return summary.filter(
            (pl.col("scope") == scope)
            & (pl.col("percentile") == p)
            & (pl.col("measure") == measure)
        ).sort("threshold_min")

    lines = [
        f"# Accessibility — `{m.city}` / `{m.scenario}`",
        "",
        f"Builder {m.builder_version} · {rows:,} rows · {m.edge_zones:,} edge zones",
        "",
        "## Headline (Simulated; jobs Estimated)",
        "",
        f"Residents can reach on average **{_pct(m.headline_est_jobs_share)} of the city's "
        f"estimated jobs** within {ht} min by transit and walking (median over "
        f"{s.window_start}-{s.window_end} departures; population-weighted mean over all zones).",
        "",
        "## Population-weighted mean share reachable",
        "",
        "| Measure | Percentile | " + " | ".join(f"{t} min" for t in s.thresholds_min) + " |",
        "|---|---|" + "---:|" * len(s.thresholds_min),
    ]
    for measure, label in (("est_jobs", "Estimated jobs"), ("population", "Population")):
        for p in s.percentiles:
            values = pick("all zones", p, measure)["population_weighted_mean"].to_list()
            lines.append(f"| {label} | p{p} | " + " | ".join(_pct(v) for v in values) + " |")
    lines += [
        "",
        f"p{s.percentiles[0]} is a good day (a quarter of departures do at least this well), "
        f"p{s.percentiles[-1]} a bad one.",
        "",
        f"## Distribution of estimated jobs reachable (p{hp})",
        "",
        "Quantiles are over residents, not zones: q10 means 10 % of residents reach less.",
        "",
        "| Scope | Threshold | Mean | q10 | q25 | q50 | q75 | q90 | Gini | Residents < 1 % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scope in ("all zones", "excluding edge zones"):
        for row in pick(scope, hp, "est_jobs").iter_rows(named=True):
            quantiles = " | ".join(_pct(row[f"q{round(q * 100):02d}"]) for q in QUANTILES)
            lines.append(
                f"| {scope} | {row['threshold_min']} min | "
                f"{_pct(row['population_weighted_mean'])} | {quantiles} | {row['gini']:.2f} | "
                f"{_pct(row['population_share_below_1pct'])} |"
            )
    if sensitivity is not None:
        lines += [
            "",
            f"## Sensitivity to the employment-proxy weights (p{hp}, weights Assumed)",
            "",
            "Population-weighted mean share of estimated jobs reachable under each weighting of "
            "the proxy (see the attraction report). The population row is a reference, not a "
            "proxy.",
            "",
            "| Weighting | "
            + " | ".join(f"{t} min" for t in s.thresholds_min)
            + f" | Change at {ht} min | Gini at {ht} min |",
            "|---|" + "---:|" * (len(s.thresholds_min) + 2),
            *(
                "| " + " | ".join(row) + " |"
                for row in sensitivity_rows(sensitivity, s.thresholds_min, ht)
            ),
        ]
    lines += [
        "",
        "## Notes and labels",
        "",
        "- Opportunities: `est_jobs` is the employment proxy (Estimated; weights Assumed) and "
        "population is WorldPop (Estimated). Reach is Simulated from the travel-time matrix.",
        f"- `est_opportunity_index` = share x {m.opportunity_index_total:,} (Assumed base): an "
        "index for display, not a count of jobs.",
        f"- Edge zones: point within {s.edge_buffer_m:g} m of the study-area bbox (Assumed). "
        "Their destinations outside the bbox are missing, so they are flagged and summarised "
        "separately.",
        "- Every zone reaches itself, so a zone's own jobs and residents always count.",
        "",
        "Column labels:",
        "",
        *(f"- `{column}`: {nature.value}" for column, nature in m.column_nature.items()),
        "",
    ]
    if not math.isfinite(m.headline_est_jobs_share):
        raise AccessibilityError("headline is not finite")
    return "\n".join(lines)
