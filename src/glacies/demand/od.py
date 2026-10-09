"""Synthetic AM-peak OD matrix: trip ends → gravity model → Parquet (Phase 5 M1-M2).

Outputs go to ``demand/<scenario>/``: ``trip_ends.parquet`` (O and D per zone),
``od.parquet`` (one row per pair with trips), a manifest carrying every prior with its
citation, and a build report. Trips are **Estimated**: they come from Estimated population and
employment, Assumed priors and Simulated travel times, and are not observed flows.

Trip length is reported two ways: the trips-weighted mean door-to-door time from the matrix,
and the straight line between zone points times the network detour factor of
``[scenario] detour_factor`` (Assumed), which is what the km prior is compared against.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
from pydantic import BaseModel

from glacies import __version__
from glacies.analytics.travel_times import zone_points
from glacies.cities import DemandConfig
from glacies.demand.feasibility import attainable
from glacies.demand.gravity import F64, U32, exponential, furness
from glacies.demand.production import (
    BOOL,
    COLUMN_NATURE,
    DemandError,
    TripEnds,
    TripEndStats,
    candidate_pairs,
    trip_ends,
)
from glacies.fsutil import rename_with_retry
from glacies.provenance import DataNature, sha256_file
from glacies.validate.gtfs.common import haversine_m

MANIFEST_NAME = "manifest.json"
REPORT_NAME = "BUILD_REPORT.md"
TRIP_ENDS_NAME = "trip_ends.parquet"
OD_NAME = "od.parquet"
TIME_BANDS_MIN = (15, 30, 45, 60, 90, 120)
# Row-error checkpoints kept in the manifest; the full history can be thousands of values.
HISTORY_POINTS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)
# Largest max-flow deficit, as a share of a block's trips, still treated as feasible.
FEASIBILITY_TOLERANCE = 1e-7

OD_NATURE: dict[str, DataNature] = {
    "cost_s": DataNature.SIMULATED,
    "trips": DataNature.ESTIMATED,
    "distance_km": DataNature.ESTIMATED,  # straight line x detour factor (Assumed)
}


class Convergence(BaseModel):
    iterations: int
    converged: bool
    tolerance: float
    max_row_error: float
    max_column_error: float
    row_error_at: dict[int, float]


class Attainability(BaseModel):
    """Pairs left out, and where the network cannot deliver the proxy's attraction totals."""

    walk_pairs_excluded: int  # fastest on foot at half or more of the departures
    blocks: int  # independent groups of zones after splitting at bottlenecks
    trips_moved: float  # Σ|D - D_proxy| / 2
    pairs_dropped: int  # reachable pairs that carry no trips in the balanced limit
    pairs_kept: int


class TripLength(BaseModel):
    mean_cost_min: float
    mean_straight_km: float
    mean_km: float  # straight line x detour factor
    detour_factor: float
    prior_mean_km: float
    accept_km: tuple[float, float]
    within_accepted_range: bool
    share_by_time_band: dict[str, float]  # "<=15", "15-30", ...


@dataclass
class DemandBuild:
    ends: TripEnds
    od: pl.DataFrame
    attainability: Attainability
    convergence: Convergence
    trip_length: TripLength
    beta_per_min: float


def _bands(cost_min: np.ndarray, trips: np.ndarray) -> dict[str, float]:
    total = float(trips.sum())
    bands: dict[str, float] = {}
    low = 0
    for high in TIME_BANDS_MIN:
        inside = (cost_min > low) & (cost_min <= high) if low else cost_min <= high
        bands[f"{low}-{high}" if low else f"<={high}"] = float(trips[inside].sum() / total)
        low = high
    return bands


@dataclass
class Prepared:
    """Everything up to Furness: it does not depend on β, so calibration reuses it."""

    ends: TripEnds  # with destination_proxy and the attainable destination
    pairs: pl.DataFrame  # origin_zone, dest_zone, cost_s: the pairs that can carry trips
    origin: U32
    dest: U32
    cost_min: F64
    productions: F64
    attractions: F64
    straight_km: F64  # zone point to zone point, per pair
    attainability: Attainability
    detour_factor: float


def prepare_demand(
    zones: pl.DataFrame,
    employment_score: np.ndarray,
    has_access: BOOL,
    matrix: pl.LazyFrame,
    demand: DemandConfig,
    *,
    detour_factor: float,
    walk_pairs: pl.DataFrame | None = None,
    walk_access: BOOL | None = None,
) -> Prepared:
    """Trip ends, attainable attractions and the pairs to balance; ``zones`` by ``zone_idx``.

    ``walk_pairs`` (origin_zone, dest_zone) are left out: walking is their fastest journey.
    ``walk_access`` marks the zones that may attract trips (default: ``has_access``).
    """
    zones = zones.sort("zone_idx")
    pairs = candidate_pairs(
        matrix, demand.cost.column, exclude_intrazonal=demand.exclude_intrazonal
    )
    before = pairs.height
    if walk_pairs is not None:
        pairs = pairs.join(walk_pairs, on=["origin_zone", "dest_zone"], how="anti")
    walk_excluded = before - pairs.height
    ends = trip_ends(zones, employment_score, has_access, pairs, demand, walk_access=walk_access)
    o = ends.table["origin"].to_numpy()
    d = ends.table["destination"].to_numpy()
    live = pairs.filter(
        pl.Series(o[pairs["origin_zone"].to_numpy()] > 0)
        & pl.Series(d[pairs["dest_zone"].to_numpy()] > 0)
    )
    origin = live["origin_zone"].to_numpy().astype(np.uint32)
    dest = live["dest_zone"].to_numpy().astype(np.uint32)
    feasible = attainable(origin, dest, o, d, tolerance=FEASIBILITY_TOLERANCE)
    live = live.filter(pl.Series(feasible.keep))
    ends.table = ends.table.rename({"destination": "destination_proxy"}).with_columns(
        pl.Series("destination", feasible.attractions)
    )
    points = zone_points(zones).select("zone_idx", "lat", "lon")
    straight = (
        live.select("origin_zone", "dest_zone")
        .join(points.rename({"zone_idx": "origin_zone"}), on="origin_zone", how="left")
        .join(
            points.rename({"zone_idx": "dest_zone", "lat": "lat_to", "lon": "lon_to"}),
            on="dest_zone",
            how="left",
        )
        .select(
            haversine_m(pl.col("lat"), pl.col("lon"), pl.col("lat_to"), pl.col("lon_to")) / 1000
        )
        .to_series()
        .to_numpy()
    )
    return Prepared(
        ends=ends,
        pairs=live,
        origin=origin[feasible.keep],
        dest=dest[feasible.keep],
        cost_min=live["cost_s"].to_numpy().astype(np.float64) / 60,
        productions=o,
        attractions=feasible.attractions,
        straight_km=np.asarray(straight, dtype=np.float64),
        attainability=Attainability(
            walk_pairs_excluded=walk_excluded,
            blocks=feasible.blocks,
            trips_moved=feasible.trips_moved,
            pairs_dropped=int((~feasible.keep).sum()),
            pairs_kept=int(feasible.keep.sum()),
        ),
        detour_factor=detour_factor,
    )


def balance(
    prepared: Prepared,
    demand: DemandConfig,
    beta_per_min: float,
    *,
    tolerance: float | None = None,
    initial_b: F64 | None = None,
) -> tuple[DemandBuild, F64]:
    """The balanced OD matrix for one β, and Furness's column factors (to warm-start the next).

    ``tolerance`` overrides ``[demand.gravity] tolerance`` (calibration sweeps use a coarser one).
    """
    g = demand.gravity
    tol = g.tolerance if tolerance is None else tolerance
    balanced = furness(
        prepared.origin,
        prepared.dest,
        exponential(prepared.cost_min, beta_per_min),
        prepared.productions,
        prepared.attractions,
        tolerance=tol,
        max_iterations=g.max_iterations,
        initial_b=initial_b,
    )
    convergence = Convergence(
        iterations=balanced.iterations,
        converged=balanced.converged,
        tolerance=tol,
        max_row_error=balanced.max_row_error,
        max_column_error=balanced.max_column_error,
        row_error_at={
            k: balanced.row_error_history[k - 1]
            for k in (*HISTORY_POINTS, balanced.iterations)
            if k <= balanced.iterations
        },
    )
    if not balanced.converged:
        raise DemandError(
            f"Furness did not converge in {balanced.iterations} iterations: largest row error "
            f"{balanced.max_row_error:.3g} (tolerance {tol:g})"
        )
    detour = prepared.detour_factor
    od = prepared.pairs.select(
        "origin_zone",
        "dest_zone",
        "cost_s",
        pl.Series("trips", balanced.trips),
        pl.Series("distance_km", prepared.straight_km * detour),
    ).filter(pl.col("trips") > 0)
    trips = balanced.trips
    total = float(trips.sum())
    straight = float((prepared.straight_km * trips).sum() / total)
    mean_km = straight * detour
    prior = demand.priors.trip_length
    trip_length = TripLength(
        mean_cost_min=float((prepared.cost_min * trips).sum() / total),
        mean_straight_km=straight,
        mean_km=mean_km,
        detour_factor=detour,
        prior_mean_km=prior.mean_km,
        accept_km=prior.accept_km,
        within_accepted_range=prior.accept_km[0] <= mean_km <= prior.accept_km[1],
        share_by_time_band=_bands(prepared.cost_min, trips),
    )
    build = DemandBuild(
        ends=prepared.ends,
        od=od,
        attainability=prepared.attainability,
        convergence=convergence,
        trip_length=trip_length,
        beta_per_min=beta_per_min,
    )
    return build, balanced.b


def build_demand(
    zones: pl.DataFrame,
    employment_score: np.ndarray,
    has_access: BOOL,
    matrix: pl.LazyFrame,
    demand: DemandConfig,
    *,
    detour_factor: float,
    walk_pairs: pl.DataFrame | None = None,
) -> DemandBuild:
    """Trip ends and the balanced OD matrix at ``[demand.gravity] beta_per_min``."""
    prepared = prepare_demand(
        zones,
        employment_score,
        has_access,
        matrix,
        demand,
        detour_factor=detour_factor,
        walk_pairs=walk_pairs,
    )
    return balance(prepared, demand, demand.gravity.beta_per_min)[0]


# --- outputs ----------------------------------------------------------------------------------


class DemandInput(BaseModel):
    stage: str
    manifest_sha256: str


def od_version(
    builder_version: str, demand: DemandConfig, beta_per_min: float, inputs: list[DemandInput]
) -> str:
    """Short id of everything an OD matrix depends on: the same id means the same matrix."""
    payload = json.dumps(
        {
            "builder": builder_version,
            "demand": demand.model_dump(mode="json"),
            "beta_per_min": beta_per_min,
            "inputs": [i.model_dump() for i in inputs],
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class DemandManifest(BaseModel):
    city: str
    scenario: str
    version: str  # od_version(...): changes whenever any input, setting or the code version does
    builder_version: str
    nature: DataNature
    inputs: list[DemandInput]
    demand: DemandConfig  # every prior with its source and verified flag
    column_nature: dict[str, dict[str, DataNature]]
    beta_per_min: float  # the β this matrix was balanced with
    trip_ends: TripEndStats
    attainability: Attainability
    convergence: Convergence
    trip_length: TripLength
    od_pairs: int
    outputs: dict[str, str]


def write_demand(
    build: DemandBuild,
    out_dir: Path,
    *,
    city: str,
    scenario: str,
    demand: DemandConfig,
    inputs: list[DemandInput],
) -> DemandManifest:
    staging = out_dir.with_name(f".{out_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    outputs = {}
    for name, frame in ((TRIP_ENDS_NAME, build.ends.table), (OD_NAME, build.od)):
        # Rechunk so the bytes depend only on the rows (one row group per chunk otherwise).
        frame.rechunk().write_parquet(staging / name, compression="zstd", statistics=True)
        outputs[name] = sha256_file(staging / name)
    manifest = DemandManifest(
        city=city,
        scenario=scenario,
        version=od_version(__version__, demand, build.beta_per_min, inputs),
        builder_version=__version__,
        nature=DataNature.ESTIMATED,
        inputs=inputs,
        demand=demand,
        column_nature={TRIP_ENDS_NAME: COLUMN_NATURE, OD_NAME: OD_NATURE},
        beta_per_min=build.beta_per_min,
        trip_ends=build.ends.stats,
        attainability=build.attainability,
        convergence=build.convergence,
        trip_length=build.trip_length,
        od_pairs=build.od.height,
        outputs=outputs,
    )
    (staging / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (staging / REPORT_NAME).write_text(report(manifest, build), encoding="utf-8", newline="\n")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    rename_with_retry(staging, out_dir)
    return manifest


def _cite(name: str, value: str, source: str, verified: bool) -> str:
    return f"- {name}: {value} — {source}{'' if verified else ' (not verified)'}"


def report(m: DemandManifest, build: DemandBuild) -> str:
    p = m.demand.priors
    s, a, c, t = m.trip_ends, m.attainability, m.convergence, m.trip_length
    top = (
        build.ends.table.sort("destination", "zone_idx", descending=[True, False])
        .head(10)
        .select("zone_idx", "h3_cell", "destination")
    )
    top20 = build.ends.table["destination"].sort(descending=True).head(max(1, s.zones // 20))
    lines = [
        f"# Synthetic demand — `{m.city}` / `{m.scenario}` (Estimated)",
        "",
        f"Version `{m.version}` · builder {m.builder_version} · purpose "
        f"{m.demand.trip_purpose} · "
        f"{m.od_pairs:,} OD pairs with trips",
        "",
        "## Priors (Assumed)",
        "",
        _cite(
            "Trip rate",
            f"{p.trip_rate.value:g} per person (range {p.trip_rate.range[0]:g}-"
            f"{p.trip_rate.range[1]:g})",
            p.trip_rate.source,
            p.trip_rate.verified,
        ),
        _cite(
            "Transit share",
            f"{p.transit_share.value:g} (range {p.transit_share.range[0]:g}-"
            f"{p.transit_share.range[1]:g})",
            p.transit_share.source,
            p.transit_share.verified,
        ),
        _cite(
            "Mean trip length",
            f"{p.trip_length.mean_km:g} km (accepted {t.accept_km[0]:g}-{t.accept_km[1]:g} km)",
            p.trip_length.source,
            p.trip_length.verified,
        ),
        f"- Friction: exp(-{m.beta_per_min:g} x minutes of "
        f"`{m.demand.cost.column}` door-to-door time (Simulated); β from demand.toml "
        "(`glacies demand calibrate` reports the fit).",
        "",
        "## Trip ends",
        "",
        f"- Zones with a stop within the access walk or a ride to a station: "
        f"{s.zones_with_access:,} of {s.zones:,}, holding "
        f"{s.population_with_access / s.population:.1%} of the population (Estimated); "
        f"{s.zones_ride_only:,} of them ({s.population_ride_only:,.0f} people) only by the ride.",
        f"- Origins: {s.origin_zones:,} zones; destinations: {s.destination_zones:,} zones "
        f"holding {s.employment_share_kept:.1%} of the city's estimated employment.",
        f"- Left out: {s.population - s.population_with_access:,.0f} people without a stop "
        f"within the walk or a ride, and {s.population_unreachable:,.0f} with one that reaches no "
        "destination zone. Their trips are not modelled.",
        f"- **Trips: {s.trips:,.0f}** (ΣO = ΣD; Estimated). With the trip rate and transit "
        f"share both at the ends of their ranges: {s.trips_low:,.0f} to {s.trips_high:,.0f}.",
        "",
        "## Pairs and attainable attractions",
        "",
        f"{a.walk_pairs_excluded:,} reachable zone pairs are left out because walking all the "
        "way is their fastest journey at half or more of the departures (not transit trips).",
        "",
        f"Some destinations cannot receive their share of the employment proxy: the origins "
        f"that reach them by transit make too few trips (checked as a max flow). Splitting at "
        f"these bottlenecks gives {a.blocks} independent groups of zones; attractions are "
        f"rescaled within each, which moves **{a.trips_moved:,.0f} trips "
        f"({a.trips_moved / s.trips:.1%})** of attraction. {a.pairs_dropped:,} reachable "
        f"pairs carry no trips in the balanced result ({a.pairs_kept:,} do). Productions are "
        "unchanged.",
        "",
        "## Furness balancing",
        "",
        f"{'Converged' if c.converged else 'Did NOT converge'} in {c.iterations} iterations "
        f"(tolerance {c.tolerance:g}): largest row error {c.max_row_error:.2e}, column error "
        f"{c.max_column_error:.2e}.",
        "",
        "| Iteration | Largest row error |",
        "|---:|---:|",
        *(f"| {k} | {v:.2e} |" for k, v in c.row_error_at.items()),
        "",
        "## Trip length",
        "",
        f"- Mean door-to-door time: {t.mean_cost_min:.1f} min (Simulated time, Estimated trips).",
        f"- Mean distance: {t.mean_km:.1f} km = {t.mean_straight_km:.1f} km straight line x "
        f"{t.detour_factor:g} detour (Assumed). Prior {t.prior_mean_km:g} km, accepted "
        f"{t.accept_km[0]:g}-{t.accept_km[1]:g} km: "
        f"**{'within' if t.within_accepted_range else 'OUTSIDE'}** the range.",
        "",
        "| Door-to-door time (min) | Share of trips |",
        "|---|---:|",
        *(f"| {band} | {share:.1%} |" for band, share in t.share_by_time_band.items()),
        "",
        "## Destinations",
        "",
        f"The top 5 % of zones by attracted trips receive "
        f"{float(top20.sum()) / s.trips:.1%} of all trips.",
        "",
        "| Zone | H3 cell | Trips attracted |",
        "|---:|---|---:|",
        *(
            f"| {r['zone_idx']} | `{r['h3_cell']}` | {r['destination']:,.0f} |"
            for r in top.iter_rows(named=True)
        ),
        "",
        "## Column labels",
        "",
        *(
            f"- `{table}` `{column}`: {nature.value}"
            for table, columns in m.column_nature.items()
            for column, nature in columns.items()
        ),
        "",
    ]
    return "\n".join(lines)
