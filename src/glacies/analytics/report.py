"""Accessibility report: static maps, Markdown/HTML report and a GeoParquet for QGIS (Phase 3 M4).

Everything here presents numbers computed earlier (zones, employment proxy, travel-time matrix,
accessibility); nothing is recomputed. The report states the provenance label of every quantity
(Observed / Estimated / Simulated / Assumed), as the phase's definition of done requires.

Maps use one blue ramp, light to dark, with fixed labelled classes: shares are very skewed
(most zones near zero, the centre near a fifth of the city), so a continuous scale would hide
the periphery. Zones with nothing to show are neutral grey. The study-area edge band is drawn
as a dashed line, so flagged edge zones are visible without relying on colour. Every map has
its numbers in a table next to it.
"""

from __future__ import annotations

import base64
import html
import json
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import h3
import matplotlib as mpl

mpl.use("Agg")  # files only, no display

import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from matplotlib.collections import PolyCollection
from matplotlib.patches import Patch, Rectangle
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from glacies.analytics.accessibility import (
    METRES_PER_DEGREE_LAT,
    METRES_PER_DEGREE_LON,
)
from glacies.cities import CityConfig

F64 = npt.NDArray[np.float64]
Bbox = tuple[float, float, float, float]

# Reference sequential ramp (dataviz skill, palette.md): blue steps 100, 200, ..., 700.
RAMP = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")
NONE_FILL = "#e4e3df"  # neutral grey: nothing to show
SURFACE = "#fcfcfb"
INK = "#1f1f1e"
INK_MUTED = "#6b6a66"
HUB_LINE = "#e34948"  # outline only, labelled in the legend

SHARE_BREAKS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.10)  # of the city total
GAP_BREAKS = (0.0005, 0.001, 0.0025, 0.005, 0.01, 0.02)  # percentage points as fractions
RELATIVE_BREAKS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)  # multiples of the average zone


# --- document blocks, rendered to Markdown and HTML -------------------------------------------


@dataclass(frozen=True)
class Heading:
    level: int
    text: str


@dataclass(frozen=True)
class Para:
    text: str


@dataclass(frozen=True)
class Bullets:
    items: Sequence[str]


@dataclass(frozen=True)
class Table:
    header: Sequence[str]
    rows: Sequence[Sequence[str]]
    align_right: Sequence[bool] = ()


@dataclass(frozen=True)
class Image:
    file: str
    alt: str


Block = Heading | Para | Bullets | Table | Image


def to_markdown(blocks: Sequence[Block]) -> str:
    out: list[str] = []
    for b in blocks:
        if isinstance(b, Heading):
            out += ["#" * b.level + " " + b.text, ""]
        elif isinstance(b, Para):
            out += [b.text, ""]
        elif isinstance(b, Bullets):
            out += [*(f"- {item}" for item in b.items), ""]
        elif isinstance(b, Table):
            right = list(b.align_right) or [False] * len(b.header)
            out.append("| " + " | ".join(b.header) + " |")
            out.append("|" + "|".join("---:" if r else "---" for r in right) + "|")
            out += ["| " + " | ".join(row) + " |" for row in b.rows]
            out.append("")
        else:
            out += [f"![{b.alt}]({b.file})", ""]
    return "\n".join(out)


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)


def to_html(blocks: Sequence[Block], title: str, images: Path) -> str:
    """Self-contained page: images are embedded so the file can be shared on its own."""
    body: list[str] = []
    for b in blocks:
        if isinstance(b, Heading):
            body.append(f"<h{b.level}>{_inline(b.text)}</h{b.level}>")
        elif isinstance(b, Para):
            body.append(f"<p>{_inline(b.text)}</p>")
        elif isinstance(b, Bullets):
            body.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in b.items) + "</ul>")
        elif isinstance(b, Table):
            right = list(b.align_right) or [False] * len(b.header)
            head = "".join(
                f'<th class="{"r" if r else ""}">{_inline(h)}</th>'
                for h, r in zip(b.header, right, strict=True)
            )
            rows = "".join(
                "<tr>"
                + "".join(
                    f'<td class="{"r" if r else ""}">{_inline(c)}</td>'
                    for c, r in zip(row, right, strict=True)
                )
                + "</tr>"
                for row in b.rows
            )
            body.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
        else:
            data = base64.b64encode((images / b.file).read_bytes()).decode("ascii")
            body.append(
                f'<figure><img src="data:image/png;base64,{data}" alt="{html.escape(b.alt)}">'
                f"<figcaption>{_inline(b.alt)}</figcaption></figure>"
            )
    style = (
        "body{font-family:system-ui,sans-serif;max-width:960px;margin:0 auto;padding:16px;"
        f"color:{INK};background:{SURFACE};line-height:1.5}}"
        "table{border-collapse:collapse;margin:8px 0 16px;font-size:14px}"
        "th,td{border-bottom:1px solid #dddcd8;padding:4px 10px;text-align:left}"
        "th.r,td.r{text-align:right;font-variant-numeric:tabular-nums}"
        "img{max-width:100%;height:auto}figure{margin:16px 0}"
        f"figcaption{{color:{INK_MUTED};font-size:14px}}"
        "code{background:#efeeea;padding:0 4px;border-radius:3px}"
    )
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{style}</style></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )


# --- maps -------------------------------------------------------------------------------------


def hexagons(cells: Sequence[str]) -> list[F64]:
    """Cell outlines as (lon, lat) vertex arrays."""
    return [np.array([(lon, lat) for lat, lon in h3.cell_to_boundary(c)]) for c in cells]


def classify(values: F64, breaks: Sequence[float]) -> npt.NDArray[np.int64]:
    """Class index per value: -1 for zero (nothing to show), else 0..len(breaks)."""
    classes = np.searchsorted(np.asarray(breaks), values, side="right").astype(np.int64)
    classes[values <= 0] = -1
    return classes


def class_labels(breaks: Sequence[float], fmt: str) -> list[str]:
    edges = [fmt.format(b) for b in breaks]
    return [f"< {edges[0]}"] + [f"{a} - {b}" for a, b in pairwise(edges)] + [f"≥ {edges[-1]}"]


def draw_map(
    path: Path,
    polygons: list[F64],
    values: F64,
    breaks: Sequence[float],
    fmt: str,
    title: str,
    subtitle: str,
    *,
    bbox: Bbox,
    edge_buffer_m: float,
    hubs: Sequence[tuple[str, BaseGeometry]] = (),
) -> None:
    classes = classify(values, breaks)
    colours = [NONE_FILL if c < 0 else RAMP[c] for c in classes]
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2
    fig, ax = plt.subplots(figsize=(8, 8.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.add_collection(
        PolyCollection(polygons, facecolors=colours, edgecolors=SURFACE, linewidths=0.15)
    )
    dlon = edge_buffer_m / (METRES_PER_DEGREE_LON * np.cos(np.radians(mid_lat)))
    dlat = edge_buffer_m / METRES_PER_DEGREE_LAT
    ax.add_patch(
        Rectangle(
            (min_lon + dlon, min_lat + dlat),
            max_lon - min_lon - 2 * dlon,
            max_lat - min_lat - 2 * dlat,
            fill=False,
            edgecolor=INK_MUTED,
            linestyle=(0, (4, 3)),
            linewidth=0.8,
        )
    )
    for _, shape in hubs:
        for part in getattr(shape, "geoms", [shape]):
            x, y = part.exterior.xy
            ax.plot(x, y, color=HUB_LINE, linewidth=1.2)
    ax.set_xlim(min_lon, max_lon)
    ax.set_ylim(min_lat, max_lat)
    ax.set_aspect(1 / np.cos(np.radians(mid_lat)))
    ax.set_axis_off()
    handles = [
        Patch(facecolor=RAMP[i], label=label) for i, label in enumerate(class_labels(breaks, fmt))
    ]
    handles.insert(0, Patch(facecolor=NONE_FILL, label="none"))
    handles.append(Patch(facecolor="none", edgecolor=INK_MUTED, linestyle="--", label="edge band"))
    if hubs:
        handles.append(Patch(facecolor="none", edgecolor=HUB_LINE, label="validation hubs"))
    ax.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(1.0, 1.0),
        frameon=False,
        fontsize=8,
        labelcolor=INK,
    )
    fig.suptitle(title, x=0.02, y=0.985, ha="left", fontsize=12, color=INK)
    fig.text(0.02, 0.945, subtitle, ha="left", fontsize=8.5, color=INK_MUTED)
    fig.subplots_adjust(left=0.01, right=0.78, top=0.93, bottom=0.01)
    fig.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


# --- GeoParquet -------------------------------------------------------------------------------


def write_geoparquet(frame: pl.DataFrame, cells: Sequence[str], path: Path) -> None:
    """Zones with hexagon geometry (WKB, lon/lat) and GeoParquet 1.1 metadata for QGIS."""
    polygons = [Polygon(ring) for ring in hexagons(cells)]
    wkb = shapely.to_wkb(np.array(polygons, dtype=object))
    table = frame.to_arrow(compat_level=pl.CompatLevel.oldest()).append_column(
        "geometry", pa.array(list(wkb), type=pa.binary())
    )
    bounds = shapely.total_bounds(np.array(polygons, dtype=object)).tolist()
    geo = {
        "version": "1.1.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {"encoding": "WKB", "geometry_types": ["Polygon"], "bbox": bounds}
        },  # no "crs": OGC:CRS84 (lon/lat), the GeoParquet default
    }
    metadata = dict(table.schema.metadata or {})
    metadata[b"geo"] = json.dumps(geo).encode("utf-8")
    pq.write_table(table.replace_schema_metadata(metadata), path, compression="zstd")


# --- report -----------------------------------------------------------------------------------


@dataclass
class ReportResult:
    out_dir: Path
    maps: list[str]
    zones: int


def _pct(value: float) -> str:
    if value == 0:
        return "0%"
    return f"{value:.1%}" if value >= 0.001 else f"{value:.2%}"


def build_report(
    base: Path, config: CityConfig, *, scenario: str, hubs: Sequence[tuple[str, BaseGeometry]]
) -> ReportResult:
    s = config.accessibility
    acc_dir = base / "accessibility" / scenario
    zones = pl.read_parquet(base / "zones" / "zones.parquet").sort("zone_idx")
    proxy = pl.read_parquet(base / "attraction" / "attraction.parquet").sort("zone_idx")
    long = pl.read_parquet(acc_dir / "accessibility.parquet")
    summary = pl.read_parquet(acc_dir / "summary.parquet")
    manifest = json.loads((acc_dir / "manifest.json").read_text(encoding="utf-8"))
    matrix = json.loads(
        (base / "tt_matrix" / scenario / "manifest.json").read_text(encoding="utf-8")
    )
    proxy_manifest = json.loads((base / "attraction" / "manifest.json").read_text(encoding="utf-8"))

    wide = long.pivot(
        on=["percentile", "threshold_min"],
        index="zone_idx",
        values=["est_jobs_share", "population_share"],
        separator="_",
    ).sort("zone_idx")
    rename = {}
    for p in s.percentiles:
        for t in s.thresholds_min:
            for value, short in (("est_jobs_share", "est_jobs"), ("population_share", "pop")):
                rename[f"{value}_{{{p},{t}}}"] = f"{short}_p{p}_{t}min"
    wide = wide.rename(rename)  # raises if a percentile/threshold column is missing
    edge = long.filter(
        (pl.col("percentile") == s.percentiles[0])
        & (pl.col("threshold_min") == s.thresholds_min[0])
    ).sort("zone_idx")["edge_zone"]
    table = (
        zones.select("zone_idx", "h3_cell", "population")
        .join(
            proxy.select("zone_idx", pl.col("employment_score").alias("est_jobs_score")),
            on="zone_idx",
        )
        .with_columns(pl.Series("edge_zone", edge))
        .join(wide, on="zone_idx")
        .sort("zone_idx")
    )

    out = acc_dir / "report"
    staging = out.with_name(f".{out.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    write_geoparquet(table, table["h3_cell"].to_list(), staging / "accessibility.geoparquet")

    polygons = hexagons(table["h3_cell"].to_list())
    n = table.height
    hp, ht = s.headline_percentile, s.headline_threshold_min
    good, bad = s.percentiles[0], s.percentiles[-1]
    window = f"departures {s.window_start}-{s.window_end}"
    maps: list[tuple[str, str]] = []

    def add_map(name: str, values: F64, breaks: Sequence[float], fmt: str, title: str,
                subtitle: str, *, with_hubs: bool = False) -> None:  # fmt: skip
        draw_map(
            staging / name, polygons, values, breaks, fmt, title, subtitle,
            bbox=config.city.bbox, edge_buffer_m=s.edge_buffer_m,
            hubs=hubs if with_hubs else (),
        )  # fmt: skip
        maps.append((name, f"{title}. {subtitle}"))

    for t in (ht, s.thresholds_min[-1]):
        add_map(
            f"map_est_jobs_p{hp}_{t}min.png",
            table[f"est_jobs_p{hp}_{t}min"].to_numpy(),
            SHARE_BREAKS,
            "{:.1%}",
            f"Share of estimated jobs reachable within {t} min (Simulated)",
            f"Median (p{hp}) over {window}; jobs from the employment proxy (Estimated)",
        )
    gap = (table[f"est_jobs_p{good}_{ht}min"] - table[f"est_jobs_p{bad}_{ht}min"]).to_numpy()
    add_map(
        f"map_reliability_{ht}min.png",
        gap,
        GAP_BREAKS,
        "{:.2%}",
        f"Good-day minus bad-day reach within {ht} min (Simulated)",
        f"p{good} minus p{bad} share of estimated jobs, in percentage points",
    )
    add_map(
        "map_est_jobs_proxy.png",
        table["est_jobs_score"].to_numpy() * n,
        RELATIVE_BREAKS,
        "{:g}x",
        "Estimated jobs per zone (Estimated, weights Assumed)",
        "Employment proxy, as a multiple of the average zone; red outlines are the hand-drawn hubs",
        with_hubs=True,
    )
    population = table["population"].to_numpy()
    add_map(
        "map_population.png",
        population / population.mean(),
        RELATIVE_BREAKS,
        "{:g}x",
        "Residents per zone (Estimated, WorldPop 2021)",
        "As a multiple of the average zone",
    )

    blocks = report_blocks(config, scenario, manifest, matrix, proxy_manifest, summary, maps)
    (staging / "report.md").write_text(to_markdown(blocks), encoding="utf-8", newline="\n")
    title = f"Accessibility - {config.city.name} ({scenario})"
    (staging / "report.html").write_text(
        to_html(blocks, title, staging), encoding="utf-8", newline="\n"
    )
    if out.exists():
        shutil.rmtree(out)
    staging.rename(out)
    return ReportResult(out_dir=out, maps=[m for m, _ in maps], zones=n)


def report_blocks(
    config: CityConfig,
    scenario: str,
    manifest: dict[str, object],
    matrix: dict[str, object],
    proxy_manifest: dict[str, object],
    summary: pl.DataFrame,
    maps: Sequence[tuple[str, str]],
) -> list[Block]:
    s = config.accessibility
    r = config.routing
    a = config.attraction
    hp, ht = s.headline_percentile, s.headline_threshold_min
    headline = float(manifest["headline_est_jobs_share"])  # type: ignore[arg-type]
    stats = matrix["stats"]
    assert isinstance(stats, dict)

    def mean(scope: str, p: int, measure: str) -> list[str]:
        rows = summary.filter(
            (pl.col("scope") == scope)
            & (pl.col("percentile") == p)
            & (pl.col("measure") == measure)
        ).sort("threshold_min")
        return [_pct(v) for v in rows["population_weighted_mean"]]

    blocks: list[Block] = [
        Heading(1, f"Transit accessibility - {config.city.name} ({scenario})"),
        Para(
            f"Residents can reach on average **{_pct(headline)} of the city's estimated jobs** "
            f"within {ht} min by bus, metro and walking (median over weekday departures "
            f"{s.window_start}-{s.window_end}; population-weighted). This is a model result "
            "(Simulated) built on estimated jobs; it is a share of the city, not a count of jobs."
        ),
        Heading(2, "What kind of number is each quantity?"),
        Table(
            ["Quantity", "Label", "Source"],
            [
                [
                    "Bus and metro timetables",
                    "Observed",
                    "GTFS feeds (BMTC, BMRCL) for one weekday",
                ],
                ["Points of interest", "Observed", "OpenStreetMap; job categories are Assumed"],
                ["Residents per zone", "Estimated", "WorldPop 2021 (modelled raster)"],
                ["Building footprints", "Estimated", "Open Buildings (machine-detected)"],
                ["Estimated jobs per zone", "Estimated", "Employment proxy; weights are Assumed"],
                ["Travel times and reach", "Simulated", "RAPTOR router over the departure window"],
                [
                    "Window, thresholds, walking, edge band, index base",
                    "Assumed",
                    "Chosen settings, listed below",
                ],
            ],
        ),
        Heading(2, "Average share reachable (population-weighted)"),
        Table(
            ["Measure", "Percentile", *(f"{t} min" for t in s.thresholds_min)],
            [
                [label, f"p{p}", *mean("all zones", p, measure)]
                for measure, label in (("est_jobs", "Estimated jobs"), ("population", "Residents"))
                for p in s.percentiles
            ],
            [False, False, *([True] * len(s.thresholds_min))],
        ),
        Para(
            f"p{s.percentiles[0]} is a good day (a quarter of departures do at least this well), "
            f"p{s.percentiles[-1]} a bad one."
        ),
        Heading(2, f"Who reaches how much (p{hp}, estimated jobs)"),
        Para("Quantiles are over residents: q10 means 10 % of residents reach less."),
        Table(
            [
                "Scope",
                "Threshold",
                "Mean",
                "q10",
                "q25",
                "q50",
                "q75",
                "q90",
                "Gini",
                "Residents < 1 %",
            ],
            [
                [
                    row["scope"],
                    f"{row['threshold_min']} min",
                    _pct(row["population_weighted_mean"]),
                    *(_pct(row[q]) for q in ("q10", "q25", "q50", "q75", "q90")),
                    f"{row['gini']:.2f}",
                    _pct(row["population_share_below_1pct"]),
                ]
                for row in summary.filter(
                    (pl.col("percentile") == hp) & (pl.col("measure") == "est_jobs")
                )
                .sort("scope", "threshold_min")
                .iter_rows(named=True)
            ],
            [False, True, True, True, True, True, True, True, True, True],
        ),
        Heading(2, "Maps"),
    ]
    for file, caption in maps:
        blocks.append(Image(file, caption))
    zones_total = int(matrix["zones"])  # type: ignore[call-overload]
    with_stop = int(stats["zones_with_stop"])
    covered = _pct(float(stats["population_with_stop_share"]))
    caveats = [
        f"{with_stop:,} of {zones_total:,} zones ({covered} of residents) have a stop within a "
        f"{r.max_access_walk_m:g} m walk; the others reach only zones within "
        f"{s.max_walk_only_m:g} m on foot.",
        "Bus times are scheduled times without traffic, so real peak-hour reach is probably "
        "lower than simulated.",
        f"Zones within {s.edge_buffer_m:g} m of the study-area edge are flagged (dashed line on "
        "the maps): their destinations outside the area are missing.",
    ]
    sensitivity = proxy_manifest.get("sensitivity")
    hub = sensitivity[0].get("hub_check") if isinstance(sensitivity, list) and sensitivity else None
    if isinstance(hub, dict) and a is not None:
        verdict = "passed" if hub["passed"] else "FAILED"
        caveats.append(
            f"Employment proxy hub check {verdict}: {_pct(hub['share_in_pass_rank'])} of "
            f"hand-drawn hub zones rank in the top {_pct(a.hub_pass_rank)} of zones, "
            f"{_pct(hub['share_in_report_rank'])} in the top {_pct(a.hub_report_rank)}."
        )
    blocks += [
        Heading(2, "Coverage and caveats"),
        Bullets(caveats),
        Heading(2, "Settings (Assumed)"),
        Table(
            ["Setting", "Value"],
            [
                [
                    "Departure window",
                    f"{s.window_start}-{s.window_end}, every {s.departure_step_s} s",
                ],
                ["Percentiles", ", ".join(f"p{p}" for p in s.percentiles)],
                ["Thresholds", ", ".join(f"{t} min" for t in s.thresholds_min)],
                ["Walking speed", f"{r.walking_speed_m_s} m/s"],
                ["Walk to/from stops", f"≤ {r.max_access_walk_m:g} m"],
                ["Walk between stops", f"≤ {r.max_transfer_walk_m:g} m"],
                ["Walk-only trips", f"≤ {s.max_walk_only_m:g} m"],
                ["Vehicles per journey", f"≤ {r.max_rounds}"],
                [
                    "Station entry",
                    ", ".join(f"{k} {v} s" for k, v in sorted(r.station_entry_s.items())) or "none",
                ],
                ["Edge band", f"{s.edge_buffer_m:g} m"],
                [
                    "Estimated Opportunity Index base",
                    f"{a.opportunity_index_total:,} (display only, not jobs)" if a else "-",
                ],
            ],
        ),
        Heading(2, "Files"),
        Bullets(
            [
                "`accessibility.geoparquet`: one hexagon per zone with every share, the estimated "
                "jobs score and the edge flag; open it in QGIS (Layer > Add Vector Layer).",
                "`report.md` / `report.html`: this report.",
            ]
        ),
    ]
    return blocks
