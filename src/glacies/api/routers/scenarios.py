"""Scenario files (PRD §44): the repository's, read-only, and the user's, editable.

A scenario is the Phase 4 JSON document (``schemas/scenario.schema.json``) and nothing else:
the file is what ``glacies scenario run`` reads, so the UI and the CLI run the same thing.
Every write is checked against the schema and the baseline network before it is saved.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal

import polars as pl
from fastapi import APIRouter, Body, HTTPException, Response
from pydantic import BaseModel, ValidationError

from glacies.api.deps import City, CityDep, SettingsDep
from glacies.config import Settings
from glacies.scenario.schema import Scenario, ScenarioError, resolve

router = APIRouter(prefix="/api/cities/{city}/scenarios", tags=["scenarios"])
_lock = Lock()
TABLES = ("feeds", "routes", "stops", "trips")
# The schema's scenario_id pattern; ids become file names, so nothing else may reach the disk.
_SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")


class ScenarioSummary(BaseModel):
    scenario_id: str
    title: str
    source: Literal["repository", "user"]
    editable: bool
    mutation_types: list[str]


class ScenarioRecord(BaseModel):
    source: Literal["repository", "user"]
    editable: bool
    scenario: Scenario


def _dirs(settings: Settings, city: City) -> dict[Literal["repository", "user"], Path]:
    city_id = city.config.city.id
    return {
        "repository": settings.scenarios_dir / city_id,
        "user": settings.user_scenarios_dir / city_id,
    }


def _find(settings: Settings, city: City, scenario_id: str) -> tuple[str, Path] | None:
    if not _SCENARIO_ID.match(scenario_id):
        return None
    for source, folder in _dirs(settings, city).items():
        path = folder / f"{scenario_id}.json"
        if path.is_file():
            return source, path
    return None


def _read(path: Path) -> Scenario:
    return Scenario.model_validate_json(path.read_text(encoding="utf-8"))


def _record(source: str, path: Path) -> ScenarioRecord:
    user = source == "user"
    return ScenarioRecord(
        source="user" if user else "repository", editable=user, scenario=_read(path)
    )


def _check(city: City, scenario: Scenario) -> None:
    """Refuse references to routes or stops the baseline network does not have."""
    transit = city.data / "transit"
    if not (transit / "routes.parquet").is_file():
        raise HTTPException(409, "no baseline network to check; run `glacies build transit`")
    tables = {name: pl.read_parquet(transit / f"{name}.parquet") for name in TABLES}
    try:
        resolve(scenario, tables)
    except ScenarioError as exc:
        raise HTTPException(422, str(exc)) from None


def _write(path: Path, scenario: Scenario) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = scenario.model_dump(mode="json", by_alias=True, exclude_none=True)
    staging = path.with_suffix(".json.tmp")
    staging.write_text(
        json.dumps(document, indent=4, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    os.replace(staging, path)  # a crash mid-write never leaves half a file


@router.get("", response_model=list[ScenarioSummary])
def list_scenarios(city: CityDep, settings: SettingsDep) -> list[ScenarioSummary]:
    found: dict[str, ScenarioSummary] = {}
    for source, folder in _dirs(settings, city).items():
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            if path.stem in found:
                continue  # the repository's copy wins, as in _find
            try:
                scenario = _read(path)
            except (ValidationError, OSError):
                continue  # `glacies scenario check` reports broken files; the list skips them
            found[path.stem] = ScenarioSummary(
                scenario_id=scenario.scenario_id,
                title=scenario.title,
                source=source,
                editable=source == "user",
                mutation_types=[m.type for m in scenario.mutations],
            )
    return [found[k] for k in sorted(found)]


@router.get("/{scenario_id}", response_model=ScenarioRecord)
def get_scenario(scenario_id: str, city: CityDep, settings: SettingsDep) -> ScenarioRecord:
    hit = _find(settings, city, scenario_id)
    if hit is None:
        raise HTTPException(404, f"no scenario {scenario_id!r}")
    return _record(*hit)


@router.post("", response_model=ScenarioRecord, status_code=201)
def create_scenario(scenario: Scenario, city: CityDep, settings: SettingsDep) -> ScenarioRecord:
    _check(city, scenario)
    with _lock:
        if _find(settings, city, scenario.scenario_id) is not None:
            raise HTTPException(409, f"scenario {scenario.scenario_id!r} already exists")
        path = _dirs(settings, city)["user"] / f"{scenario.scenario_id}.json"
        _write(path, scenario)
    return _record("user", path)


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7396 JSON Merge Patch: objects merge key by key, ``null`` deletes, the rest replaces."""
    if not isinstance(patch, dict):
        return patch
    merged = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = merge_patch(merged.get(key), value)
    return merged


@router.patch("/{scenario_id}", response_model=ScenarioRecord)
def update_scenario(
    scenario_id: str,
    city: CityDep,
    settings: SettingsDep,
    patch: Annotated[
        dict[str, Any],
        Body(media_type="application/merge-patch+json", examples=[{"title": "New title"}]),
    ],
) -> ScenarioRecord:
    with _lock:
        path = _editable(settings, city, scenario_id)
        current = _read(path).model_dump(mode="json", by_alias=True, exclude_none=True)
        if patch.get("scenario_id", scenario_id) != scenario_id:
            raise HTTPException(422, "scenario_id cannot change; create a new scenario instead")
        try:
            scenario = Scenario.model_validate(merge_patch(current, patch))
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False)) from None
        _check(city, scenario)
        _write(path, scenario)
    return _record("user", path)


@router.delete("/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str, city: CityDep, settings: SettingsDep) -> Response:
    with _lock:
        _editable(settings, city, scenario_id).unlink()
    return Response(status_code=204)


def _editable(settings: Settings, city: City, scenario_id: str) -> Path:
    hit = _find(settings, city, scenario_id)
    if hit is None:
        raise HTTPException(404, f"no scenario {scenario_id!r}")
    source, path = hit
    if source != "user":
        raise HTTPException(403, f"{scenario_id!r} is a repository scenario; copy it to edit it")
    return path
