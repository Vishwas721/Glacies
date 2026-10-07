"""Type stubs for the Rust extension module ``glacies_raptor``.

Times are seconds since service-day midnight; stop indices are canonical ``stop_idx`` values.
"""

from typing import Literal

import numpy as np
import numpy.typing as npt

UNREACHED: int

U32 = npt.NDArray[np.uint32]
F64 = npt.NDArray[np.float64]

class Leg:
    kind: Literal["access", "ride", "transfer", "egress"]
    from_stop: int | None
    to_stop: int | None
    duration: int
    route: int | None
    trip_id: int | None
    board: int | None
    alight: int | None

class Journey:
    departure: int
    arrival: int
    travel_time: int
    transfers: int
    walking_time: int
    in_vehicle_time: int
    waiting_time: int
    legs: list[Leg]

class Timetable:
    @staticmethod
    def build(
        stop_count: int,
        trip_ids: U32,
        trip_starts: U32,
        stops: U32,
        arrivals: U32,
        departures: U32,
        footpath_from: U32,
        footpath_to: U32,
        footpath_seconds: U32,
        entry_stops: U32 | None = None,
        entry_stations: U32 | None = None,
        entry_seconds: U32 | None = None,
    ) -> Timetable: ...
    @property
    def stop_count(self) -> int: ...
    @property
    def route_count(self) -> int: ...
    @property
    def trip_count(self) -> int: ...
    @property
    def overtaking_splits(self) -> int: ...
    def entry_times(self) -> U32: ...
    def earliest_arrivals(
        self,
        origin_stops: U32,
        origin_seconds: U32,
        departure: int,
        max_rounds: int,
        min_transfer_time: int,
    ) -> U32: ...
    def range_arrivals(
        self,
        origin_stops: U32,
        origin_seconds: U32,
        departures: U32,
        max_rounds: int,
        min_transfer_time: int,
    ) -> npt.NDArray[np.uint32]: ...
    def range_arrivals_many(
        self,
        origins: list[tuple[U32, U32]],
        departures: U32,
        max_rounds: int,
        min_transfer_time: int,
    ) -> list[npt.NDArray[np.uint32]]: ...
    def zone_travel_times_many(
        self,
        origins: list[tuple[U32, U32, U32, U32]],
        departures: U32,
        zone_count: int,
        egress_zones: U32,
        egress_stops: U32,
        egress_seconds: U32,
        percentiles: npt.NDArray[np.uint8],
        max_travel_time: int,
        max_rounds: int,
        min_transfer_time: int,
    ) -> tuple[U32, U32, npt.NDArray[np.uint32]]: ...
    def plan(
        self,
        origin_stops: U32,
        origin_seconds: U32,
        departure: int,
        destination_stops: U32,
        destination_seconds: U32,
        max_rounds: int,
        min_transfer_time: int,
    ) -> list[Journey]: ...

class WalkGraph:
    def __init__(
        self, node_count: int, edge_from: U32, edge_to: U32, edge_length_m: F64
    ) -> None: ...
    def attach_stops(self, stops: U32, edges: U32, fractions: F64, offsets_m: F64) -> None: ...
    @property
    def node_count(self) -> int: ...
    @property
    def edge_count(self) -> int: ...
    def stops_within(
        self, edge: int, fraction: float, offset_m: float, max_m: float
    ) -> tuple[U32, F64]: ...
    def stop_to_stop(self, max_m: float) -> tuple[U32, U32, F64]: ...
