"""Assignment validation report: convergence, station entries, crowded segments (Phase 6 M6).

Reads a finished assignment (``assignment/<scenario>/``) and writes, under
``reports/assignment/<scenario>/``:

- ``convergence.png``: the crowding loop's gap per iteration;
- ``stations.png``: simulated against observed metro gate entries per station, by set (training,
  held-out, excluded lines), when the run was scored against ridership (validation level 4);
- ``segments_peak.geoparquet`` and ``segments_peak.png``: every route's stop-to-stop segment
  with the passengers, highest load and highest load factor of the vehicles leaving it in the
  report window, for checking against corridors known to be crowded (QGIS);
- ``report.md`` tying them together. Everything is Simulated; observed entries are Observed.
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
import polars as pl
from matplotlib.axes import Axes
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from shapely.geometry import LineString

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
    to_markdown,
    write_geometries,
)
from glacies.fsutil import rename_with_retry

REPORTS_DIR = "reports"
# Categorical slots 1-3 of the dataviz reference palette (validated: CVD ΔE >= 9.2; aqua is
# below 3:1 on the surface, so each set also has its own marker and the misses are labelled).
SET_STYLE = {
    "training": ("#2a78d6", "o", "Training stations"),
    "held_out": ("#eb6834", "s", "Held-out stations"),
    "excluded": ("#1baf7a", "^", "Excluded lines"),
}
# Ordinal blue ramp from step 250 (validated: monotone, light end 2.06:1 on the surface).
LOAD_CLASSES = ((0.5, "#86b6ef"), (1.0, "#3987e5"), (1.5, "#256abf"), (np.inf, "#0d366b"))
LOAD_LABELS = ("under 0.5", "0.5-1.0", "1.0-1.5", "over 1.5")
TOP_MISSES = 6
TOP_SEGMENTS = 15


@dataclass(frozen=True)
class ValidationResult:
    out_dir: Path
    figures: list[str]
    segments: int


def peak_segments(
    loads: pl.DataFrame,
    trips: pl.DataFrame,
    routes: pl.DataFrame,
    report_window: tuple[int, int],
) -> pl.DataFrame:
    """Per route and stop-to-stop segment, the vehicles leaving it in the report window:
    trips, passengers (sum of loads), highest load and highest load factor. Empty segments
    are kept, so quiet corridors show too."""
    start, end = report_window
    return (
        loads.filter((pl.col("departure") >= start) & (pl.col("departure") < end))
        .join(trips.select("trip_idx", "route_idx"), on="trip_idx")
        .group_by("route_idx", "from_stop_idx", "to_stop_idx")
        .agg(
            pl.len().alias("trips"),
            pl.col("load").sum().alias("passengers"),
            pl.col("load").max().alias("max_load"),
            pl.col("load_factor").max().alias("max_load_factor"),
            pl.col("capacity").first(),
        )
        .join(routes.select("route_idx", "mode", "short_name"), on="route_idx", how="left")
        .sort("route_idx", "from_stop_idx", "to_stop_idx")
    )


def _lines(segments: pl.DataFrame, stops: pl.DataFrame) -> list[LineString]:
    coords = stops.select("stop_idx", "lat", "lon")
    ends = (
        segments.select("from_stop_idx", "to_stop_idx")
        .join(
            coords.rename({"stop_idx": "from_stop_idx", "lat": "lat0", "lon": "lon0"}),
            on="from_stop_idx",
            how="left",
            maintain_order="left",
        )
        .join(
            coords.rename({"stop_idx": "to_stop_idx", "lat": "lat1", "lon": "lon1"}),
            on="to_stop_idx",
            how="left",
            maintain_order="left",
        )
    )
    return [
        LineString([(lon0, lat0), (lon1, lat1)])
        for lat0, lon0, lat1, lon1 in ends.select("lat0", "lon0", "lat1", "lon1").iter_rows()
    ]


def _style(ax: Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED, labelsize=8)
    ax.grid(color="#e4e3df", linewidth=0.6)
    ax.set_axisbelow(True)


def draw_convergence(convergence: pl.DataFrame, gap: float, path: Path) -> None:
    rows = convergence.filter(pl.col("iteration") > 0)
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    ax.plot(rows["iteration"], rows["gap"], color="#2a78d6", linewidth=2, marker="o", markersize=4)
    ax.axhline(gap, color=INK_MUTED, linestyle=(0, (4, 3)), linewidth=1)
    ax.text(
        float(rows["iteration"].to_numpy().max()),
        gap,
        f" stop at {gap:g}",
        va="bottom",
        ha="right",
        fontsize=8,
        color=INK_MUTED,
    )
    ax.set_yscale("log")
    ax.set_xlabel("Iteration", color=INK, fontsize=9)
    ax.set_ylabel("Relative change of segment loads", color=INK, fontsize=9)
    fig.suptitle("Crowding loop convergence (Simulated)", x=0.02, ha="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


def draw_stations(stations: pl.DataFrame, path: Path) -> None:
    """Simulated against observed entries per station on log axes, one marker per set."""
    rows = stations.filter((pl.col("observed") > 0) & (pl.col("entries") > 0))
    fig, ax = plt.subplots(figsize=(6.4, 6.0), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    values = np.concatenate([rows["observed"].to_numpy(), rows["entries"].to_numpy()])
    low, high = float(values.min()) * 0.8, float(values.max()) * 1.25
    ax.plot([low, high], [low, high], color=INK_MUTED, linewidth=1, linestyle=(0, (4, 3)))
    handles = []
    for name, (colour, marker, label) in SET_STYLE.items():
        part = rows.filter(pl.col("set") == name)
        if part.height == 0:
            continue
        ax.scatter(
            part["observed"],
            part["entries"],
            s=30,
            c=colour,
            marker=marker,
            edgecolors=SURFACE,
            linewidths=1.5,
            zorder=3,
        )
        handles.append(Line2D([], [], color=colour, marker=marker, linestyle="", label=label))
    misses = rows.with_columns(
        (pl.col("entries") / pl.col("observed")).log().abs().alias("miss")
    ).sort("miss", "station_idx", descending=[True, False])
    for name, x, y in misses.head(TOP_MISSES).select("name", "observed", "entries").iter_rows():
        ax.annotate(name, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7, color=INK)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(low, high)
    ax.set_ylim(low, high)
    ax.set_xlabel("Observed entries, 08:00-10:00 (BMRCL, Observed)", color=INK, fontsize=9)
    ax.set_ylabel("Simulated gate entries (Simulated)", color=INK, fontsize=9)
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=8, labelcolor=INK)
    fig.suptitle(
        "Metro entries per station: simulated against observed",
        x=0.02,
        ha="left",
        fontsize=11,
        color=INK,
    )
    fig.text(
        0.02,
        0.925,
        "Dashed line: simulated = observed. Labelled: the largest misses.",
        fontsize=8,
        color=INK_MUTED,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


def draw_segment_map(segments: pl.DataFrame, lines: list[LineString], path: Path) -> None:
    """Segments coloured by their highest peak load factor; heavier classes drawn on top."""
    lf = segments["max_load_factor"].fill_null(0.0).to_numpy()
    classes = np.searchsorted([c for c, _ in LOAD_CLASSES], lf, side="right")
    classes = np.minimum(classes, len(LOAD_CLASSES) - 1)
    fig, ax = plt.subplots(figsize=(8, 8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    xy = [np.asarray(line.coords) for line in lines]
    for k, (_, colour) in enumerate(LOAD_CLASSES):
        chosen = [xy[i] for i in np.flatnonzero(classes == k)]
        if chosen:
            ax.add_collection(
                LineCollection(chosen, colors=colour, linewidths=0.4 + 0.5 * k, zorder=k + 1)
            )
    if xy:
        points = np.vstack(xy)
        ax.set_xlim(points[:, 0].min(), points[:, 0].max())
        ax.set_ylim(points[:, 1].min(), points[:, 1].max())
        ax.set_aspect(1 / np.cos(np.radians(points[:, 1].mean())))
    ax.set_axis_off()
    handles = [
        Line2D([], [], color=colour, linewidth=2, label=label)
        for (_, colour), label in zip(LOAD_CLASSES, LOAD_LABELS, strict=True)
    ]
    ax.legend(
        handles=handles,
        title="Highest load factor",
        title_fontsize=8,
        loc="upper left",
        bbox_to_anchor=(1.0, 1.0),
        frameon=False,
        fontsize=8,
        labelcolor=INK,
    )
    fig.suptitle("Peak-hour segment loads (Simulated)", x=0.02, ha="left", fontsize=12, color=INK)
    fig.subplots_adjust(left=0.01, right=0.8, top=0.94, bottom=0.01)
    fig.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


def build_validation(
    base: Path,
    scenario: str,
    stops: pl.DataFrame,
    routes: pl.DataFrame,
    trips: pl.DataFrame,
    stop_gap: float,
) -> ValidationResult:
    """Write the validation report of ``assignment/<scenario>``; ``stop_gap`` is the MSA
    stopping rule, drawn on the convergence plot."""
    run = base / "assignment" / scenario
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    out_dir = base / REPORTS_DIR / "assignment" / scenario
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    start, end = (
        sum(int(x) * f for x, f in zip(t.split(":"), (3600, 60), strict=True))
        for t in manifest["report_window"].split("-")
    )
    figures = []
    blocks: list[Block] = [
        Heading(1, f"Assignment validation — `{manifest['city']}` / `{scenario}`"),
        Para(
            f"Method: {manifest['method']}. Departures {manifest['window']}; crowding for "
            f"vehicles leaving a stop {manifest['report_window']}. Every value is **Simulated** "
            "unless marked Observed."
        ),
    ]
    convergence_path = run / "convergence.parquet"
    if convergence_path.is_file() and manifest.get("msa"):
        msa = manifest["msa"]
        convergence = pl.read_parquet(convergence_path)
        draw_convergence(convergence, stop_gap, staging / "convergence.png")
        figures.append("convergence.png")
        blocks += [
            Heading(2, "Convergence"),
            Para(
                f"{'Converged' if msa['converged'] else 'Did not converge'} after "
                f"{msa['iterations']} iterations (final gap {msa['final_gap']:.4f}); logit scale "
                f"{msa['theta_per_min']:g}, fares {'on' if msa['use_fares'] else 'off'}."
            ),
            Image("convergence.png", "Gap per iteration"),
        ]
    stations = pl.read_parquet(run / "stations.parquet")
    if "observed" in stations.columns and manifest.get("station_fits"):
        draw_stations(stations, staging / "stations.png")
        figures.append("stations.png")
        fits = manifest["station_fits"]
        blocks += [
            Heading(2, "Metro entries against BMRCL (validation level 4)"),
            Table(
                ["Set", "Stations", "R² (share)", "r", "Mean GEH", "Simulated / observed"],
                [
                    [
                        SET_STYLE.get(k, ("", "", k))[2],
                        str(f["items"]),
                        f"{f['r2_share']:.2f}",
                        f"{f['correlation']:.2f}",
                        f"{f['mean_geh']:.1f}",
                        f"{f['level_ratio']:.2f}",
                    ]
                    for k, f in sorted(fits.items())
                ],
                align_right=[False, True, True, True, True, True],
            ),
            Image("stations.png", "Simulated against observed entries per station"),
        ]
    segments = peak_segments(pl.read_parquet(run / "loads.parquet"), trips, routes, (start, end))
    lines = _lines(segments, stops)
    write_geometries(segments, lines, "LineString", staging / "segments_peak.geoparquet")
    draw_segment_map(segments, lines, staging / "segments_peak.png")
    figures.append("segments_peak.png")
    names = stops.select("stop_idx", "name")
    top = (
        segments.sort("max_load_factor", "route_idx", descending=[True, False])
        .head(TOP_SEGMENTS)
        .join(names.rename({"stop_idx": "from_stop_idx", "name": "from"}), on="from_stop_idx")
        .join(names.rename({"stop_idx": "to_stop_idx", "name": "to"}), on="to_stop_idx")
        .sort("max_load_factor", "route_idx", descending=[True, False])
    )
    blocks += [
        Heading(2, "Crowded segments"),
        Para(
            "Check these against corridors known to be crowded; open "
            "`segments_peak.geoparquet` in QGIS for the whole network. Loads come from a "
            "soft-capacity model: a segment far above its capacity means the model sends more "
            "people there than could board, not a forecast."
        ),
        Image("segments_peak.png", "Peak-hour segment loads"),
        Table(
            [
                "Mode",
                "Route",
                "From",
                "To",
                "Trips",
                "Passengers",
                "Highest load",
                "Highest load factor",
            ],
            [
                [
                    r["mode"],
                    r["short_name"],
                    r["from"],
                    r["to"],
                    str(r["trips"]),
                    f"{r['passengers']:,.0f}",
                    f"{r['max_load']:,.0f}",
                    f"{r['max_load_factor']:.2f}",
                ]
                for r in top.iter_rows(named=True)
            ],
            align_right=[False, False, False, False, True, True, True, True],
        ),
        Heading(2, "Files"),
        Bullets(
            [
                "`segments_peak.geoparquet`: one line per route and stop-to-stop segment with "
                "trips, passengers, highest load and load factor in the report window (QGIS).",
                *[f"`{f}`" for f in figures],
            ]
        ),
    ]
    (staging / "report.md").write_text(to_markdown(blocks), encoding="utf-8", newline="\n")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rename_with_retry(staging, out_dir)
    return ValidationResult(out_dir=out_dir, figures=figures, segments=segments.height)
