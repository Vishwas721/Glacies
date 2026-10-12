"""Trips that start at rail and bus terminals (Phase 5 M8, ADR 0016).

Passengers arriving by long-distance train or bus are not produced by any home zone, so the
metro stations at terminals are under-predicted by a home-based model. Each gateway in
``[demand.gateways]`` sends ``factor x daily_passengers`` trips from the zone containing it,
spread over destinations in proportion to the main purpose's attractions times the gravity
friction (singly constrained: the gateway's total is fixed, destinations are not balanced).

Trips are linear in ``factor``, so calibration builds them at factor 1 and scales.
"""

from __future__ import annotations

from dataclasses import dataclass

import h3
import numpy as np
import polars as pl

from glacies.cities import Gateways
from glacies.demand.gravity import F64, U32, exponential
from glacies.demand.production import DemandError


def gateway_zones(zones: pl.DataFrame, gateways: Gateways) -> pl.DataFrame:
    """name, zone_idx, daily_passengers: the zone whose H3 cell contains each gateway."""
    resolution = h3.get_resolution(zones["h3_cell"][0])
    found = pl.DataFrame(
        {
            "name": [g.name for g in gateways.stations],
            "h3_cell": [h3.latlng_to_cell(g.lat, g.lon, resolution) for g in gateways.stations],
            "daily_passengers": [g.daily_passengers for g in gateways.stations],
        }
    ).join(zones.select("zone_idx", "h3_cell"), on="h3_cell", how="left")
    outside = found.filter(pl.col("zone_idx").is_null())["name"].to_list()
    if outside:
        raise DemandError(f"gateways outside the zones: {', '.join(outside)}")
    return found.select("name", "zone_idx", "daily_passengers")


@dataclass
class GatewayModel:
    """Everything but β and the factor: per pair, the gateway zone's passengers and the
    destination's attraction."""

    zones: pl.DataFrame  # name, zone_idx, daily_passengers (per gateway)
    pairs: pl.DataFrame  # origin_zone, dest_zone, cost_s
    group: U32  # per pair: position of its origin zone in ``sizes``
    sizes: F64  # daily passengers per gateway zone (gateways sharing a zone add up)
    attraction: F64  # per pair: the destination's attraction
    cost_min: F64
    distance_km: F64  # straight line x detour factor (Assumed)


def prepare_gateways(
    found: pl.DataFrame, pairs: pl.DataFrame, attractions: F64, distance_km: F64
) -> GatewayModel:
    """``pairs`` (origin_zone, dest_zone, cost_s) are the candidate transit pairs and
    ``distance_km`` their distances; ``attractions`` is indexed by zone."""
    by_zone = found.group_by("zone_idx").agg(pl.col("daily_passengers").sum()).sort("zone_idx")
    zone = by_zone["zone_idx"].to_numpy()
    rows = pairs.with_columns(pl.Series("distance_km", distance_km)).filter(
        pl.col("origin_zone").is_in(pl.Series(zone).implode())
        & pl.Series(attractions[pairs["dest_zone"].to_numpy()] > 0)
    )
    reached = set(rows["origin_zone"].unique().to_list())
    stranded = found.filter(~pl.col("zone_idx").is_in(sorted(reached)))["name"].to_list()
    if stranded:
        raise DemandError(
            f"gateways whose zone reaches no destination by transit: {', '.join(stranded)}"
        )
    origin = rows["origin_zone"].to_numpy()
    return GatewayModel(
        zones=found,
        pairs=rows.select("origin_zone", "dest_zone", "cost_s"),
        group=np.searchsorted(zone, origin).astype(np.uint32),
        sizes=by_zone["daily_passengers"].to_numpy().astype(np.float64),
        attraction=attractions[rows["dest_zone"].to_numpy()].astype(np.float64),
        cost_min=rows["cost_s"].to_numpy().astype(np.float64) / 60,
        distance_km=rows["distance_km"].to_numpy().astype(np.float64),
    )


def gateway_od(model: GatewayModel, beta_per_min: float, factor: float) -> pl.DataFrame:
    """origin_zone, dest_zone, cost_s, trips, distance_km for one β and factor."""
    weight = model.attraction * exponential(model.cost_min, beta_per_min)
    total = np.bincount(model.group, weights=weight, minlength=model.sizes.size)
    trips = factor * model.sizes[model.group] * weight / total[model.group]
    return model.pairs.with_columns(
        pl.Series("trips", trips), pl.Series("distance_km", model.distance_km)
    ).filter(pl.col("trips") > 0)
