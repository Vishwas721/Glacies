"""Results of the baseline or of one scenario run, aggregated for the map (PRD §42, §46).

A result is ``baseline`` or a scenario run's cache key (``data/processed/<city>/results/<key>``).
Nothing per trip or per passenger leaves the server: crowding is per directed stop pair over the
reporting hour, flows are the same pairs in 15-minute frames, accessibility is one slice of the
zone table. Everything here is Simulated except the zone population and capacities (Assumed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import polars as pl
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from glacies.api.deps import City, CityDep, SettingsDep
from glacies.api.labels import Labelled, field
from glacies.api.store import Memo, query
from glacies.cities import load_assignment
from glacies.config import Settings
from glacies.jobs.child import COMPARISON
from glacies.provenance import DataNature
from glacies.routing.network import clock
from glacies.scenario.compare import BASELINE
from glacies.scenario.runner import RUN_NAME, RunRecord

router = APIRouter(prefix="/api/cities/{city}/results/{result}", tags=["results"])
listing = APIRouter(prefix="/api/cities/{city}/results", tags=["results"])
_memo = Memo()
_KEY = re.compile(r"^[0-9a-f]{64}$")
FRAME_S = 900  # 15-minute playback frames (PRD §42)
MIN_PASSENGERS = 0.01  # rows below this are rounding residue of fractional expected flows
# Values are rounded for transport: 0.01 passenger and 0.001 of capacity are far below anything a
# map colour can show.
SIM = DataNature.SIMULATED
ASSUMED = DataNature.ASSUMED


@dataclass(frozen=True)
class Result:
    ref: str
    accessibility: Path
    transit: Path
    assignment: Path | None
    comparison: Path | None


def resolve(city: City, ref: str) -> Result:
    if ref == BASELINE:
        assigned = city.data / "assignment" / BASELINE
        return Result(
            ref,
            city.data / "accessibility" / BASELINE,
            city.data / "transit",
            assigned if (assigned / "manifest.json").is_file() else None,
            None,
        )
    folder = city.data / "results" / ref
    if not _KEY.match(ref) or not (folder / "run.json").is_file():
        raise HTTPException(404, f"no result {ref!r}")
    return Result(
        ref,
        folder / "accessibility",
        folder / "transit",
        folder / "assignment" if (folder / "assignment" / "manifest.json").is_file() else None,
        folder / COMPARISON if (folder / COMPARISON / "comparison.json").is_file() else None,
    )


def _assigned(result: Result) -> Path:
    if result.assignment is None:
        raise HTTPException(404, f"{result.ref} has no assignment; run `glacies build assignment`")
    return result.assignment


# --- metrics ------------------------------------------------------------------------------


class MetricRow(BaseModel):
    metric: str
    unit: str
    nature: str = Field(description="Data nature of this row's values.")
    baseline: float
    scenario: float
    delta: float


class Metrics(BaseModel):
    """Every row carries its own data nature; the rows are the PRD §31 comparison."""

    rows: list[MetricRow]


def metrics(result: Result) -> Metrics:
    if result.comparison is None:
        raise HTTPException(404, f"{result.ref} has no comparison with the baseline")
    table = pl.read_parquet(result.comparison / "metrics.parquet")
    return Metrics(
        rows=[
            MetricRow(
                metric=r["metric"],
                unit=r["unit"],
                nature=r["nature"],
                baseline=r["a"],
                scenario=r["b"],
                delta=r["delta"],
            )
            for r in table.iter_rows(named=True)
        ]
    )


# --- accessibility ------------------------------------------------------------------------


class Accessibility(Labelled):
    """Columns in ``zone_idx`` order, for one percentile and time threshold."""

    percentile: int
    threshold_min: int
    zone_idx: list[int]
    h3_cell: list[str]
    edge_zone: list[bool]
    est_jobs_share: list[float]
    population_share: list[float]
    est_jobs_share_delta: list[float] | None = Field(
        description="Scenario minus baseline; None for the baseline itself."
    )


PercentileQuery = Annotated[int | None, Query(description="Default: the headline percentile.")]
ThresholdQuery = Annotated[int | None, Query(description="Minutes; default: the headline.")]


def accessibility(
    city: City, result: Result, percentile: int | None, threshold_min: int | None
) -> Accessibility:
    s = city.config.accessibility
    p = s.headline_percentile if percentile is None else percentile
    t = s.headline_threshold_min if threshold_min is None else threshold_min
    if p not in s.percentiles or t not in s.thresholds_min:
        raise HTTPException(
            422, f"percentile in {s.percentiles} and threshold_min in {s.thresholds_min}"
        )
    path = result.accessibility / "accessibility.parquet"
    if not path.is_file():
        raise HTTPException(404, f"{result.ref} has no accessibility results")
    table = query(
        """
        SELECT zone_idx, h3_cell, edge_zone, est_jobs_share, population_share
        FROM read_parquet($path) WHERE percentile = $p AND threshold_min = $t ORDER BY zone_idx
        """,
        {"path": str(path), "p": p, "t": t},
    )
    delta = None
    if result.comparison is not None:
        deltas = query(
            """
            SELECT est_jobs_share_delta FROM read_parquet($path)
            WHERE percentile = $p AND threshold_min = $t ORDER BY zone_idx
            """,
            {"path": str(result.comparison / "zone_deltas.parquet"), "p": p, "t": t},
        )
        delta = deltas["est_jobs_share_delta"].to_list()
    return Accessibility(
        fields={
            "est_jobs_share": field(
                SIM,
                f"Share of the city's estimated jobs reachable within {t} min "
                f"(p{p} over the AM window).",
                "share",
            ),
            "population_share": field(
                SIM, f"Share of the city's population reachable within {t} min.", "share"
            ),
            "est_jobs_share_delta": field(SIM, "Scenario minus baseline.", "share"),
            "percentile": field(DataNature.ASSUMED, "Percentile over departure times.", "%"),
            "threshold_min": field(DataNature.ASSUMED, "Travel-time threshold.", "min"),
        },
        percentile=p,
        threshold_min=t,
        zone_idx=table["zone_idx"].to_list(),
        h3_cell=table["h3_cell"].to_list(),
        edge_zone=table["edge_zone"].to_list(),
        est_jobs_share=table["est_jobs_share"].to_list(),
        population_share=table["population_share"].to_list(),
        est_jobs_share_delta=delta,
    )


# --- crowding and flows --------------------------------------------------------------------


class Pairs(BaseModel):
    """Directed stop pairs, the segments both crowding and flows are drawn on."""

    from_stop_idx: list[int]
    to_stop_idx: list[int]
    coordinates: list[tuple[float, float, float, float]] = Field(
        description="[from_lon, from_lat, to_lon, to_lat]: a straight line (Assumed)."
    )
    mode: list[str] = Field(description="Vehicle family (bus or metro) of the pair's vehicles.")


class Crowding(Labelled):
    window: tuple[str, str] = Field(description="Vehicles leaving a stop in [start, end).")
    pairs: Pairs
    vehicles: list[int]
    passengers: list[float]
    load_factor: list[float]
    max_load_factor: list[float]


def _segments(result: Result, lo: int, hi: int, bin_s: int | None) -> pl.DataFrame:
    """Loads summed per directed stop pair (and per time bin) for vehicles leaving in [lo, hi)."""
    bin_expr = f"(departure // {int(bin_s)}) * {int(bin_s)}" if bin_s else "0"
    return query(
        f"""
        WITH l AS (
            SELECT from_stop_idx, to_stop_idx, {bin_expr} AS bin, load, capacity,
                   split_part(vehicle, '_', 1) AS mode
            FROM read_parquet($loads) WHERE departure >= $lo AND departure < $hi
        )
        SELECT l.from_stop_idx, l.to_stop_idx, l.bin, any_value(l.mode) AS mode,
               count(*) AS vehicles, sum(l.load) AS passengers, sum(l.capacity) AS capacity,
               max(l.load / l.capacity) AS max_load_factor,
               any_value(a.lon) AS from_lon, any_value(a.lat) AS from_lat,
               any_value(b.lon) AS to_lon, any_value(b.lat) AS to_lat
        FROM l
        JOIN read_parquet($stops) a ON a.stop_idx = l.from_stop_idx
        JOIN read_parquet($stops) b ON b.stop_idx = l.to_stop_idx
        GROUP BY l.from_stop_idx, l.to_stop_idx, l.bin
        ORDER BY l.bin, l.from_stop_idx, l.to_stop_idx
        """,
        {
            "loads": str(_assigned(result) / "loads.parquet"),
            "stops": str(result.transit / "stops.parquet"),
            "lo": lo,
            "hi": hi,
        },
    )


def _pairs(table: pl.DataFrame) -> Pairs:
    r = 6
    return Pairs(
        from_stop_idx=table["from_stop_idx"].to_list(),
        to_stop_idx=table["to_stop_idx"].to_list(),
        coordinates=list(
            zip(
                table["from_lon"].round(r).to_list(),
                table["from_lat"].round(r).to_list(),
                table["to_lon"].round(r).to_list(),
                table["to_lat"].round(r).to_list(),
                strict=True,
            )
        ),
        mode=table["mode"].to_list(),
    )


def _window(settings: Settings, city: City) -> tuple[int, int, int, int]:
    """(demand window start, end, crowding report start, end) in seconds."""
    w = load_assignment(settings.cities_dir / city.config.city.id / "assignment.toml").assignment
    departures = w.departures()
    lo, hi = w.report_window()
    return departures[0], departures[-1] + 60, lo, hi


def crowding(settings: Settings, city: City, result: Result) -> Crowding:
    _, _, lo, hi = _window(settings, city)
    loads = _assigned(result) / "loads.parquet"
    table = _memo.get(
        ("crowding", str(loads), lo, hi), [loads], lambda: _segments(result, lo, hi, None)
    )
    table = table.filter(pl.col("passengers") >= MIN_PASSENGERS)
    return Crowding(
        fields={
            "vehicles": field(SIM, "Vehicles leaving from_stop in the window.", "vehicles"),
            "passengers": field(SIM, "Passengers carried over the pair by those vehicles.", "pax"),
            "load_factor": field(
                SIM, "Passengers over the vehicles' summed design capacity (Assumed).", "ratio"
            ),
            "max_load_factor": field(SIM, "Highest load factor of one vehicle.", "ratio"),
        },
        window=(clock(lo), clock(hi)),
        pairs=_pairs(table),
        vehicles=table["vehicles"].to_list(),
        passengers=table["passengers"].round(2).to_list(),
        load_factor=(table["passengers"] / table["capacity"]).round(3).to_list(),
        max_load_factor=table["max_load_factor"].round(3).to_list(),
    )


class Frame(BaseModel):
    start: str
    partial: bool = Field(
        description="Outside the crowding report window: the model has no travellers leaving "
        "home before or after its demand window, so these frames are filling or draining."
    )
    passenger_segments: float = Field(
        description="Passengers summed over every pair: a measure of activity, not of people."
    )


class Flows(Labelled):
    frame_minutes: int
    demand_window: tuple[str, str] = Field(description="Trips leave home in [start, end).")
    report_window: tuple[str, str] = Field(description="Full frames: crowding is reported here.")
    frames: list[Frame]
    pairs: Pairs
    frame_idx: list[int] = Field(description="Index into `frames` of each row.")
    pair_idx: list[int] = Field(description="Index into `pairs` of each row.")
    passengers: list[float]
    load_factor: list[float]
    dropped_passengers: float = Field(description="Sum over rows below the display minimum.")


def flows(settings: Settings, city: City, result: Result) -> Flows:
    start, end, lo, hi = _window(settings, city)
    loads = _assigned(result) / "loads.parquet"
    # Riders who leave home by the end of the window can still be travelling hours later.
    table = _memo.get(
        ("flows", str(loads), start, end),
        [loads],
        lambda: _segments(result, start, end + 4 * 3600, FRAME_S),
    )
    kept = table.filter(pl.col("passengers") >= MIN_PASSENGERS)
    dropped = float(table["passengers"].to_numpy().sum() - kept["passengers"].to_numpy().sum())
    last = int(kept["bin"].to_numpy().max()) if kept.height else start
    bins = list(range(start, last + FRAME_S, FRAME_S))
    totals = dict(kept.group_by("bin").agg(pl.col("passengers").sum()).iter_rows())
    pair_table = kept.unique(["from_stop_idx", "to_stop_idx"], maintain_order=True).sort(
        "from_stop_idx", "to_stop_idx"
    )
    index = pair_table.select("from_stop_idx", "to_stop_idx").with_row_index("pair")
    rows = kept.join(index, on=["from_stop_idx", "to_stop_idx"], how="left", maintain_order="left")
    return Flows(
        fields={
            "passengers": field(
                SIM, "Passengers carried over the pair by vehicles leaving in the frame.", "pax"
            ),
            "load_factor": field(
                SIM, "Passengers over the vehicles' summed design capacity (Assumed).", "ratio"
            ),
            "frame_minutes": field(DataNature.ASSUMED, "Length of a frame.", "min"),
            "dropped_passengers": field(SIM, "Total left out as rounding residue.", "pax"),
            "passenger_segments": field(
                SIM, "A frame's passengers summed over all pairs (not distinct people).", "pax"
            ),
        },
        frame_minutes=FRAME_S // 60,
        demand_window=(clock(start), clock(end)),
        report_window=(clock(lo), clock(hi)),
        frames=[
            Frame(
                start=clock(b),
                partial=not (lo <= b and b + FRAME_S <= hi),
                passenger_segments=round(float(totals.get(b, 0.0)), 2),
            )
            for b in bins
        ],
        pairs=_pairs(pair_table),
        frame_idx=((rows["bin"] - start) // FRAME_S).cast(pl.Int64).to_list(),
        pair_idx=rows["pair"].cast(pl.Int64).to_list(),
        passengers=rows["passengers"].round(2).to_list(),
        load_factor=(rows["passengers"] / rows["capacity"]).round(3).to_list(),
        dropped_passengers=dropped,
    )


# --- what changed ------------------------------------------------------------------------

Coord = tuple[float, float]
KIND: dict[str, Literal["removed", "added", "modified"]] = {
    "remove_route": "removed",
    "add_route": "added",
    "modify_headway": "modified",
}


class ChangedRoute(BaseModel):
    mutation_idx: int = Field(description="Index of the change in the scenario's mutations.")
    kind: Literal["removed", "added", "modified"]
    route_id: str
    route_idx: list[int] = Field(description="Matching routes (usually one; feeds may repeat ids).")
    name: str | None
    mode: str | None
    trips_removed: int
    trips_added: int
    boardings_baseline: float | None
    boardings_scenario: float | None
    coordinates: list[list[Coord]] = Field(
        description="One line per stop pattern, stop to stop (Assumed)."
    )


class RouteDelta(BaseModel):
    route_idx: int
    name: str | None
    mode: str
    boardings_baseline: float
    boardings_scenario: float
    boardings_delta: float


class Changes(Labelled):
    routes: list[ChangedRoute]
    largest_boardings_changes: list[RouteDelta] = Field(
        description="Routes whose boardings changed most, either way: where riders moved."
    )


def _route_lines(transit: Path, route_idx: list[int]) -> dict[int, list[list[Coord]]]:
    if not route_idx:
        return {}
    table = query(
        """
        SELECT p.route_idx, ps.pattern_idx, s.lon, s.lat
        FROM read_parquet($patterns) p
        JOIN read_parquet($pattern_stops) ps USING (pattern_idx)
        JOIN read_parquet($stops) s USING (stop_idx)
        WHERE list_contains($routes, p.route_idx)
        ORDER BY p.route_idx, ps.pattern_idx, ps.position
        """,
        {
            "patterns": str(transit / "patterns.parquet"),
            "pattern_stops": str(transit / "pattern_stops.parquet"),
            "stops": str(transit / "stops.parquet"),
            "routes": route_idx,
        },
    )
    lines: dict[int, list[list[Coord]]] = {}
    for (route, _), group in table.group_by("route_idx", "pattern_idx", maintain_order=True):
        coords = list(zip(group["lon"].round(6), group["lat"].round(6), strict=True))
        lines.setdefault(int(str(route)), []).append(coords)
    return lines


def changes(city: City, result: Result, top: int) -> Changes:
    folder = city.data / "results" / result.ref
    if result.ref == BASELINE or not (folder / RUN_NAME).is_file():
        raise HTTPException(404, "the baseline has no changes")
    try:
        run = RunRecord.model_validate_json((folder / RUN_NAME).read_text(encoding="utf-8"))
    except ValidationError:
        raise HTTPException(404, f"{result.ref} is from an older runner; run it again") from None
    base_routes = pl.read_parquet(city.data / "transit" / "routes.parquet")
    scenario_routes = pl.read_parquet(result.transit / "routes.parquet")
    deltas = (
        pl.read_parquet(result.comparison / "route_deltas.parquet")
        if result.comparison and (result.comparison / "route_deltas.parquet").is_file()
        else None
    )
    boardings: dict[int, tuple[float, float]] = {}
    if deltas is not None:
        pairs = deltas.select("route_idx", "boardings_a", "boardings_b").iter_rows()
        boardings = {r: (a, b) for r, a, b in pairs}
    out = []
    for change in run.changes:
        kind = KIND.get(change.type, "modified")
        routes = base_routes if kind == "removed" else scenario_routes
        rows = routes.filter(pl.col("source_route_id") == change.route_id)
        idx = rows["route_idx"].to_list()
        lines = _route_lines(city.data / "transit" if kind == "removed" else result.transit, idx)
        a, b = (sum(boardings[i][k] for i in idx if i in boardings) for k in (0, 1))
        out.append(
            ChangedRoute(
                mutation_idx=change.mutation - 1,
                kind=kind,
                route_id=change.route_id,
                route_idx=idx,
                name=rows["short_name"][0] if rows.height else None,
                mode=rows["mode"][0] if rows.height else None,
                trips_removed=change.trips_removed,
                trips_added=change.trips_added,
                boardings_baseline=a if boardings else None,
                boardings_scenario=b if boardings else None,
                coordinates=[line for i in idx for line in lines.get(i, [])],
            )
        )
    largest: list[RouteDelta] = []
    if deltas is not None:
        biggest = deltas.sort(pl.col("boardings_delta").abs(), descending=True).head(top)
        largest = [
            RouteDelta(
                route_idx=r["route_idx"],
                name=r["short_name"],
                mode=r["mode"],
                boardings_baseline=r["boardings_a"],
                boardings_scenario=r["boardings_b"],
                boardings_delta=r["boardings_delta"],
            )
            for r in biggest.iter_rows(named=True)
        ]
    return Changes(
        fields={
            "trips_removed": field(ASSUMED, "Timetabled trips the change takes away.", "trips"),
            "trips_added": field(ASSUMED, "Timetabled trips the change adds.", "trips"),
            "boardings_baseline": field(SIM, "Boardings by the AM-peak demand, baseline.", "pax"),
            "boardings_scenario": field(SIM, "Boardings by the AM-peak demand, scenario.", "pax"),
            "boardings_delta": field(SIM, "Scenario minus baseline.", "pax"),
        },
        routes=out,
        largest_boardings_changes=largest,
    )


# --- endpoints ----------------------------------------------------------------------------


@router.get("/metrics", response_model=Metrics)
def get_metrics(city: CityDep, result: str) -> Metrics:
    return metrics(resolve(city, result))


@router.get("/accessibility", response_model=Accessibility)
def get_accessibility(
    city: CityDep,
    result: str,
    percentile: PercentileQuery = None,
    threshold_min: ThresholdQuery = None,
) -> Accessibility:
    return accessibility(city, resolve(city, result), percentile, threshold_min)


@router.get("/crowding", response_model=Crowding)
def get_crowding(city: CityDep, result: str, settings: SettingsDep) -> Crowding:
    return crowding(settings, city, resolve(city, result))


@router.get("/flows", response_model=Flows)
def get_flows(city: CityDep, result: str, settings: SettingsDep) -> Flows:
    return flows(settings, city, resolve(city, result))


@router.get("/changes", response_model=Changes)
def get_changes(
    city: CityDep,
    result: str,
    top: Annotated[int, Query(ge=1, le=100, description="How many route changes.")] = 10,
) -> Changes:
    return changes(city, resolve(city, result), top)


class ResultSummary(BaseModel):
    key: str
    scenario_id: str
    title: str
    finished_at: str
    assignment: bool = Field(description="The run assigned demand (crowding and flows exist).")
    compared: bool = Field(description="A comparison with the baseline was written.")


@listing.get("", response_model=list[ResultSummary])
def list_results(city: CityDep) -> list[ResultSummary]:
    """Scenario results on disk, newest first: the cache is the record of what was run, so
    results stay available when Redis (and the simulation records) are not."""
    folder = city.data / "results"
    found = []
    for run_file in sorted(folder.glob(f"*/{RUN_NAME}")) if folder.is_dir() else []:
        key = run_file.parent.name
        if not _KEY.match(key):
            continue
        try:
            run = RunRecord.model_validate_json(run_file.read_text(encoding="utf-8"))
        except ValidationError:
            continue  # written by an older runner; its cache key no longer matches anything
        found.append(
            ResultSummary(
                key=key,
                scenario_id=run.scenario_id,
                title=run.title,
                finished_at=run.finished_at,
                assignment=run.assignment,
                compared=(run_file.parent / COMPARISON / "comparison.json").is_file(),
            )
        )
    return sorted(found, key=lambda r: (r.finished_at, r.key), reverse=True)
