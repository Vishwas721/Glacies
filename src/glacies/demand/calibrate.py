"""β calibration against observed metro station entries (Phase 5 M4).

The model reproduces the *shape* of ridership, not its level: it covers home-to-work trips
from zones within walking distance of a stop, while metro riders also come by feeder bus, auto
and two-wheeler and travel for other purposes. So the objective is the RMSE between each
station's share of entries, simulated and observed, with shares taken within the station set
being fitted. The level ratio is reported, never fitted.

Stations are split before anything is computed: lines in ``exclude_lines`` (whose service at
the ridership dates differs from the timetable) are left out; ``held_out_stations`` are never
seen by the search; the rest train β. Shares are normalised within each set, so the held-out
counts do not enter the training objective even through a denominator.

The search runs Furness at a log-spaced grid of β (warm-starting each from the previous one),
then a golden-section refinement in log β around the best grid point, all at a coarser Furness
tolerance; the chosen β is re-run at the configured tolerance for the reported fit. Fit
statistics: share RMSE, R² of shares, GEH of counts after scaling the simulated set total to
the observed one (GEH is meant for hourly counts; these are two-hour means), and the level
ratio. Station-pair flows are a secondary check on the dates that have them.
"""

from __future__ import annotations

import math
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.cities import DemandCalibration, DemandConfig
from glacies.demand.metro import station_flows
from glacies.demand.od import DemandBuild, Prepared, balance
from glacies.demand.production import DemandError
from glacies.fsutil import rename_with_retry
from glacies.provenance import DataNature, sha256_file

F64 = npt.NDArray[np.float64]
TRAINING, HELD_OUT, EXCLUDED = "training", "held_out", "excluded"
MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
SWEEP_NAME = "sweep.parquet"
STATIONS_NAME = "stations.parquet"
PAIRS_NAME = "pairs.parquet"
GOLDEN = (math.sqrt(5) - 1) / 2


def station_sets(stations: pl.DataFrame, calibration: DemandCalibration) -> pl.DataFrame:
    """station_idx, name, lines, set: excluded if every line of the station is excluded."""
    excluded = set(calibration.exclude_lines)
    held = set(calibration.held_out_stations)
    return stations.with_columns(
        pl.when(
            pl.col("lines").str.split("+").list.eval(pl.element().is_in(list(excluded))).list.all()
        )
        .then(pl.lit(EXCLUDED))
        .when(pl.col("name").is_in(list(held)))
        .then(pl.lit(HELD_OUT))
        .otherwise(pl.lit(TRAINING))
        .alias("set")
    )


class Fit(BaseModel):
    """Simulated against observed counts of one set (shares taken within the set)."""

    items: int
    rmse_share: float
    r2_share: float  # 1 - SS_res / SS_tot of the shares
    correlation: float  # Pearson, shares
    mean_geh: float  # counts, simulated scaled to the observed set total
    share_geh_below_5: float
    level_ratio: float  # simulated total / observed total


def fit(simulated: F64, observed: F64) -> Fit:
    if simulated.size == 0 or observed.sum() <= 0:
        raise DemandError("nothing observed to fit against")
    obs_share = observed / observed.sum()
    total = simulated.sum()
    sim_share = simulated / total if total > 0 else np.zeros_like(simulated)
    residual = sim_share - obs_share
    ss_tot = float(((obs_share - obs_share.mean()) ** 2).sum())
    scaled = sim_share * observed.sum()
    denominator = scaled + observed
    geh = np.sqrt(
        np.divide(2 * (scaled - observed) ** 2, denominator, out=np.zeros_like(observed),
                  where=denominator > 0)
    )  # fmt: skip
    spread = sim_share.std() * obs_share.std()
    correlation = (
        float(np.mean((sim_share - sim_share.mean()) * (obs_share - obs_share.mean())) / spread)
        if spread > 0
        else 0.0
    )
    return Fit(
        items=int(simulated.size),
        rmse_share=float(np.sqrt(np.mean(residual**2))),
        r2_share=1 - float((residual**2).sum()) / ss_tot if ss_tot > 0 else 0.0,
        correlation=correlation,
        mean_geh=float(geh.mean()),
        share_geh_below_5=float((geh < 5).mean()),
        level_ratio=float(total / observed.sum()),
    )


@dataclass(frozen=True)
class Targets:
    """Observed calibration targets and the network objects needed to simulate them."""

    sets: pl.DataFrame  # station_idx, name, lines, set
    entries: pl.DataFrame  # station_idx, observed
    pairs: pl.DataFrame  # entry_station, exit_station, observed
    pair_dates: list[date]
    reach: pl.DataFrame
    paths: pl.DataFrame
    stations: pl.DataFrame


def station_table(build: DemandBuild, targets: Targets) -> tuple[pl.DataFrame, pl.DataFrame]:
    flows = station_flows(build.od, targets.reach, targets.paths, targets.stations)
    stations = (
        targets.sets.join(targets.entries, on="station_idx", how="left")
        .join(flows.stations.select("station_idx", "entries"), on="station_idx", how="left")
        .select(
            "station_idx",
            "name",
            "lines",
            "set",
            pl.col("observed").fill_null(0.0),
            pl.col("entries").fill_null(0.0).alias("simulated"),
        )
        .sort("station_idx")
    )
    return stations, flows.pairs


def set_fit(stations: pl.DataFrame, which: str) -> Fit:
    rows = stations.filter(pl.col("set") == which)
    return fit(rows["simulated"].to_numpy(), rows["observed"].to_numpy())


class SweepPoint(BaseModel):
    beta_per_min: float
    stage: str  # "grid" or "refine"
    rmse_share_training: float
    r2_share_training: float
    mean_km: float
    mean_cost_min: float
    iterations: int


@dataclass
class Calibration:
    beta_per_min: float
    sweep: list[SweepPoint]
    at_boundary: bool
    build: DemandBuild
    stations: pl.DataFrame
    pairs: pl.DataFrame  # entry_station, exit_station, set, observed, simulated
    fits: dict[str, Fit]  # per station set, and "pairs_<set>"


def _pair_table(simulated: pl.DataFrame, targets: Targets) -> pl.DataFrame:
    sets = targets.sets.select("station_idx", "set")
    keys = ["entry_station", "exit_station"]
    return (
        targets.pairs.join(simulated.rename({"trips": "simulated"}), on=keys, how="full",
                           coalesce=True)
        .join(sets.rename({"station_idx": "entry_station", "set": "entry_set"}), on="entry_station")
        .join(sets.rename({"station_idx": "exit_station", "set": "exit_set"}), on="exit_station")
        .with_columns(
            pl.col("observed").fill_null(0.0),
            pl.col("simulated").fill_null(0.0),
            # A pair is fitted with a set only if both of its stations are in that set.
            pl.when(pl.col("entry_set") == pl.col("exit_set"))
            .then(pl.col("entry_set"))
            .otherwise(pl.lit("mixed"))
            .alias("set"),
        )
        .select(*keys, "set", "observed", "simulated")
        .sort(keys)
    )  # fmt: skip


def search_beta(
    evaluate: Callable[[float, str], float],
    beta_min: float,
    beta_max: float,
    grid_points: int,
    refine_steps: int,
) -> tuple[float, bool]:
    """β with the lowest ``evaluate(β, stage)`` and whether the grid's best was at an edge.

    A log-spaced grid (ascending, so each Furness run warm-starts from a neighbour), then a
    golden-section search on log β between the best grid point's neighbours. Ties go to the
    smaller β.
    """
    grid = np.geomspace(beta_min, beta_max, grid_points)
    tried: list[tuple[float, float]] = []

    def score(beta: float, stage: str) -> float:
        value = evaluate(beta, stage)
        tried.append((value, beta))
        return value

    scores = [score(float(beta), "grid") for beta in grid]
    best = int(np.argmin(scores))
    low = math.log(grid[max(best - 1, 0)])
    high = math.log(grid[min(best + 1, grid.size - 1)])
    x1 = high - GOLDEN * (high - low)
    x2 = low + GOLDEN * (high - low)
    f1, f2 = score(math.exp(x1), "refine"), score(math.exp(x2), "refine")
    for _ in range(refine_steps - 2):
        if f1 <= f2:
            high, x2, f2 = x2, x1, f1
            x1 = high - GOLDEN * (high - low)
            f1 = score(math.exp(x1), "refine")
        else:
            low, x1, f1 = x1, x2, f2
            x2 = low + GOLDEN * (high - low)
            f2 = score(math.exp(x2), "refine")
    return min(tried)[1], best in (0, grid.size - 1)


def calibrate(
    prepared: Prepared,
    demand: DemandConfig,
    targets: Targets,
    *,
    on_point: Callable[[SweepPoint], None] | None = None,
) -> Calibration:
    """Search β on the training stations; see module doc."""
    cal = demand.calibration
    sweep: list[SweepPoint] = []
    warm: dict[str, F64] = {}

    def evaluate(beta: float, stage: str) -> float:
        build, b = balance(
            prepared, demand, beta, tolerance=cal.sweep_tolerance, initial_b=warm.get("b")
        )
        warm["b"] = b
        stations, _ = station_table(build, targets)
        training = set_fit(stations, TRAINING)
        point = SweepPoint(
            beta_per_min=beta,
            stage=stage,
            rmse_share_training=training.rmse_share,
            r2_share_training=training.r2_share,
            mean_km=build.trip_length.mean_km,
            mean_cost_min=build.trip_length.mean_cost_min,
            iterations=build.convergence.iterations,
        )
        sweep.append(point)
        if on_point is not None:
            on_point(point)
        return training.rmse_share

    chosen, at_boundary = search_beta(
        evaluate, cal.beta_min, cal.beta_max, cal.grid_points, cal.refine_steps
    )
    build, _ = balance(prepared, demand, chosen)
    stations, simulated_pairs = station_table(build, targets)
    pairs = _pair_table(simulated_pairs, targets)
    fits = {which: set_fit(stations, which) for which in (TRAINING, HELD_OUT, EXCLUDED)}
    for which in (TRAINING, HELD_OUT):
        rows = pairs.filter(pl.col("set") == which)
        if rows.height and rows["observed"].sum() > 0:
            fits[f"pairs_{which}"] = fit(rows["simulated"].to_numpy(), rows["observed"].to_numpy())
    return Calibration(
        beta_per_min=chosen,
        sweep=sweep,
        at_boundary=at_boundary,
        build=build,
        stations=stations,
        pairs=pairs,
        fits=fits,
    )


# --- outputs ----------------------------------------------------------------------------------


class CalibrationInput(BaseModel):
    stage: str
    manifest_sha256: str


class CalibrationManifest(BaseModel):
    city: str
    scenario: str
    builder_version: str
    nature: DataNature
    inputs: list[CalibrationInput]
    calibration: DemandCalibration
    observed_dates: list[date]
    pair_dates: list[date]
    beta_per_min: float
    at_boundary: bool
    fits: dict[str, Fit]
    mean_km: float
    mean_cost_min: float
    trips: float
    outputs: dict[str, str]


def write_calibration(
    result: Calibration,
    out_dir: Path,
    *,
    city: str,
    scenario: str,
    calibration: DemandCalibration,
    pair_dates: list[date],
    inputs: list[CalibrationInput],
) -> CalibrationManifest:
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    sweep = pl.DataFrame([p.model_dump() for p in result.sweep])
    outputs = {}
    for name, frame in (
        (SWEEP_NAME, sweep),
        (STATIONS_NAME, result.stations),
        (PAIRS_NAME, result.pairs),
    ):
        frame.rechunk().write_parquet(staging / name, compression="zstd", statistics=True)
        outputs[name] = sha256_file(staging / name)
    t = result.build.trip_length
    manifest = CalibrationManifest(
        city=city,
        scenario=scenario,
        builder_version=__version__,
        nature=DataNature.SIMULATED,
        inputs=inputs,
        calibration=calibration,
        observed_dates=calibration.dates,
        pair_dates=pair_dates,
        beta_per_min=result.beta_per_min,
        at_boundary=result.at_boundary,
        fits=result.fits,
        mean_km=t.mean_km,
        mean_cost_min=t.mean_cost_min,
        trips=result.build.ends.stats.trips,
        outputs=outputs,
    )
    (staging / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (staging / REPORT_NAME).write_text(report(manifest, result), encoding="utf-8", newline="\n")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rename_with_retry(staging, out_dir)
    return manifest


def _fit_row(name: str, f: Fit) -> str:
    return (
        f"| {name} | {f.items} | {f.rmse_share:.4f} | {f.r2_share:.2f} | {f.correlation:.2f} "
        f"| {f.mean_geh:.1f} | {f.share_geh_below_5:.0%} | {f.level_ratio:.2f} |"
    )


def report(m: CalibrationManifest, result: Calibration) -> str:
    names = {
        TRAINING: "Training stations",
        HELD_OUT: "Held-out stations",
        EXCLUDED: "Excluded lines",
        f"pairs_{TRAINING}": "Training station pairs",
        f"pairs_{HELD_OUT}": "Held-out station pairs",
    }
    stations = result.stations.with_columns(
        (pl.col("simulated") / pl.col("simulated").sum().over("set")).alias("sim_share"),
        (pl.col("observed") / pl.col("observed").sum().over("set")).alias("obs_share"),
    )
    held = stations.filter(pl.col("set") == HELD_OUT).sort("observed", descending=True)
    sweep = sorted(result.sweep, key=lambda p: p.beta_per_min)
    cal = m.calibration
    lines = [
        f"# β calibration — `{m.city}` / `{m.scenario}` (Simulated vs Observed)",
        "",
        f"Builder {m.builder_version} · objective: RMSE of station entry shares on training "
        f"stations · entries {cal.hours[0]:02d}:00-{cal.hours[-1] + 1:02d}:00 averaged over "
        f"{len(m.observed_dates)} dates · station pairs on {len(m.pair_dates)} date(s) "
        f"({', '.join(map(str, m.pair_dates))}), by exit hour",
        "",
        f"**Chosen β = {m.beta_per_min:.4f} per minute** (1/β = {1 / m.beta_per_min:.0f} min)"
        + (" — **at the edge of the searched range**; widen it." if m.at_boundary else "."),
        f"At this β: {m.trips:,.0f} trips, mean {m.mean_km:.1f} km, {m.mean_cost_min:.1f} min "
        "door to door.",
        "",
        "## Fit",
        "",
        "Shares are taken within each set; GEH compares counts after scaling the simulated "
        "set total to the observed one. The level ratio (simulated / observed entries) is "
        "reported, not fitted: the model covers only home-to-work trips from zones near a stop.",
        "",
        "| Set | Items | RMSE (share) | R² (share) | r | Mean GEH | GEH < 5 | Level |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        *(_fit_row(names.get(k, k), f) for k, f in m.fits.items()),
        "",
        "## Held-out stations (never seen by the search)",
        "",
        "| Station | Lines | Observed | Simulated | Share obs. | Share sim. |",
        "|---|---|---:|---:|---:|---:|",
        *(
            f"| {r['name']} | {r['lines']} | {r['observed']:,.0f} | {r['simulated']:,.0f} | "
            f"{r['obs_share']:.1%} | {r['sim_share']:.1%} |"
            for r in held.iter_rows(named=True)
        ),
        "",
        "## Sweep (training stations only)",
        "",
        f"Furness tolerance {cal.sweep_tolerance:g} during the sweep; the chosen β is re-run at "
        "the configured tolerance.",
        "",
        "| β | Stage | RMSE (share) | R² | Mean km | Mean min | Iterations |",
        "|---:|---|---:|---:|---:|---:|---:|",
        *(
            f"| {p.beta_per_min:.4f} | {p.stage} | {p.rmse_share_training:.5f} | "
            f"{p.r2_share_training:.3f} | {p.mean_km:.1f} | {p.mean_cost_min:.1f} | "
            f"{p.iterations} |"
            for p in sweep
        ),
        "",
    ]
    return "\n".join(lines)
