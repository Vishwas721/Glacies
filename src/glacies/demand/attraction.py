"""Employment proxy per zone (Phase 3 M1; reused as trip attraction in Phase 5).

Data-poor cities have no job census by zone, so employment is **Estimated** from two layers
already in the zones table: building footprint area (Open Buildings) and job-type POIs (OSM).
Each layer is turned into its share of the city total before weighting, because the raw
values have different units (m² vs counts). The weights are **Assumed**.

``employment_score`` is therefore a share of the city's estimated employment and sums to 1.
``opportunity_index`` rescales it to an assumed display base; it is an index, never a job
count. Transit stop counts are deliberately not an input: accessibility is computed from the
transit network, and using it here would make the metric circular.

Validation compares the ranking with hand-drawn polygons of known employment hubs.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import h3
import numpy as np
import numpy.typing as npt
import polars as pl
import shapely
from pydantic import BaseModel
from scipy.stats import spearmanr
from shapely.geometry import Polygon, shape
from shapely.geometry.base import BaseGeometry

from glacies import __version__
from glacies.cities import Attraction, ProxyWeights
from glacies.fsutil import rename_with_retry
from glacies.provenance import DataNature, sha256_file

F64 = npt.NDArray[np.float64]
MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
TABLE_NAME = "attraction.parquet"
# Not an employment proxy: shown in the sensitivity table to show how lenient the hub check is.
POPULATION_REFERENCE = "population (reference, not a proxy)"

COLUMN_NATURE: dict[str, DataNature] = {
    "building_share": DataNature.ESTIMATED,
    "job_poi_share": DataNature.OBSERVED,  # mapped features (category choice is Assumed)
    "employment_score": DataNature.ESTIMATED,
    "opportunity_index": DataNature.ESTIMATED,
    "score_rank": DataNature.ESTIMATED,
    "population": DataNature.ESTIMATED,
}


class AttractionError(ValueError):
    """The employment proxy cannot be computed from the given inputs."""


def building_column(confidence: float) -> str:
    return f"building_area_m2_c{round(confidence * 100):02d}"


def _shares(values: F64, what: str) -> F64:
    total = float(values.sum())
    if total <= 0:
        raise AttractionError(f"{what} is zero in every zone")
    return values / total


def component_shares(
    zones: pl.DataFrame, confidence: float, categories: Sequence[str]
) -> tuple[F64, F64]:
    """Each zone's share of the city's building area and of its job-type POIs."""
    column = building_column(confidence)
    missing = [c for c in [column, *(f"poi_{c}" for c in categories)] if c not in zones.columns]
    if missing:
        raise AttractionError(f"zones table has no column(s) {', '.join(missing)}")
    area = zones[column].to_numpy().astype(np.float64)
    pois = np.zeros(zones.height, dtype=np.float64)
    for category in sorted(categories):
        pois += zones[f"poi_{category}"].to_numpy().astype(np.float64)
    return _shares(area, f"{column}"), _shares(pois, "job-type POIs")


def employment_score(zones: pl.DataFrame, weights: ProxyWeights, categories: Sequence[str]) -> F64:
    """``w_area · area share + w_pois · POI share`` per zone; sums to 1."""
    area, pois = component_shares(zones, weights.building_confidence, categories)
    return weights.building_area * area + weights.job_pois * pois


def score_rank(score: F64) -> npt.NDArray[np.int64]:
    """1-based rank, highest score first; ties go to the lower zone index (deterministic)."""
    order = np.lexsort((np.arange(score.size), -score))
    rank = np.empty(score.size, dtype=np.int64)
    rank[order] = np.arange(1, score.size + 1)
    return rank


# --- validation hubs --------------------------------------------------------------------------


def read_hubs(path: Path) -> list[tuple[str, BaseGeometry]]:
    """Named hub polygons from GeoJSON (WGS84), sorted by name."""
    try:
        collection = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AttractionError(f"validation hubs not found: {path}") from None
    hubs = []
    for feature in collection.get("features", []):
        name = str(feature.get("properties", {}).get("name", "")).strip()
        geometry = shape(feature["geometry"])
        if not name or geometry.is_empty or geometry.geom_type not in ("Polygon", "MultiPolygon"):
            raise AttractionError(f"{path}: every hub needs a name and a polygon")
        hubs.append((name, geometry))
    if len({name for name, _ in hubs}) != len(hubs):
        raise AttractionError(f"{path}: hub names must be unique")
    return sorted(hubs, key=lambda hub: hub[0])


def hub_zones(hubs: Sequence[tuple[str, BaseGeometry]], zones: pl.DataFrame) -> pl.DataFrame:
    """(hub, zone_idx) for every zone whose cell overlaps a hub with a positive area.

    Cells merely touching a hub's edge are left out. Overlap, not centre containment, is used
    because many hubs are smaller than one cell (~0.74 km² at resolution 8).
    """
    cells = [Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(c)]) for c in zones["h3_cell"]]
    tree = shapely.STRtree(cells)
    zone_idx = zones["zone_idx"].to_numpy()
    rows: list[tuple[str, int]] = []
    for name, polygon in hubs:
        for i in sorted(tree.query(polygon, predicate="intersects").tolist()):
            if cells[i].intersection(polygon).area > 0:
                rows.append((name, int(zone_idx[i])))
    return pl.DataFrame(rows, schema={"hub": pl.String, "zone_idx": pl.UInt32}, orient="row")


class HubResult(BaseModel):
    hub: str
    zones: int
    in_pass_rank: int
    in_report_rank: int
    best_rank_share: float  # best (smallest) rank / zone count; 0.01 = top 1 %


class HubCheck(BaseModel):
    """How the ranking of one weighting treats the hub zones."""

    weighting: str
    hub_zones: int
    share_in_pass_rank: float
    share_in_report_rank: float
    concentration: float  # hub zones' share of the score ÷ their share of population
    passed: bool
    hubs: list[HubResult]


def hub_check(
    name: str,
    score: F64,
    population: F64,
    hubs: pl.DataFrame,
    zone_idx: npt.NDArray[np.uint32],
    params: Attraction,
) -> HubCheck:
    """Share of hub zones ranked in the top ``hub_pass_rank`` (and ``hub_report_rank``)."""
    n = score.size
    rank_share = score_rank(score) / n
    position = {int(z): i for i, z in enumerate(zone_idx)}
    results = []
    all_rows: list[int] = []
    for hub in sorted(set(hubs["hub"].to_list())):
        rows = [position[int(z)] for z in hubs.filter(pl.col("hub") == hub)["zone_idx"]]
        all_rows += rows
        shares = rank_share[rows]
        results.append(
            HubResult(
                hub=hub,
                zones=len(rows),
                in_pass_rank=int((shares <= params.hub_pass_rank).sum()),
                in_report_rank=int((shares <= params.hub_report_rank).sum()),
                best_rank_share=float(shares.min()),
            )
        )
    unique = sorted(set(all_rows))  # a zone overlapping two hubs counts once
    if not unique:
        raise AttractionError("no zone overlaps any validation hub")
    in_pass = float(np.mean(rank_share[unique] <= params.hub_pass_rank))
    pop_share = float(population[unique].sum() / population.sum())
    return HubCheck(
        weighting=name,
        hub_zones=len(unique),
        share_in_pass_rank=in_pass,
        share_in_report_rank=float(np.mean(rank_share[unique] <= params.hub_report_rank)),
        concentration=float(score[unique].sum()) / pop_share if pop_share > 0 else float("inf"),
        passed=in_pass >= params.hub_pass_share,
        hubs=results,
    )


# --- build ------------------------------------------------------------------------------------


class SensitivityRow(BaseModel):
    weighting: str
    building_area: float | None
    job_pois: float | None
    building_confidence: float | None
    rank_correlation: float | None  # Spearman against the baseline; None if one is constant
    top_decile_overlap: float  # share of the baseline's top 10 % zones also in this top 10 %
    hub_check: HubCheck | None


@dataclass
class AttractionBuild:
    table: pl.DataFrame
    sensitivity: list[SensitivityRow]
    hubs_found: list[str]


def _top_decile(score: F64) -> set[int]:
    rank = score_rank(score)
    return set(np.flatnonzero(rank <= max(1, score.size // 10)).tolist())


def build_attraction(
    zones: pl.DataFrame, params: Attraction, hubs: Sequence[tuple[str, BaseGeometry]] | None
) -> AttractionBuild:
    zones = zones.sort("zone_idx")
    base = params.baseline
    area, pois = component_shares(zones, base.building_confidence, params.job_poi_categories)
    score = base.building_area * area + base.job_pois * pois
    population = zones["population"].to_numpy().astype(np.float64)
    zone_idx = zones["zone_idx"].to_numpy()
    table = zones.select("zone_idx", "h3_cell", "lat", "lon").with_columns(
        pl.Series("building_share", area),
        pl.Series("job_poi_share", pois),
        pl.Series("employment_score", score),
        pl.Series("opportunity_index", score * params.opportunity_index_total),
        pl.Series("score_rank", score_rank(score)).cast(pl.UInt32),
        pl.Series("population", population),
    )

    hub_table = hub_zones(hubs, zones) if hubs else None
    found = sorted(set(hub_table["hub"].to_list())) if hub_table is not None else []
    baseline_top = _top_decile(score)
    rows = []
    variants: list[tuple[str, ProxyWeights | None, F64]] = [
        (w.name, w, employment_score(zones, w, params.job_poi_categories))
        for w in (base, *params.sensitivity)
    ]
    variants.append((POPULATION_REFERENCE, None, _shares(population, "population")))
    for name, weights, values in variants:
        constant = np.ptp(score) == 0 or np.ptp(values) == 0
        correlation = None if constant else float(spearmanr(score, values).statistic)
        rows.append(
            SensitivityRow(
                weighting=name,
                building_area=weights.building_area if weights else None,
                job_pois=weights.job_pois if weights else None,
                building_confidence=weights.building_confidence if weights else None,
                rank_correlation=correlation,
                top_decile_overlap=len(baseline_top & _top_decile(values)) / len(baseline_top),
                hub_check=(
                    hub_check(name, values, population, hub_table, zone_idx, params)
                    if hub_table is not None and hub_table.height
                    else None
                ),
            )
        )
    return AttractionBuild(table=table, sensitivity=rows, hubs_found=found)


class AttractionManifest(BaseModel):
    city: str
    builder_version: str
    zones_manifest_sha256: str
    hubs_sha256: str | None
    hubs_missing: list[str]
    params: Attraction
    column_nature: dict[str, DataNature]
    sensitivity: list[SensitivityRow]
    outputs: dict[str, str]


def write_attraction(
    build: AttractionBuild,
    out_dir: Path,
    *,
    city: str,
    params: Attraction,
    zones_manifest_sha256: str,
    hubs_path: Path | None,
    hub_names: Sequence[str],
) -> AttractionManifest:
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    path = staging / TABLE_NAME
    build.table.write_parquet(path, compression="zstd", statistics=True)
    manifest = AttractionManifest(
        city=city,
        builder_version=__version__,
        zones_manifest_sha256=zones_manifest_sha256,
        hubs_sha256=sha256_file(hubs_path) if hubs_path else None,
        hubs_missing=sorted(set(hub_names) - set(build.hubs_found)),
        params=params,
        column_nature=COLUMN_NATURE,
        sensitivity=build.sensitivity,
        outputs={TABLE_NAME: sha256_file(path)},
    )
    (staging / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (staging / REPORT_NAME).write_text(
        report(manifest, build.table), encoding="utf-8", newline="\n"
    )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    rename_with_retry(staging, out_dir)
    return manifest


# --- report -----------------------------------------------------------------------------------


def _pct(value: float) -> str:
    return f"{value:.0%}"


def _corr(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def report(m: AttractionManifest, table: pl.DataFrame) -> str:
    p = m.params
    b = p.baseline
    base_row = m.sensitivity[0]
    lines = [
        f"# Employment proxy — `{m.city}`",
        "",
        f"Builder {m.builder_version} · {table.height:,} zones",
        "",
        "## Formula (Estimated; weights Assumed)",
        "",
        "`employment_score = "
        f"{b.building_area:g} x building-area share + {b.job_pois:g} x job-POI share`",
        "",
        f"- Building area: Open Buildings footprints, confidence ≥ {b.building_confidence:g} "
        "(Estimated; all uses, no heights).",
        "- Job-type POIs (OpenStreetMap, Observed; categories Assumed): "
        + ", ".join(sorted(p.job_poi_categories))
        + ".",
        "- Each part is a share of the city total, so the score is a share of the city's "
        "estimated employment and sums to 1. Transit stops are not an input (no circularity).",
        f"- `opportunity_index` = score x {p.opportunity_index_total:,} (Assumed base): an "
        "**Estimated Opportunity Index**, not a count of jobs.",
        "",
    ]
    if base_row.hub_check is None:
        lines += ["## Hub check", "", "No validation hubs configured.", ""]
    else:
        check = base_row.hub_check
        verdict = "PASSED" if check.passed else "FAILED"
        lines += [
            "## Hub check",
            "",
            f"**{verdict}**: {_pct(check.share_in_pass_rank)} of {check.hub_zones} hub zones rank "
            f"in the top {_pct(p.hub_pass_rank)} of zones (rule: ≥ {_pct(p.hub_pass_share)}). "
            f"Top {_pct(p.hub_report_rank)}: {_pct(check.share_in_report_rank)}. Hub zones hold "
            f"{check.concentration:.2f}x their share of population.",
            "",
            "Hub zones are the cells overlapping each hand-drawn polygon.",
            "",
            f"| Hub | Zones | In top {_pct(p.hub_pass_rank)} | In top {_pct(p.hub_report_rank)} "
            "| Best rank |",
            "|---|---:|---:|---:|---:|",
            *(
                f"| {h.hub} | {h.zones} | {h.in_pass_rank} | {h.in_report_rank} | "
                f"top {h.best_rank_share:.1%} |"
                for h in check.hubs
            ),
            "",
        ]
        if m.hubs_missing:
            lines += [f"Hubs overlapping no zone: {', '.join(m.hubs_missing)}.", ""]
    lines += [
        "## Sensitivity (weights Assumed)",
        "",
        "Rank correlation (Spearman) and top-10% overlap are against the baseline. The "
        "population row is not an employment proxy: it shows how much of the hub check a map "
        "of residents alone would pass.",
        "",
        f"| Weighting | Area | POIs | Confidence | Rank corr. | Top-10% overlap "
        f"| Hubs in top {_pct(p.hub_pass_rank)} | Hubs in top {_pct(p.hub_report_rank)} "
        "| Concentration |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in m.sensitivity:
        c = row.hub_check

        def cell(v: float | None) -> str:
            return "-" if v is None else f"{v:g}"

        hub_cells = (
            f"{_pct(c.share_in_pass_rank)} | {_pct(c.share_in_report_rank)} | "
            f"{c.concentration:.2f}x"
            if c
            else "- | - | -"
        )
        lines.append(
            f"| {row.weighting} | {cell(row.building_area)} | {cell(row.job_pois)} | "
            f"{cell(row.building_confidence)} | {_corr(row.rank_correlation)} | "
            f"{_pct(row.top_decile_overlap)} | {hub_cells} |"
        )
    top = table.sort("score_rank").head(10)
    lines += [
        "",
        "## Top 10 zones (Estimated)",
        "",
        "| Rank | H3 cell | Lat, lon | Score | Opportunity index |",
        "|---:|---|---|---:|---:|",
        *(
            f"| {r['score_rank']} | `{r['h3_cell']}` | {r['lat']:.4f}, {r['lon']:.4f} | "
            f"{r['employment_score']:.4%} | {r['opportunity_index']:,.0f} |"
            for r in top.iter_rows(named=True)
        ),
        "",
        "## Column labels",
        "",
        *(f"- `{column}`: {nature.value}" for column, nature in m.column_nature.items()),
        "",
    ]
    return "\n".join(lines)
