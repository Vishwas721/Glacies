"""Cities: what is configured, which outputs exist and which sources need attributing."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

from glacies.api.deps import CityDep, SettingsDep, city_ids, load
from glacies.provenance import DataNature

router = APIRouter(prefix="/api/cities", tags=["cities"])

# Outputs the UI can show, the folder holding each one's manifest and the command building it.
OUTPUTS: tuple[tuple[str, str, str], ...] = (
    ("transit", "transit", "glacies build transit"),
    ("walk", "walk", "glacies build walk"),
    ("zones", "zones", "glacies build zones"),
    ("attraction", "attraction", "glacies build attraction"),
    ("accessibility", "accessibility/baseline", "glacies build accessibility"),
    ("demand", "demand/baseline", "glacies build demand"),
    ("assignment", "assignment/baseline", "glacies build assignment"),
)


class CitySummary(BaseModel):
    id: str
    name: str
    country: str


class Output(BaseModel):
    name: str
    available: bool
    command: str = Field(description="The CLI command that builds this output.")


class Source(BaseModel):
    id: str
    kind: str
    source: str
    url: str
    license: str
    nature: DataNature
    verified: bool


class CityDetail(CitySummary):
    timezone: str
    bbox: tuple[float, float, float, float] = Field(
        description="WGS84 [min_lon, min_lat, max_lon, max_lat] (Assumed study area)."
    )
    service_date: date | None = Field(description="The single day whose timetable is modelled.")
    window: tuple[str, str] = Field(
        description="AM departure window of the travel-time matrix, [start, end) HH:MM."
    )
    outputs: list[Output]
    sources: list[Source] = Field(description="Every configured data source, for attribution.")


@router.get("", response_model=list[CitySummary])
def list_cities(settings: SettingsDep) -> list[CitySummary]:
    cities = []
    for city_id in city_ids(settings):
        info = load(settings, city_id).config.city
        cities.append(CitySummary(id=info.id, name=info.name, country=info.country))
    return cities


@router.get("/{city}", response_model=CityDetail)
def get_city(city: CityDep) -> CityDetail:
    config = city.config
    return CityDetail(
        id=config.city.id,
        name=config.city.name,
        country=config.city.country,
        timezone=config.city.timezone,
        bbox=config.city.bbox,
        service_date=config.network.service_date if config.network else None,
        window=(config.accessibility.window_start, config.accessibility.window_end),
        outputs=[
            Output(
                name=name, available=(city.data / folder / "manifest.json").is_file(), command=cmd
            )
            for name, folder, cmd in OUTPUTS
        ],
        sources=[
            Source(
                id=source_id,
                kind=s.kind,
                source=s.source,
                url=s.url,
                license=s.license,
                nature=s.nature,
                verified=s.verified,
            )
            for source_id, s in sorted(config.sources.items())
        ],
    )
