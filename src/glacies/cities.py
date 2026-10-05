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


class CityConfig(_Strict):
    city: CityInfo
    zoning: Zoning
    network: Network | None = None
    walk: Walk = Field(default_factory=Walk)
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

    def source(self, dataset: str) -> Source:
        try:
            return self.sources[dataset]
        except KeyError:
            known = ", ".join(sorted(self.sources))
            raise CityConfigError(
                f"unknown dataset {dataset!r} for city {self.city.id!r}; known: {known}"
            ) from None


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
