"""``optimise.toml``: which routes the frequency optimiser may change, and how (Phase 8).

Everything city-specific about the search lives here: the trunk routes, the headway set, the
window whose departures are rewritten, the layover per terminal (Assumed) and the load limit.
The fleet is estimated from the baseline timetable unless the file states it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from glacies.cities import CityConfigError
from glacies.scenario.schema import GtfsId, parse_seconds


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OptimiseRoute(_Strict):
    route_id: GtfsId = Field(description="GTFS route_id, as scenario files use it.")
    feed: str | None = Field(default=None, description="Dataset name, if route_id is ambiguous.")
    label: str = Field(min_length=1, description="What a planner calls it (the route number).")


class Optimise(_Strict):
    routes: list[OptimiseRoute] = Field(min_length=1, max_length=5)  # PRD §36
    headways_min: list[int] = Field(min_length=2)
    window: tuple[str, str] = Field(
        description="Departures from the first stop in this window are regularised (both "
        "directions); outside it the timetable is unchanged."
    )
    layover_min: float = Field(ge=0, description="Per terminal, added to the round trip.")
    max_load_factor: float = Field(
        gt=0,
        description="Limit on a route's peak-hour passenger-km over design capacity-km, "
        "estimated as baseline x new headway / current headway.",
    )
    fleet_vehicles: int | None = Field(
        default=None, gt=0, description="Vehicles available; omitted means the baseline need."
    )
    source: str = ""

    @field_validator("headways_min")
    @classmethod
    def _headways(cls, value: list[int]) -> list[int]:
        if any(h <= 0 for h in value) or value != sorted(set(value)):
            raise ValueError("headways_min must be positive, increasing and without repeats")
        return value

    @field_validator("window")
    @classmethod
    def _window(cls, value: tuple[str, str]) -> tuple[str, str]:
        if parse_seconds(value[0]) >= parse_seconds(value[1]):
            raise ValueError(f"window {value[0]}-{value[1]} must end after it starts")
        return value

    @field_validator("routes")
    @classmethod
    def _distinct(cls, value: list[OptimiseRoute]) -> list[OptimiseRoute]:
        keys = [(r.feed, r.route_id) for r in value]
        if len(set(keys)) != len(keys):
            raise ValueError("a route appears twice")
        return value

    def window_s(self) -> tuple[int, int]:
        return parse_seconds(self.window[0]), parse_seconds(self.window[1])


class _OptimiseFile(_Strict):
    optimise: Optimise


def load_optimise(path: Path) -> Optimise:
    """Parse and validate an ``optimise.toml`` file."""
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError:
        raise CityConfigError(f"optimise config not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise CityConfigError(f"invalid TOML in {path}: {exc}") from exc
    try:
        return _OptimiseFile.model_validate(raw).optimise
    except ValidationError as exc:
        raise CityConfigError(f"invalid optimise config {path}:\n{exc}") from exc
