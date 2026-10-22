"""Journey planning on the baseline network (PRD §43), answered in-process.

Building a city's router takes seconds (2.8 s for Bengaluru in the Phase 2 benchmark) and a
plan tens of milliseconds, so the router is built on the first request and kept: plans then
stay well under the one-second limit above which work goes through the job queue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from typing import Literal

import glacies_raptor as gr
import numpy as np
import numpy.typing as npt
import polars as pl
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from glacies.api.deps import City, CityDep, load
from glacies.api.labels import Labelled, field
from glacies.config import Settings
from glacies.provenance import DataNature
from glacies.routing.network import Router, RouterError, clock, load_router, parse_clock

router = APIRouter(prefix="/api/cities/{city}", tags=["routing"])

LatLon = tuple[float, float]
Coord = tuple[float, float]  # [lon, lat]
_lock = Lock()
log = logging.getLogger(__name__)


class RouteRequest(BaseModel):
    origin: LatLon = Field(description="[lat, lon]", examples=[[12.9766, 77.5713]])
    destination: LatLon = Field(description="[lat, lon]", examples=[[12.9784, 77.6408]])
    departure_time: str = Field(description="HH:MM on the service date.", examples=["08:30"])

    @model_validator(mode="after")
    def _check(self) -> RouteRequest:
        for lat, lon in (self.origin, self.destination):
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("points are [lat, lon] in degrees")
        try:
            parse_clock(self.departure_time)
        except RouterError as exc:
            raise ValueError(str(exc)) from None
        return self


class Leg(BaseModel):
    kind: Literal["access", "ride", "transfer", "egress"]
    from_stop_idx: int | None
    to_stop_idx: int | None
    from_name: str | None
    to_name: str | None
    route_idx: int | None
    route_name: str | None
    mode: str | None
    board: str | None = Field(description="HH:MM, rides only.")
    alight: str | None = Field(description="HH:MM, rides only.")
    duration_s: int
    coordinates: list[Coord] = Field(
        description="[lon, lat] line: the stops passed on a ride, straight otherwise."
    )


class Journey(BaseModel):
    departure: str
    arrival: str
    travel_time_s: int
    in_vehicle_time_s: int
    waiting_time_s: int
    walking_time_s: int
    transfers: int
    legs: list[Leg]


class RouteResponse(Labelled):
    journeys: list[Journey] = Field(
        description="Pareto-optimal on arrival time and transfers; empty when none is found."
    )


@dataclass(frozen=True)
class Planner:
    """A city's router with the lookups that turn its journeys into responses."""

    router: Router
    names: dict[int, str]
    where: dict[int, Coord]
    trip_route: dict[int, int]
    route_label: dict[int, tuple[str, str]]  # route_idx -> (display name, mode)
    # Stop times sorted by (trip, position), and where each trip starts, to draw rides.
    calls: npt.NDArray[np.uint32]  # rows of (stop_idx, departure, arrival)
    trip_start: npt.NDArray[np.int64]

    @classmethod
    def build(cls, city: City) -> Planner:
        r = load_router(city.data, city.config.routing, city.config.city.crs_projected)
        stops = r.stops.select("stop_idx", "name", "lat", "lon")
        routes = r.routes.select(
            "route_idx", pl.coalesce("route_number", "short_name", "source_route_id"), "mode"
        )
        calls = pl.read_parquet(
            city.data / "transit" / "stop_times.parquet",
            columns=["trip_idx", "position", "stop_idx", "departure", "arrival"],
        ).sort("trip_idx", "position")
        trips = calls["trip_idx"].to_numpy()
        return cls(
            router=r,
            names=dict(stops.select("stop_idx", "name").iter_rows()),
            where={s: (round(lon, 6), round(lat, 6)) for s, _, lat, lon in stops.iter_rows()},
            trip_route=dict(r.trips.select("trip_idx", "route_idx").iter_rows()),
            route_label={i: (name, mode) for i, name, mode in routes.iter_rows()},
            calls=calls.select("stop_idx", "departure", "arrival").to_numpy().astype(np.uint32),
            trip_start=np.searchsorted(trips, np.arange(int(trips.max()) + 2)).astype(np.int64),
        )

    def stops_of(self, trip: int) -> list[tuple[int, int, int]]:
        """(stop, departure, arrival) of every call of a trip, in travel order."""
        lo, hi = self.trip_start[trip], self.trip_start[trip + 1]
        return [(int(a), int(b), int(c)) for a, b, c in self.calls[lo:hi]]


def planner(planners: dict[str, Planner], city: City) -> Planner:
    with _lock:  # one build per city, even when the first requests arrive together
        if city.config.city.id not in planners:
            try:
                planners[city.config.city.id] = Planner.build(city)
            except RouterError as exc:
                raise HTTPException(404, str(exc)) from None
        return planners[city.config.city.id]


def warm(planners: dict[str, Planner], settings: Settings) -> None:
    """Build the default city's router so the first journey request does not wait for it."""
    try:
        planner(planners, load(settings, settings.city))
    except HTTPException as exc:  # no such city or no network built: requests will say so
        log.info("router not warmed: %s", exc.detail)


@router.post("/route", response_model=RouteResponse)
def plan_route(body: RouteRequest, city: CityDep, request: Request) -> RouteResponse:
    min_lon, min_lat, max_lon, max_lat = city.config.city.bbox
    for lat, lon in (body.origin, body.destination):
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            raise HTTPException(422, f"[{lat}, {lon}] is outside the study area")
    planners: dict[str, Planner] = request.app.state.routers
    plan = planner(planners, city)
    try:
        found = plan.router.plan(body.origin, body.destination, parse_clock(body.departure_time))
    except RouterError as exc:
        raise HTTPException(422, str(exc)) from None

    start = (round(body.origin[1], 6), round(body.origin[0], 6))
    end = (round(body.destination[1], 6), round(body.destination[0], 6))
    where, names = plan.where, plan.names

    journeys = []
    for j in found:
        legs = []
        for leg in j.legs:
            # leg.route is the router's internal route (a stop sequence); the trip knows ours.
            route_idx = plan.trip_route[leg.trip_id] if leg.trip_id is not None else None
            name, mode = plan.route_label[route_idx] if route_idx is not None else (None, None)
            if leg.kind == "ride" and leg.trip_id is not None:
                line = [where[s] for s in _ride_stops(plan.stops_of(leg.trip_id), leg)]
            else:
                line = [
                    start if leg.from_stop is None else where[leg.from_stop],
                    end if leg.to_stop is None else where[leg.to_stop],
                ]
            legs.append(
                Leg(
                    kind=leg.kind,
                    from_stop_idx=leg.from_stop,
                    to_stop_idx=leg.to_stop,
                    from_name=names.get(leg.from_stop) if leg.from_stop is not None else None,
                    to_name=names.get(leg.to_stop) if leg.to_stop is not None else None,
                    route_idx=route_idx,
                    route_name=name,
                    mode=mode,
                    board=clock(leg.board) if leg.board is not None else None,
                    alight=clock(leg.alight) if leg.alight is not None else None,
                    duration_s=leg.duration,
                    coordinates=line,
                )
            )
        journeys.append(
            Journey(
                departure=clock(j.departure),
                arrival=clock(j.arrival),
                travel_time_s=j.travel_time,
                in_vehicle_time_s=j.in_vehicle_time,
                waiting_time_s=j.waiting_time,
                walking_time_s=j.walking_time,
                transfers=j.transfers,
                legs=legs,
            )
        )
    simulated = DataNature.SIMULATED
    return RouteResponse(
        fields={
            "travel_time_s": field(simulated, "Departure to arrival.", "s"),
            "in_vehicle_time_s": field(simulated, "Time on board.", "s"),
            "waiting_time_s": field(simulated, "Time at stops before boarding.", "s"),
            "walking_time_s": field(simulated, "Access, transfer and egress walks.", "s"),
            "transfers": field(simulated, "Vehicle changes.", "count"),
            "duration_s": field(simulated, "Length of the leg.", "s"),
        },
        journeys=journeys,
    )


def _ride_stops(stops: list[tuple[int, int, int]], leg: gr.Leg) -> list[int]:
    """The stops a ride passes, boarding and alighting stops included.

    A trip can call at the same stop twice (loops), so the ride starts at the call departing
    at the boarding time and ends at the call arriving at the alighting time.
    """
    out: list[int] = []
    for stop, departure, arrival in stops:
        if not out and stop == leg.from_stop and departure == leg.board:
            out.append(stop)
        elif out:
            out.append(stop)
            if stop == leg.to_stop and arrival == leg.alight:
                return out
    return [s for s in (leg.from_stop, leg.to_stop) if s is not None]  # not found: straight
