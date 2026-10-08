"""Compare two networks: a scenario against the baseline, or two scenarios (PRD §31).

Nothing is recomputed: the comparison reads the accessibility summaries, zone accessibility and
travel-time matrices that the runs already wrote, so it is cheap and always describes exactly
the cached results named in ``comparison.json``. A scenario is found by its cache key under the
current code and data; if it has not been run, the comparison says so instead of guessing.

Outputs (``comparisons/<a>__vs__<b>/``): ``comparison.md``, ``metrics.parquet``,
``zone_deltas.parquet`` (every zone x percentile x threshold), ``zone_deltas.geoparquet`` (one
hexagon per zone, for QGIS), ``delta_map.png`` and ``comparison.json``. All values are
Simulated; job counts behind them are Estimated.

Waiting, transfers and crowding (PRD §31) come with assignment in Phase 6: the travel-time
matrix stores door-to-door times only.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")  # files only, no display

import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
import polars as pl
from matplotlib.collections import PolyCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from pydantic import BaseModel

from glacies import __version__
from glacies.analytics.report import (
    INK,
    INK_MUTED,
    SURFACE,
    Block,
    Bullets,
    Heading,
    Image,
    Para,
    Table,
    hexagons,
    to_markdown,
    write_geoparquet,
)
from glacies.cities import CityConfig
from glacies.config import Settings
from glacies.fsutil import rename_with_retry
from glacies.pipeline import PipelineError, city_dir
from glacies.provenance import DataNature, sha256_file
from glacies.scenario.runner import (
    MANIFEST_NAME,
    RUN_NAME,
    EngineVersions,
    RunRecord,
    baseline_inputs,
    cache_key,
    engine_versions,
    result_dir,
)
from glacies.scenario.schema import Scenario, load_scenario

BASELINE = "baseline"
COMPARISONS_DIR = "comparisons"
KEYS = ["zone_idx", "percentile", "threshold_min"]
# Diverging blue (gain) / red (loss) arms with a neutral grey midpoint, from the dataviz
# reference palette; each arm validated as an ordinal ramp on the light surface.
GAIN = ("#86b6ef", "#3987e5", "#184f95")
LOSS = ("#f19d99", "#e34948", "#a3292a")
NO_CHANGE = "#f0efec"
ROUTE_LINE = INK_MUTED  # context, not data: neutral ink
DELTA_BREAKS = (0.0005, 0.002)  # 0.05 and 0.2 percentage points, as fractions
TOP_ZONES = 10


class ComparisonError(PipelineError):
    """A side of the comparison has no results to read."""


@dataclass(frozen=True)
class Side:
    label: str
    accessibility: Path
    tt_matrix: Path
    transit: Path
    run: RunRecord | None = None
    scenario: Scenario | None = None


class SideRecord(BaseModel):
    label: str
    cache_key: str | None
    accessibility_manifest_sha256: str
    tt_matrix_manifest_sha256: str


class ComparisonManifest(BaseModel):
    city: str
    builder_version: str
    a: SideRecord
    b: SideRecord
    headline_percentile: int
    headline_threshold_min: int
    nature: DataNature
    zones_up: int
    zones_down: int
    direction_check: str
    outputs: dict[str, str]


@dataclass(frozen=True)
class Comparison:
    manifest: ComparisonManifest
    out_dir: Path
    metrics: pl.DataFrame


def resolve_side(
    settings: Settings, config: CityConfig, ref: str, engine: EngineVersions | None = None
) -> Side:
    """``baseline`` or a scenario file whose result exists for the current code and data."""
    base = city_dir(settings, config)
    if ref == BASELINE:
        side = Side(
            BASELINE,
            base / "accessibility" / BASELINE,
            base / "tt_matrix" / BASELINE,
            base / "transit",
        )
    else:
        scenario = load_scenario(Path(ref))
        key = cache_key(
            scenario,
            config,
            baseline_inputs(base),
            engine or engine_versions(),
            settings.random_seed,
        )
        directory = result_dir(base, key)
        if not (directory / RUN_NAME).is_file():
            raise ComparisonError(
                f"{scenario.scenario_id} has no result for the current code and data; "
                f"run `glacies scenario run {ref}` first"
            )
        run = RunRecord.model_validate_json((directory / RUN_NAME).read_text(encoding="utf-8"))
        side = Side(
            scenario.scenario_id,
            directory / "accessibility",
            directory / "tt_matrix",
            directory / "transit",
            run=run,
            scenario=scenario,
        )
    for directory in (side.accessibility, side.tt_matrix, side.transit):
        if not (directory / MANIFEST_NAME).is_file():
            raise ComparisonError(f"{side.label}: missing {directory / MANIFEST_NAME}")
    return side


def compare(
    settings: Settings,
    config: CityConfig,
    a_ref: str,
    b_ref: str,
    *,
    engine: EngineVersions | None = None,
) -> Comparison:
    """Write the comparison of B against A; ``engine`` overrides the version used to find runs."""
    a = resolve_side(settings, config, a_ref, engine)
    b = resolve_side(settings, config, b_ref, engine)
    if a.label == b.label:
        raise ComparisonError("compare two different networks")
    base = city_dir(settings, config)
    s = config.accessibility
    p, t = s.headline_percentile, s.headline_threshold_min
    zones = pl.read_parquet(base / "zones" / "zones.parquet").sort("zone_idx")

    deltas = _zone_deltas(a, b, zones)
    head = deltas.filter((pl.col("percentile") == p) & (pl.col("threshold_min") == t))
    up = int((head["est_jobs_share_delta"] > 0).sum())
    down = int((head["est_jobs_share_delta"] < 0).sum())
    direction = _direction_check(a, b, deltas)
    metrics = _metrics(a, b, zones, config, up, down)

    out_dir = base / COMPARISONS_DIR / f"{a.label}__vs__{b.label}"
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    metrics.write_parquet(staging / "metrics.parquet")
    deltas.write_parquet(staging / "zone_deltas.parquet", compression="zstd")
    wide = _wide(deltas, zones, p, s.thresholds_min, t)
    write_geoparquet(wide, wide["h3_cell"].to_list(), staging / "zone_deltas.geoparquet")
    _draw_delta_map(
        staging / "delta_map.png",
        head,
        _route_lines(a, b),
        f"Change in estimated jobs reachable within {t} min",
        f"{b.label} vs {a.label}: percentage points of the city's estimated jobs, p{p} "
        f"(Simulated); {up + down:,} zones changed",
        config,
    )
    blocks = _report(a, b, metrics, head, direction, config)
    (staging / "comparison.md").write_text(to_markdown(blocks), encoding="utf-8", newline="\n")

    manifest = ComparisonManifest(
        city=config.city.id,
        builder_version=__version__,
        a=_side_record(a),
        b=_side_record(b),
        headline_percentile=p,
        headline_threshold_min=t,
        nature=DataNature.SIMULATED,
        zones_up=up,
        zones_down=down,
        direction_check=direction,
        outputs={f.name: sha256_file(f) for f in sorted(staging.iterdir())},
    )
    (staging / "comparison.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    rename_with_retry(staging, out_dir)
    return Comparison(manifest=manifest, out_dir=out_dir, metrics=metrics)


def _side_record(side: Side) -> SideRecord:
    return SideRecord(
        label=side.label,
        cache_key=side.run.cache_key if side.run else None,
        accessibility_manifest_sha256=sha256_file(side.accessibility / MANIFEST_NAME),
        tt_matrix_manifest_sha256=sha256_file(side.tt_matrix / MANIFEST_NAME),
    )


def _zone_deltas(a: Side, b: Side, zones: pl.DataFrame) -> pl.DataFrame:
    columns = ["est_jobs_share", "population_share"]
    left = pl.read_parquet(a.accessibility / "accessibility.parquet")
    right = pl.read_parquet(b.accessibility / "accessibility.parquet")
    joined = left.select(*KEYS, "edge_zone", *columns).join(
        right.select(*KEYS, *columns), on=KEYS, suffix="_b", how="full", coalesce=True
    )
    if joined.height != left.height or joined.height != right.height:
        raise ComparisonError("the two results cover different zones or settings")
    return (
        joined.rename({c: f"{c}_a" for c in columns})
        .with_columns((pl.col(f"{c}_b") - pl.col(f"{c}_a")).alias(f"{c}_delta") for c in columns)
        .join(zones.select("zone_idx", "h3_cell", "lat", "lon", "population"), on="zone_idx")
        .select(
            *KEYS,
            "h3_cell",
            "lat",
            "lon",
            "population",
            "edge_zone",
            *(f"{c}_{s}" for c in columns for s in ("a", "b", "delta")),
        )
        .sort(KEYS)
    )


def _direction_check(a: Side, b: Side, deltas: pl.DataFrame) -> str:
    """Added service can never lower access and removed service never raise it."""
    if a.run is not None or b.run is None:
        return "not checked (needs the baseline as A and a scenario as B)"
    removed = sum(c.trips_removed for c in b.run.changes)
    added = sum(c.trips_added for c in b.run.changes)
    delta = deltas["est_jobs_share_delta"]
    if removed == 0:
        wrong, rule = int((delta < 0).sum()), "trips only added: no value may fall"
    elif added == 0:
        wrong, rule = int((delta > 0).sum()), "trips only removed: no value may rise"
    else:
        return "not checked (trips both added and removed)"
    verdict = "passed" if wrong == 0 else f"FAILED: {wrong} values moved the wrong way"
    return f"{verdict} ({rule}; {deltas.height:,} zone x percentile x threshold values)"


def _summary(side: Side) -> pl.DataFrame:
    return pl.read_parquet(side.accessibility / "summary.parquet").filter(
        pl.col("scope") == "all zones"
    )


def _pick(summary: pl.DataFrame, measure: str, p: int, t: int, column: str) -> float:
    row = summary.filter(
        (pl.col("measure") == measure)
        & (pl.col("percentile") == p)
        & (pl.col("threshold_min") == t)
    )
    return float(row[column][0])


def _travel(side: Side, column: str) -> pl.LazyFrame:
    return pl.scan_parquet(side.tt_matrix / "part-*.parquet").select(
        "origin_zone", "dest_zone", pl.col(column).alias("seconds")
    )


def _metrics(
    a: Side, b: Side, zones: pl.DataFrame, config: CityConfig, up: int, down: int
) -> pl.DataFrame:
    s = config.accessibility
    p, t = s.headline_percentile, s.headline_threshold_min
    sa, sb = _summary(a), _summary(b)
    rows: list[tuple[str, float, float, str, str]] = []

    def add(name: str, va: float, vb: float, unit: str, nature: DataNature) -> None:
        rows.append((name, va, vb, unit, nature.value))

    for threshold in s.thresholds_min:
        add(
            f"Estimated jobs reachable within {threshold} min (p{p}, population-weighted)",
            _pick(sa, "est_jobs", p, threshold, "population_weighted_mean"),
            _pick(sb, "est_jobs", p, threshold, "population_weighted_mean"),
            "share",
            DataNature.SIMULATED,
        )
    add(
        f"Population reachable within {t} min (p{p}, population-weighted)",
        _pick(sa, "population", p, t, "population_weighted_mean"),
        _pick(sb, "population", p, t, "population_weighted_mean"),
        "share",
        DataNature.SIMULATED,
    )
    add(
        f"Population reaching under 1 % of estimated jobs within {t} min",
        _pick(sa, "est_jobs", p, t, "population_share_below_1pct"),
        _pick(sb, "est_jobs", p, t, "population_share_below_1pct"),
        "share",
        DataNature.SIMULATED,
    )
    add(
        f"Gini of estimated-job access within {t} min (0 equal, 1 unequal)",
        _pick(sa, "est_jobs", p, t, "gini"),
        _pick(sb, "est_jobs", p, t, "gini"),
        "index",
        DataNature.SIMULATED,
    )

    column = f"p{p}_s"
    ta, tb = _travel(a, column), _travel(b, column)
    for limit in (s.thresholds_min[-1], s.max_travel_time_min):
        count = [
            int(f.filter(pl.col("seconds") <= limit * 60).select(pl.len()).collect().item())
            for f in (ta, tb)
        ]
        add(
            f"Zone pairs connected within {limit} min (p{p})",
            count[0],
            count[1],
            "count",
            DataNature.SIMULATED,
        )
    weights = zones.select(pl.col("zone_idx").alias("origin_zone"), "population").lazy()
    both = (
        ta.drop_nulls("seconds")
        .join(tb.drop_nulls("seconds"), on=["origin_zone", "dest_zone"], suffix="_b")
        .join(weights, on="origin_zone")
        .select(
            (pl.col("seconds") * pl.col("population")).sum() / pl.col("population").sum(),
            (pl.col("seconds_b") * pl.col("population")).sum() / pl.col("population").sum(),
        )
        .collect()
    )
    add(
        f"Mean door-to-door time over pairs connected in both (p{p}, by origin population)",
        float(both.item(0, 0)) / 60,
        float(both.item(0, 1)) / 60,
        "minutes",
        DataNature.SIMULATED,
    )
    trips = [
        json.loads((side.transit / MANIFEST_NAME).read_text(encoding="utf-8"))["row_counts"][
            "trips"
        ]
        for side in (a, b)
    ]
    add("Trips in the service-day timetable", trips[0], trips[1], "count", DataNature.SIMULATED)
    add(
        f"Zones gaining access at the headline ({t} min, p{p})",
        0,
        up,
        "count",
        DataNature.SIMULATED,
    )
    add(
        f"Zones losing access at the headline ({t} min, p{p})",
        0,
        down,
        "count",
        DataNature.SIMULATED,
    )
    return pl.DataFrame(
        rows,
        schema={
            "metric": pl.String,
            "a": pl.Float64,
            "b": pl.Float64,
            "unit": pl.String,
            "nature": pl.String,
        },
        orient="row",
    ).with_columns((pl.col("b") - pl.col("a")).alias("delta"))


def _wide(
    deltas: pl.DataFrame, zones: pl.DataFrame, p: int, thresholds: list[int], t: int
) -> pl.DataFrame:
    """One row per zone for QGIS: the headline values and the change at every threshold."""
    at = deltas.filter(pl.col("percentile") == p)
    frame = zones.select("zone_idx", "h3_cell", "population")
    head = at.filter(pl.col("threshold_min") == t).select(
        "zone_idx",
        "edge_zone",
        pl.col("est_jobs_share_a").alias(f"jobs_{t}min_a"),
        pl.col("est_jobs_share_b").alias(f"jobs_{t}min_b"),
    )
    frame = frame.join(head, on="zone_idx", how="left")
    for threshold in thresholds:
        frame = frame.join(
            at.filter(pl.col("threshold_min") == threshold).select(
                "zone_idx", pl.col("est_jobs_share_delta").alias(f"jobs_{threshold}min_delta")
            ),
            on="zone_idx",
            how="left",
        )
    return frame.sort("zone_idx")


def _colour(delta: float) -> str:
    if delta == 0:
        return NO_CHANGE
    arm = GAIN if delta > 0 else LOSS
    return arm[int(np.searchsorted(DELTA_BREAKS, abs(delta), side="right"))]


def _route_lines(a: Side, b: Side) -> list[npt.NDArray[np.float64]]:
    """Stop-to-stop lines of every route a scenario touches, from the network that has it."""
    ids = sorted({c.route_id for side in (a, b) if side.run for c in side.run.changes})
    lines: list[npt.NDArray[np.float64]] = []
    for side in (a, b):
        routes = pl.read_parquet(side.transit / "routes.parquet")
        chosen = routes.filter(pl.col("source_route_id").is_in(ids))["route_idx"]
        if chosen.is_empty():
            continue
        patterns = pl.read_parquet(side.transit / "patterns.parquet").filter(
            pl.col("route_idx").is_in(chosen.implode())
        )
        stops = pl.read_parquet(side.transit / "stops.parquet", columns=["stop_idx", "lat", "lon"])
        points = (
            pl.read_parquet(side.transit / "pattern_stops.parquet")
            .join(patterns.select("pattern_idx"), on="pattern_idx")
            .join(stops, on="stop_idx")
            .sort("pattern_idx", "position")
        )
        for (_,), part in points.group_by(["pattern_idx"], maintain_order=True):
            lines.append(part.select("lon", "lat").to_numpy())
    return lines


def _draw_delta_map(
    path: Path,
    head: pl.DataFrame,
    lines: list[npt.NDArray[np.float64]],
    title: str,
    subtitle: str,
    config: CityConfig,
) -> None:
    """Changed zones and the changed routes, zoomed to them; unchanged zones as context."""
    changed = head.filter(pl.col("est_jobs_share_delta") != 0)
    lon = np.concatenate([changed["lon"].to_numpy(), *(line[:, 0] for line in lines)])
    lat = np.concatenate([changed["lat"].to_numpy(), *(line[:, 1] for line in lines)])
    if lon.size:
        pad = 0.02  # about 2 km of context
        min_lon, max_lon = float(lon.min()) - pad, float(lon.max()) + pad
        min_lat, max_lat = float(lat.min()) - pad, float(lat.max()) + pad
    else:
        min_lon, min_lat, max_lon, max_lat = config.city.bbox
    view = head.filter(
        pl.col("lon").is_between(min_lon - 0.01, max_lon + 0.01)
        & pl.col("lat").is_between(min_lat - 0.01, max_lat + 0.01)
    )
    shrink = float(np.cos(np.radians((min_lat + max_lat) / 2)))
    # Size the figure to the map: 8 in wide, the map takes 73 % of it; 0.8 in for the titles.
    map_h = 8 * 0.73 * (max_lat - min_lat) / ((max_lon - min_lon) * shrink)
    height = min(max(map_h + 0.8, 4.0), 11.0)
    fig, ax = plt.subplots(figsize=(8, height), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.add_collection(
        PolyCollection(
            hexagons(view["h3_cell"].to_list()),
            facecolors=[_colour(d) for d in view["est_jobs_share_delta"].to_list()],
            edgecolors=SURFACE,
            linewidths=0.3,
        )
    )
    for line in lines:
        ax.plot(line[:, 0], line[:, 1], color=ROUTE_LINE, linewidth=1.0)
    ax.set_xlim(min_lon, max_lon)
    ax.set_ylim(min_lat, max_lat)
    ax.set_aspect(1 / shrink)
    ax.set_axis_off()
    ax.set_anchor("N")
    pp = [f"{x * 100:g}" for x in DELTA_BREAKS]
    labels = [f"under {pp[0]} pp", f"{pp[0]} - {pp[1]} pp", f"{pp[1]} pp or more"]
    handles: list[Patch | Line2D] = [
        Patch(facecolor=c, label=f"gain {lab}")
        for c, lab in zip(reversed(GAIN), reversed(labels), strict=True)
    ]
    handles.append(Patch(facecolor=NO_CHANGE, label="no change"))
    handles += [
        Patch(facecolor=c, label=f"loss {lab}") for c, lab in zip(LOSS, labels, strict=True)
    ]
    if lines:
        handles.append(Line2D([], [], color=ROUTE_LINE, linewidth=1.0, label="changed routes"))
    ax.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(1.0, 1.0),
        frameon=False,
        fontsize=8,
        labelcolor=INK,
    )
    top = 1 - 0.75 / height
    fig.text(0.02, 1 - 0.3 / height, title, ha="left", va="center", fontsize=12, color=INK)
    fig.text(
        0.02, 1 - 0.58 / height, subtitle, ha="left", va="center", fontsize=8.5, color=INK_MUTED
    )
    fig.subplots_adjust(left=0.01, right=0.74, top=top, bottom=0.01)
    fig.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


def format_value(value: float, unit: str) -> str:
    if unit == "share":
        return f"{value * 100:.4f} %"
    if unit == "minutes":
        return f"{value:.2f}"
    if unit == "index":
        return f"{value:.4f}"
    return f"{value:,.0f}"


def format_delta(value: float, unit: str) -> str:
    decimals = {"share": 6, "minutes": 2, "index": 4}.get(unit, 0)
    value = round(value, decimals) + 0.0  # + 0.0 turns -0.0 into 0.0
    if unit == "share":
        return f"{value * 100:+.4f} pp"
    if unit == "minutes":
        return f"{value:+.2f}"
    if unit == "index":
        return f"{value:+.4f}"
    return f"{value:+,.0f}"


def _report(
    a: Side,
    b: Side,
    metrics: pl.DataFrame,
    head: pl.DataFrame,
    direction: str,
    config: CityConfig,
) -> list[Block]:
    s = config.accessibility
    blocks: list[Block] = [
        Heading(1, f"{b.label} vs {a.label}"),
        Para(
            f"City `{config.city.id}`. A = `{a.label}`, B = `{b.label}`. Every value is "
            "**Simulated** from the cached runs named in `comparison.json`; job counts behind "
            "the shares are **Estimated** (employment proxy), not observed employment."
        ),
    ]
    for side in (a, b):
        if side.scenario is not None and side.run is not None:
            changes = "; ".join(
                f"{c.type} {c.route_id} (-{c.trips_removed:,} / +{c.trips_added:,} trips)"
                for c in side.run.changes
            )
            blocks += [
                Heading(2, f"Scenario `{side.label}`"),
                Bullets(
                    [
                        f"Title: {side.scenario.title}",
                        f"Changes: {changes}",
                        "Expected change (planner): "
                        + (side.scenario.expected_change or "not stated"),
                        f"Run: `{side.run.cache_key[:12]}`, {side.run.mode}, commit "
                        f"`{(side.run.engine.git_commit or 'unknown')[:7]}`",
                    ]
                ),
            ]
    blocks += [
        Heading(2, "Metrics"),
        Table(
            ["Metric", "A", "B", "Change"],
            [
                [m, format_value(va, u), format_value(vb, u), format_delta(d, u)]
                for m, va, vb, u, d in metrics.select(
                    "metric", "a", "b", "unit", "delta"
                ).iter_rows()
            ],
            align_right=[False, True, True, True],
        ),
        Para(
            "PRD §31 also lists average waiting, transfers and crowding. They need per-journey "
            "results and passenger demand, which arrive with assignment (Phase 6); the "
            "travel-time matrix stores door-to-door times only. The mean door-to-door time is "
            "taken over the pairs connected in both networks, so its A value can differ "
            "slightly between comparisons. The two zone counts compare B against A (A's column "
            "is 0 by definition)."
        ),
        Heading(2, "Direction check"),
        Para(direction),
        Heading(2, "Where access changes"),
        Image("delta_map.png", "Map of zones whose access changed"),
    ]
    for title, frame in (
        (
            "Largest gains",
            head.filter(pl.col("est_jobs_share_delta") > 0).sort(
                "est_jobs_share_delta", descending=True
            ),
        ),
        (
            "Largest losses",
            head.filter(pl.col("est_jobs_share_delta") < 0).sort("est_jobs_share_delta"),
        ),
    ):
        blocks.append(
            Heading(3, f"{title} ({s.headline_threshold_min} min, p{s.headline_percentile})")
        )
        if frame.height == 0:
            blocks.append(Para("None."))
            continue
        blocks.append(
            Table(
                ["Zone (H3)", "Lat, lon", "Population (Estimated)", "A", "B", "Change"],
                [
                    [
                        f"`{r['h3_cell']}`",
                        f"{r['lat']:.4f}, {r['lon']:.4f}",
                        f"{r['population']:,.0f}",
                        f"{r['est_jobs_share_a'] * 100:.3f} %",
                        f"{r['est_jobs_share_b'] * 100:.3f} %",
                        f"{r['est_jobs_share_delta'] * 100:+.3f} pp",
                    ]
                    for r in frame.head(TOP_ZONES).iter_rows(named=True)
                ],
                align_right=[False, False, True, True, True, True],
            )
        )
    blocks += [
        Heading(2, "Files"),
        Bullets(
            [
                "`zone_deltas.parquet`: every zone x percentile x threshold, A, B and change.",
                "`zone_deltas.geoparquet`: one hexagon per zone for QGIS (headline A/B and the "
                "change at each threshold).",
                "`metrics.parquet`: the table above.",
            ]
        ),
    ]
    return blocks
