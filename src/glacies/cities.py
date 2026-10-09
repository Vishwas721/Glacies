"""City configuration (``cities/<city>/city.toml``).

The engine is city-agnostic: everything that differs between cities is read from this file.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from glacies.model.transit.schema import MODE_BY_ROUTE_TYPE, OTHER_MODE
from glacies.provenance import DataNature


class CityConfigError(ValueError):
    """The city configuration is missing or invalid."""


class _Strict(BaseModel):
    # Forbid unknown keys so a typo in city.toml fails loudly instead of being ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)


class CityInfo(_Strict):
    id: str
    name: str
    country: str
    timezone: str
    crs_projected: str
    bbox: tuple[float, float, float, float] = Field(
        description="WGS84 [min_lon, min_lat, max_lon, max_lat]."
    )

    @model_validator(mode="after")
    def _check_bbox(self) -> CityInfo:
        min_lon, min_lat, max_lon, max_lat = self.bbox
        if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
            raise ValueError(f"bbox must be [min_lon, min_lat, max_lon, max_lat], got {self.bbox}")
        return self


class Zoning(_Strict):
    system: Literal["h3"]
    resolution: int = Field(ge=0, le=15)
    building_confidence_thresholds: list[float] = Field(
        default_factory=lambda: [0.65, 0.75],
        description="Open Buildings confidence cut-offs; zone totals are kept for each (Assumed).",
    )

    @model_validator(mode="after")
    def _check_thresholds(self) -> Zoning:
        ts = self.building_confidence_thresholds
        if not ts or any(not 0 < t <= 1 for t in ts) or sorted(set(ts)) != ts:
            raise ValueError("building_confidence_thresholds must be ascending, unique, in (0, 1]")
        return self


class CoverageReference(_Strict):
    """An external count of routes to compare a feed against. Usually Assumed, not Observed."""

    route_count_min: int = Field(gt=0)
    route_count_max: int = Field(gt=0)
    source: str
    verified: bool

    @model_validator(mode="after")
    def _check_range(self) -> CoverageReference:
        if self.route_count_min > self.route_count_max:
            raise ValueError("route_count_min must be <= route_count_max")
        return self


class Source(_Strict):
    kind: str
    mode: str | None = None
    source: str
    url: str
    license: str
    verified: bool
    nature: DataNature
    notes: str = ""
    download_url: str | None = Field(
        default=None, description="Direct file URL for `glacies ingest fetch`; None if manual."
    )
    route_number_pattern: str | None = Field(
        default=None,
        description="GTFS feeds only: regex whose first match in route_short_name is the "
        "customer-facing route number, so variants of one route are counted once.",
    )
    exclude_route_pattern: str | None = Field(
        default=None,
        description="GTFS feeds only: routes whose short or long name matches this regex are "
        "non-revenue (e.g. test runs) and are left out of the canonical network.",
    )
    coverage_reference: CoverageReference | None = None

    @model_validator(mode="after")
    def _check_patterns(self) -> Source:
        for name in ("route_number_pattern", "exclude_route_pattern"):
            pattern = getattr(self, name)
            if pattern is not None:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ValueError(f"invalid {name}: {exc}") from exc
        return self


class Network(_Strict):
    """Which feeds form the canonical transit network, and for which day."""

    feeds: list[str] = Field(min_length=1)
    service_date: date = Field(description="The single day whose timetable is modelled.")
    drop_implausible_speed_trips: bool = True


DEFAULT_WALK_HIGHWAYS = (
    "residential", "service", "footway", "path", "pedestrian", "steps", "living_street",
    "track", "unclassified", "tertiary", "tertiary_link", "secondary", "secondary_link",
    "primary", "primary_link", "trunk", "trunk_link", "corridor", "cycleway", "bridleway",
    "platform", "road",
)  # fmt: skip


class Walk(_Strict):
    """Which OSM ways pedestrians can use, and how stops attach to them. All Assumed."""

    highways: list[str] = Field(default_factory=lambda: list(DEFAULT_WALK_HIGHWAYS))
    exclude_foot: list[str] = Field(default_factory=lambda: ["no", "private", "use_sidepath"])
    exclude_access: list[str] = Field(default_factory=lambda: ["no", "private"])
    allow_foot: list[str] = Field(
        default_factory=lambda: ["yes", "designated", "permissive"],
        description="foot= values that override an excluded access= value.",
    )
    max_snap_m: float = Field(default=300.0, gt=0)
    snap_to_largest_component: bool = True


class Routing(_Strict):
    """Journey-planning parameters (Phase 2). All Assumed."""

    max_rounds: int = Field(default=4, ge=1, le=10, description="Vehicles per journey.")
    walking_speed_m_s: float = Field(default=1.2, gt=0)
    max_access_walk_m: float = Field(default=800.0, gt=0)
    max_transfer_walk_m: float = Field(default=400.0, ge=0)
    min_transfer_time_s: int = Field(default=60, ge=0)
    station_entry_s: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Seconds to walk onto a stop of a mode from outside its station (entrance, security,"
            " stairs). Changes between platforms of one station are free."
        ),
    )

    @model_validator(mode="after")
    def _check_entry_modes(self) -> Routing:
        known = {*MODE_BY_ROUTE_TYPE.values(), OTHER_MODE}
        for mode, seconds in self.station_entry_s.items():
            if mode not in known:
                raise ValueError(f"station_entry_s: unknown mode {mode!r}")
            if seconds < 0:
                raise ValueError(f"station_entry_s: {mode} must be >= 0")
        return self


class ProxyWeights(_Strict):
    """One weighting of the employment proxy (Phase 3). Assumed."""

    name: str = Field(min_length=1)
    building_area: float = Field(ge=0, le=1, description="Weight of the footprint-area share.")
    job_pois: float = Field(ge=0, le=1, description="Weight of the job-POI share.")
    building_confidence: float = Field(
        description="Open Buildings confidence cut-off; one of [zoning] thresholds."
    )

    @model_validator(mode="after")
    def _check_sum(self) -> ProxyWeights:
        if abs(self.building_area + self.job_pois - 1) > 1e-9:
            raise ValueError(f"weights of {self.name!r} must sum to 1")
        return self


class Attraction(_Strict):
    """Employment proxy per zone (Phase 3; reused by Phase 5 demand).

    The proxy's output is Estimated; every value configured here is Assumed.
    """

    baseline: ProxyWeights
    sensitivity: list[ProxyWeights] = Field(default_factory=list)
    job_poi_categories: list[str] = Field(min_length=1)
    opportunity_index_total: int = Field(
        gt=0, description="Display base of the Estimated Opportunity Index; never a job count."
    )
    validation_hubs: str | None = Field(
        default=None, description="GeoJSON of known employment hubs, relative to the city folder."
    )
    hub_pass_rank: float = Field(default=0.20, gt=0, le=1)
    hub_report_rank: float = Field(default=0.05, gt=0, le=1)
    hub_pass_share: float = Field(default=0.80, gt=0, le=1)

    @model_validator(mode="after")
    def _check_names(self) -> Attraction:
        names = [w.name for w in (self.baseline, *self.sensitivity)]
        if len(set(names)) != len(names):
            raise ValueError("attraction weighting names must be unique")
        return self


def _clock_seconds(text: str) -> int:
    hours, _, minutes = text.partition(":")
    if not (hours.isdigit() and minutes.isdigit() and len(minutes) == 2 and int(minutes) < 60):
        raise ValueError(f"invalid time {text!r}; use HH:MM")
    return int(hours) * 3600 + int(minutes) * 60


class Accessibility(_Strict):
    """Travel-time matrix and accessibility settings (Phase 3). All Assumed."""

    window_start: str = Field(default="07:30", description="First departure, HH:MM.")
    window_end: str = Field(default="09:30", description="End of the window (exclusive), HH:MM.")
    departure_step_s: int = Field(default=60, gt=0)
    percentiles: list[int] = Field(default_factory=lambda: [25, 50, 75])
    max_travel_time_min: int = Field(
        default=120, gt=0, le=1000, description="Longer trips are not stored (not reached)."
    )
    max_walk_only_m: float = Field(
        default=2000.0, ge=0, description="Zone to zone on foot, without transit."
    )
    thresholds_min: list[int] = Field(default_factory=lambda: [15, 30, 45, 60])
    headline_threshold_min: int = Field(default=45, description="Threshold of the summary metric.")
    headline_percentile: int = Field(default=50, description="Percentile of the summary metric.")
    edge_buffer_m: float = Field(
        default=5000.0,
        ge=0,
        description="Zones whose point is this close to the bbox edge are flagged: their "
        "destinations beyond the study area are missing.",
    )

    @model_validator(mode="after")
    def _check(self) -> Accessibility:
        if _clock_seconds(self.window_end) <= _clock_seconds(self.window_start):
            raise ValueError("window_end must be after window_start")
        ps = self.percentiles
        if not ps or sorted(set(ps)) != ps or not all(1 <= p <= 100 for p in ps):
            raise ValueError("percentiles must be ascending, unique, in 1..100")
        ts = self.thresholds_min
        if not ts or sorted(set(ts)) != ts or ts[0] <= 0:
            raise ValueError("thresholds_min must be ascending, unique and positive")
        if ts[-1] > self.max_travel_time_min:
            raise ValueError("thresholds_min cannot exceed max_travel_time_min")
        if self.headline_threshold_min not in ts:
            raise ValueError("headline_threshold_min must be one of thresholds_min")
        if self.headline_percentile not in ps:
            raise ValueError("headline_percentile must be one of percentiles")
        return self

    def departures(self) -> list[int]:
        """Departure times (seconds since midnight) in the half-open window."""
        start, end = _clock_seconds(self.window_start), _clock_seconds(self.window_end)
        return list(range(start, end, self.departure_step_s))


class ScenarioDefaults(_Strict):
    """Timetables of routes added by scenarios (Phase 4). All Assumed."""

    detour_factor: float = Field(
        default=1.15,
        ge=1,
        le=3,
        description="Road distance over straight-line distance between consecutive stops.",
    )
    dwell_s: int = Field(default=20, ge=0, description="Stop dwell when a route sets none.")


class CityConfig(_Strict):
    city: CityInfo
    zoning: Zoning
    network: Network | None = None
    walk: Walk = Field(default_factory=Walk)
    routing: Routing = Field(default_factory=Routing)
    attraction: Attraction | None = None
    accessibility: Accessibility = Field(default_factory=Accessibility)
    scenario: ScenarioDefaults = Field(default_factory=ScenarioDefaults)
    sources: dict[str, Source]

    @model_validator(mode="after")
    def _check_network_feeds(self) -> CityConfig:
        if self.network is not None:
            for feed in self.network.feeds:
                if feed not in self.sources:
                    raise ValueError(f"network feed {feed!r} is not a source")
                if self.sources[feed].kind != "gtfs":
                    raise ValueError(f"network feed {feed!r} is not a GTFS source")
            if len(set(self.network.feeds)) != len(self.network.feeds):
                raise ValueError("network feeds must be unique")
        return self

    @model_validator(mode="after")
    def _check_attraction_confidence(self) -> CityConfig:
        if self.attraction is not None:
            kept = self.zoning.building_confidence_thresholds
            for w in (self.attraction.baseline, *self.attraction.sensitivity):
                if w.building_confidence not in kept:
                    raise ValueError(
                        f"weighting {w.name!r}: building_confidence {w.building_confidence} is "
                        f"not one of [zoning] building_confidence_thresholds {kept}"
                    )
        return self

    def source(self, dataset: str) -> Source:
        try:
            return self.sources[dataset]
        except KeyError:
            known = ", ".join(sorted(self.sources))
            raise CityConfigError(
                f"unknown dataset {dataset!r} for city {self.city.id!r}; known: {known}"
            ) from None


# --- demand (cities/<city>/demand.toml, Phase 5) -----------------------------------------------


class Prior(_Strict):
    """An Assumed prior with the range used for sensitivity and its citation."""

    value: float = Field(gt=0)
    range: tuple[float, float]
    source: str = Field(min_length=1)
    verified: bool = Field(description="False if only secondary sources quoting it were checked.")

    @model_validator(mode="after")
    def _check_range(self) -> Prior:
        low, high = self.range
        if not 0 < low <= self.value <= high:
            raise ValueError(f"range {self.range} must contain value {self.value} and be > 0")
        return self


class TripLengthPrior(_Strict):
    """Mean trip length the demand model is checked against (definition of done)."""

    mean_km: float = Field(gt=0)
    accept_km: tuple[float, float]
    source: str = Field(min_length=1)
    verified: bool

    @model_validator(mode="after")
    def _check_range(self) -> TripLengthPrior:
        low, high = self.accept_km
        if not 0 < low <= self.mean_km <= high:
            raise ValueError(f"accept_km {self.accept_km} must contain mean_km {self.mean_km}")
        return self


class DemandPriors(_Strict):
    trip_rate: Prior = Field(description="Trips per person in the modelled period.")
    transit_share: Prior
    trip_length: TripLengthPrior

    @model_validator(mode="after")
    def _check_share(self) -> DemandPriors:
        if self.transit_share.range[1] > 1:
            raise ValueError("transit_share cannot exceed 1")
        return self


class DemandCost(_Strict):
    column: str = Field(
        pattern=r"^p\d{1,3}_s$", description="Travel-time matrix percentile used as the cost."
    )


class Gravity(_Strict):
    """Doubly constrained gravity model settings (Phase 5 M2)."""

    beta_per_min: float = Field(
        gt=0, description="Exponential friction exp(-beta x minutes). Assumed until calibrated."
    )
    tolerance: float = Field(
        default=1e-6, gt=0, lt=1, description="Largest relative row/column sum error allowed."
    )
    max_iterations: int = Field(default=1000, ge=1)


class DemandCalibration(_Strict):
    friction_function: Literal["exponential"]
    dataset: str = Field(description="Ridership source in city.toml (Observed).")
    snapshot: str
    hours: list[int] = Field(min_length=1, description="Tap-in hours counted, 0-23.")
    dates: list[date] = Field(min_length=1)
    exclude_lines: list[str] = Field(default_factory=list)
    objective: Literal["rmse_entry_share"]
    held_out_stations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> DemandCalibration:
        if sorted(set(self.hours)) != self.hours or not all(0 <= h <= 23 for h in self.hours):
            raise ValueError("hours must be ascending, unique, in 0..23")
        if sorted(set(self.dates)) != self.dates:
            raise ValueError("dates must be ascending and unique")
        if len(set(self.held_out_stations)) != len(self.held_out_stations):
            raise ValueError("held_out_stations must be unique")
        return self


class DemandConfig(_Strict):
    """Synthetic OD demand: priors (Assumed) and calibration against ridership (Observed)."""

    trip_purpose: str = Field(min_length=1)
    origins: Literal["transit_served_zones"] = Field(
        description="Zones that produce and attract trips: those with a stop within the access "
        "walk. Other zones reach only walkable zones in the travel-time matrix."
    )
    exclude_intrazonal: bool = True
    exclude_walk_pairs: bool = Field(
        default=True,
        description="Leave out zone pairs where walking all the way is fastest for at least "
        "half the departures: they are not transit trips.",
    )
    priors: DemandPriors
    cost: DemandCost
    gravity: Gravity
    calibration: DemandCalibration


class _DemandFile(_Strict):
    demand: DemandConfig


def load_demand(path: Path) -> DemandConfig:
    """Parse and validate a ``demand.toml`` file."""
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError:
        raise CityConfigError(f"demand config not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise CityConfigError(f"invalid TOML in {path}: {exc}") from exc
    try:
        return _DemandFile.model_validate(raw).demand
    except ValidationError as exc:
        raise CityConfigError(f"invalid demand config {path}:\n{exc}") from exc


def load_city(path: Path) -> CityConfig:
    """Parse and validate a ``city.toml`` file."""
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError:
        raise CityConfigError(f"city config not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise CityConfigError(f"invalid TOML in {path}: {exc}") from exc
    try:
        return CityConfig.model_validate(raw)
    except ValidationError as exc:
        raise CityConfigError(f"invalid city config {path}:\n{exc}") from exc
