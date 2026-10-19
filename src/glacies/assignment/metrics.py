"""Assignment metrics: per route, per metro station and for the city (Phase 6 M2, PRD §31).

Every metric is **Simulated** (Estimated demand on the timetable). Distances are straight lines
between consecutive stops (Estimated), so passenger-km run a little short of road distances.
"Crowding" is the share of passenger-km travelled on segments above design capacity
(load > seats + 6 standees/m²) among vehicles leaving a stop in the report window.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import polars as pl
from pydantic import BaseModel

from glacies.assignment.aon import AonFlows
from glacies.cities import DemandCalibration
from glacies.demand.calibrate import Fit, fit, station_sets

F64 = npt.NDArray[np.float64]
EARTH_RADIUS_KM = 6371.0088


def great_circle_km(lat0: F64, lon0: F64, lat1: F64, lon1: F64) -> F64:
    """Haversine distance in km between points given in degrees."""
    a0, a1 = np.radians(lat0), np.radians(lat1)
    dlat, dlon = a1 - a0, np.radians(lon1 - lon0)
    h = np.sin(dlat / 2) ** 2 + np.cos(a0) * np.cos(a1) * np.sin(dlon / 2) ** 2
    return np.asarray(2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(h)), dtype=np.float64)


def with_distances(loads: pl.DataFrame, stops: pl.DataFrame) -> pl.DataFrame:
    """``loads`` plus ``km``: great-circle distance from the segment's stop to the next."""
    coords = stops.select("stop_idx", "lat", "lon")
    table = loads.join(
        coords.rename({"stop_idx": "from_stop_idx", "lat": "lat0", "lon": "lon0"}),
        on="from_stop_idx",
        how="left",
    ).join(
        coords.rename({"stop_idx": "to_stop_idx", "lat": "lat1", "lon": "lon1"}),
        on="to_stop_idx",
        how="left",
    )
    km = great_circle_km(
        table["lat0"].to_numpy(),
        table["lon0"].to_numpy(),
        table["lat1"].to_numpy(),
        table["lon1"].to_numpy(),
    )
    return table.drop("lat0", "lon0", "lat1", "lon1").with_columns(pl.Series("km", km))


def _peak(report_window: tuple[int, int]) -> pl.Expr:
    start, end = report_window
    return (pl.col("departure") >= start) & (pl.col("departure") < end)


def route_metrics(
    loads: pl.DataFrame,
    trips: pl.DataFrame,
    routes: pl.DataFrame,
    report_window: tuple[int, int],
) -> pl.DataFrame:
    """Per route: boardings and passenger-km over the whole window; utilisation (passenger-km
    / capacity-km), the highest load factor and the share of segments above capacity among
    vehicles leaving a stop in the report window. Routes nobody rides are kept."""
    peak = _peak(report_window)
    return (
        loads.join(trips.select("trip_idx", "route_idx"), on="trip_idx")
        .group_by("route_idx")
        .agg(
            pl.col("trip_idx").filter(peak).n_unique().alias("peak_trips"),
            pl.col("boardings").sum(),
            (pl.col("load") * pl.col("km")).sum().alias("passenger_km"),
            (pl.col("load") * (pl.col("arrival") - pl.col("departure")).cast(pl.Float64))
            .sum()
            .truediv(3600)
            .alias("passenger_hours"),
            (
                (pl.col("load") * pl.col("km")).filter(peak).sum()
                / (pl.col("capacity").cast(pl.Float64) * pl.col("km")).filter(peak).sum()
            ).alias("peak_utilisation"),
            pl.col("load_factor").filter(peak).max().alias("peak_max_load_factor"),
            (pl.col("load_factor").filter(peak) > 1).mean().alias("peak_share_over_capacity"),
        )
        .join(routes.select("route_idx", "mode", "short_name"), on="route_idx", how="left")
        .select(
            "route_idx",
            "mode",
            "short_name",
            "peak_trips",
            "boardings",
            "passenger_km",
            "passenger_hours",
            "peak_utilisation",
            "peak_max_load_factor",
            "peak_share_over_capacity",
        )
        .sort("route_idx")
    )


def station_flows(flows: AonFlows, stations: pl.DataFrame) -> pl.DataFrame:
    """station_idx, name, lines, entries, exits: metro fare-gate passes per station."""
    entries = flows.gates.group_by(pl.col("entry_station").alias("station_idx")).agg(
        pl.col("trips").sum().alias("entries")
    )
    exits = flows.gates.group_by(pl.col("exit_station").alias("station_idx")).agg(
        pl.col("trips").sum().alias("exits")
    )
    return (
        stations.select("station_idx", "name", "lines")
        .join(entries, on="station_idx", how="left")
        .join(exits, on="station_idx", how="left")
        .with_columns(pl.col("entries", "exits").fill_null(0.0))
        .sort("station_idx")
    )


class CityMetrics(BaseModel):
    """City aggregates per transit trip (minutes) and of the vehicles (PRD §31). Simulated."""

    mean_travel_min: float
    mean_in_vehicle_min: float
    mean_waiting_min: float
    mean_walking_min: float
    mean_riding_min: float  # ride to a station (auto, two-wheeler), board-only access
    transfers_per_trip: float
    share_riding_to_station: float
    passenger_km: float
    peak_crowded_pkm_share: float  # above design capacity, report window
    peak_crush_pkm_share: float  # above crush capacity, report window
    metro_entries: float  # fare-gate passes


def city_metrics(
    flows: AonFlows, loads: pl.DataFrame, report_window: tuple[int, int]
) -> CityMetrics:
    od = flows.od.filter(pl.col("transit") > 0)
    transit = float(od["transit"].sum())

    def mean(column: str) -> float:
        if transit <= 0:
            return 0.0
        return float((od[column] * od["transit"]).sum()) / transit

    parts = ["in_vehicle_min", "waiting_min", "walking_min", "riding_min"]
    peak = loads.filter(_peak(report_window))
    pkm = (peak["load"] * peak["km"]).to_numpy()
    total_pkm = float(pkm.sum())

    def share(mask: pl.Series) -> float:
        return float(pkm[mask.to_numpy()].sum()) / total_pkm if total_pkm > 0 else 0.0

    return CityMetrics(
        mean_travel_min=sum(mean(c) for c in parts),
        mean_in_vehicle_min=mean("in_vehicle_min"),
        mean_waiting_min=mean("waiting_min"),
        mean_walking_min=mean("walking_min"),
        mean_riding_min=mean("riding_min"),
        transfers_per_trip=mean("vehicles") - 1.0 if transit > 0 else 0.0,
        share_riding_to_station=float(od["ridden"].sum()) / transit if transit > 0 else 0.0,
        passenger_km=float((loads["load"] * loads["km"]).sum()),
        peak_crowded_pkm_share=share(peak["load_factor"] > 1),
        peak_crush_pkm_share=share(peak["crush_factor"] > 1),
        metro_entries=float(flows.gates["trips"].sum()),
    )


def station_fit(
    stations: pl.DataFrame, observed: pl.DataFrame, calibration: DemandCalibration
) -> tuple[pl.DataFrame, dict[str, Fit]]:
    """Simulated gate entries against observed entries (station_idx, observed), per set
    (training, held-out, excluded lines) exactly as demand calibration scores them."""
    table = (
        station_sets(stations, calibration)
        .join(observed, on="station_idx", how="left")
        .with_columns(pl.col("observed").fill_null(0.0))
    )
    fits = {}
    for which in sorted(table["set"].unique().to_list()):
        rows = table.filter(pl.col("set") == which)
        if rows["observed"].sum() > 0:
            fits[which] = fit(rows["entries"].to_numpy(), rows["observed"].to_numpy())
    return table, fits
