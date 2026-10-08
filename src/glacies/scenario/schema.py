"""Scenario files: a baseline reference plus an ordered list of mutations (PRD §29-30).

A scenario is a diff, never a copy of the network, so the file stays small and reviewable and
two scenarios can be compared by their mutations alone. Route and stop references use the GTFS
ids (``source_*_id``) a planner sees in the feed, not the dense ``*_idx`` indices, which change
whenever the network is rebuilt.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from glacies.model.transit.schema import MODE_BY_ROUTE_TYPE, OTHER_MODE
from glacies.routing.network import RouterError, parse_clock

SCHEMA_VERSION = 1
MODES = frozenset([*MODE_BY_ROUTE_TYPE.values(), OTHER_MODE])
BOARDING_POINT = 0  # stops.location_type for a stop vehicles call at

ClockTime = Annotated[str, Field(description="HH:MM or HH:MM:SS; hours may exceed 24.")]
GtfsId = Annotated[str, Field(min_length=1)]


class ScenarioError(Exception):
    """A scenario file that cannot be read, or that does not fit the baseline network."""


def parse_seconds(text: str) -> int:
    """``HH:MM[:SS]`` to seconds, as a ``ValueError`` for Pydantic validators."""
    try:
        return parse_clock(text)
    except RouterError as exc:
        raise ValueError(str(exc)) from exc


def _check_window(window: tuple[str, str]) -> tuple[str, str]:
    if parse_seconds(window[0]) >= parse_seconds(window[1]):
        raise ValueError(f"window {window[0]}-{window[1]} must end after it starts")
    return window


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _RouteRef(_Strict):
    route_id: GtfsId
    feed: str | None = Field(
        default=None,
        description="Dataset name (city.toml [network]); needed only if route_id is in two feeds.",
    )


class RemoveRoute(_RouteRef):
    """Drop every trip of a route."""

    type: Literal["remove_route"]


class ModifyHeadway(_RouteRef):
    """Change how often a route runs, inside ``window`` or over the whole day.

    ``headway_factor`` scales the existing timetable: the gaps between departures are multiplied
    by the factor, so an irregular timetable keeps its shape (0.5 doubles the frequency).
    ``headway_secs`` regularises it: the trips are replaced by evenly spaced departures.
    """

    type: Literal["modify_headway"]
    headway_factor: float | None = Field(default=None, gt=0, le=10)
    headway_secs: int | None = Field(default=None, gt=0)
    window: tuple[ClockTime, ClockTime] | None = None

    @model_validator(mode="after")
    def _one_rule(self) -> ModifyHeadway:
        if (self.headway_factor is None) == (self.headway_secs is None):
            raise ValueError("set exactly one of headway_factor and headway_secs")
        return self

    @field_validator("window")
    @classmethod
    def _window(cls, value: tuple[str, str] | None) -> tuple[str, str] | None:
        return None if value is None else _check_window(value)


class AddRoute(_Strict):
    """A new route with evenly spaced trips; running times come from ``speed_kmh`` (Assumed)."""

    type: Literal["add_route"]
    route_id: GtfsId = Field(description="New id; must not exist in any baseline feed.")
    name: str | None = None
    mode: str = "bus"
    feed: str | None = Field(
        default=None, description="Dataset of the stop ids; needed only if a stop id is ambiguous."
    )
    stops: list[GtfsId] = Field(min_length=2)
    return_stops: list[GtfsId] | None = Field(
        default=None,
        min_length=2,
        description="Stops in the other direction; omitted means the outbound stops reversed.",
    )
    one_way: bool = False
    headway_secs: int = Field(gt=0)
    span: tuple[ClockTime, ClockTime] = Field(description="First and last departure.")
    speed_kmh: float = Field(gt=0, le=120)
    dwell_secs: int | None = Field(
        default=None, ge=0, description="Stop dwell; omitted means the city default."
    )

    @field_validator("mode")
    @classmethod
    def _mode(cls, value: str) -> str:
        if value not in MODES:
            raise ValueError(f"unknown mode {value!r}; use one of {', '.join(sorted(MODES))}")
        return value

    @field_validator("span")
    @classmethod
    def _span(cls, value: tuple[str, str]) -> tuple[str, str]:
        return _check_window(value)

    @field_validator("stops", "return_stops")
    @classmethod
    def _no_repeats(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("a stop appears twice in one direction")
        return value

    @model_validator(mode="after")
    def _directions(self) -> AddRoute:
        if self.one_way and self.return_stops is not None:
            raise ValueError("a one_way route cannot have return_stops")
        return self

    def directions(self) -> list[list[str]]:
        """Stop sequences to build trips on, outbound first."""
        if self.one_way:
            return [self.stops]
        return [self.stops, self.return_stops or self.stops[::-1]]


Mutation = Annotated[RemoveRoute | ModifyHeadway | AddRoute, Field(discriminator="type")]


class Scenario(_Strict):
    """A named change to the baseline network, applied in ``mutations`` order."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    json_schema_ref: str | None = Field(
        default=None, alias="$schema", description="Editor hint; ignored by the engine."
    )
    schema_version: Literal[1]
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    base_network: Literal["baseline"] = "baseline"
    title: str = Field(min_length=1)
    description: str = ""
    expected_change: str = Field(
        default="", description="The planner's expected direction of change (PRD validation 5)."
    )
    mutations: list[Mutation] = Field(min_length=1)


def json_schema() -> dict[str, Any]:
    return Scenario.model_json_schema(by_alias=True)


def json_schema_text() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load_scenario(path: Path) -> Scenario:
    """Read a scenario file; the file name must be ``<scenario_id>.json``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ScenarioError(f"{path}: expected a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ScenarioError(
            f"{path}: schema_version {version!r} is not supported (this engine reads "
            f"{SCHEMA_VERSION})"
        )
    try:
        scenario = Scenario.model_validate(data)
    except ValidationError as exc:
        raise ScenarioError(f"{path}: {exc}") from exc
    if scenario.scenario_id != path.stem:
        raise ScenarioError(
            f"{path}: scenario_id {scenario.scenario_id!r} does not match the file name"
        )
    return scenario


@dataclass(frozen=True)
class Resolved:
    """Baseline indices for the ids a scenario mentions."""

    route_idx: dict[str, int]
    stop_idx: dict[str, int]


def _lookup(
    kind: str,
    table: pl.DataFrame,
    id_column: str,
    idx_column: str,
    source_id: str,
    feed: str | None,
    feed_idx: Mapping[str, int],
) -> int | str:
    """The index of ``source_id``, or a problem message."""
    rows = table.filter(pl.col(id_column) == source_id)
    if feed is not None:
        if feed not in feed_idx:
            return f"unknown feed {feed!r}; the network has {', '.join(sorted(feed_idx))}"
        rows = rows.filter(pl.col("feed_idx") == feed_idx[feed])
    if rows.height == 0:
        where = f" in feed {feed!r}" if feed else ""
        return f"{kind} {source_id!r} is not in the baseline network{where}"
    if rows.height > 1:
        return f"{kind} {source_id!r} is in several feeds; set 'feed'"
    return int(rows[idx_column][0])


def resolve(scenario: Scenario, tables: Mapping[str, pl.DataFrame]) -> Resolved:
    """Check every reference against the baseline tables and map it to an index.

    Collects all problems before raising, so a planner fixes a file in one pass. Mutations may
    only reference baseline routes, not routes added earlier in the same scenario.
    """
    feeds = tables["feeds"]
    feed_idx = dict(zip(feeds["dataset"].to_list(), feeds["feed_idx"].to_list(), strict=True))
    routes, stops, trips = tables["routes"], tables["stops"], tables["trips"]
    with_trips = set(trips["route_idx"].unique().to_list())
    existing_routes = set(routes["source_route_id"].to_list())
    boarding = set(stops.filter(pl.col("location_type") == BOARDING_POINT)["stop_idx"].to_list())

    problems: list[str] = []
    route_idx: dict[str, int] = {}
    stop_idx: dict[str, int] = {}
    removed: set[str] = set()
    added: set[str] = set()
    for n, mutation in enumerate(scenario.mutations, start=1):
        prefix = f"mutation {n} ({mutation.type}): "
        if isinstance(mutation, AddRoute):
            if mutation.route_id in existing_routes or mutation.route_id in added:
                problems.append(prefix + f"route {mutation.route_id!r} already exists")
            added.add(mutation.route_id)
            for stop_id in sorted({s for d in mutation.directions() for s in d}):
                found = _lookup(
                    "stop", stops, "source_stop_id", "stop_idx", stop_id, mutation.feed, feed_idx
                )
                if isinstance(found, str):
                    problems.append(prefix + found)
                    continue
                if found not in boarding:
                    problems.append(prefix + f"stop {stop_id!r} is a station, not a boarding point")
                stop_idx[stop_id] = found
            continue

        if mutation.route_id in added:
            problems.append(prefix + f"route {mutation.route_id!r} is added by this scenario")
            continue
        idx = _lookup(
            "route",
            routes,
            "source_route_id",
            "route_idx",
            mutation.route_id,
            mutation.feed,
            feed_idx,
        )
        if isinstance(idx, str):
            problems.append(prefix + idx)
            continue
        if mutation.route_id in removed:
            problems.append(prefix + f"route {mutation.route_id!r} was already removed")
        elif idx not in with_trips:
            problems.append(prefix + f"route {mutation.route_id!r} has no trips on the service day")
        if isinstance(mutation, RemoveRoute):
            removed.add(mutation.route_id)
        route_idx[mutation.route_id] = idx

    if problems:
        raise ScenarioError(f"scenario {scenario.scenario_id!r}:\n  " + "\n  ".join(problems))
    return Resolved(route_idx=route_idx, stop_idx=stop_idx)
