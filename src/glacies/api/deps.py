"""Request dependencies: settings, the requested city and its processed-data folder."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from glacies.cities import CityConfig, CityConfigError, load_city
from glacies.config import Settings

# City ids become folder names; anything else could walk out of cities/ or data/.
_CITY_ID = re.compile(r"^[a-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class City:
    config: CityConfig
    data: Path  # data/processed/<city>


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


def city_ids(settings: Settings) -> list[str]:
    """Cities with a ``city.toml``, sorted so listings are stable."""
    if not settings.cities_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in settings.cities_dir.iterdir()
        if _CITY_ID.match(p.name) and (p / "city.toml").is_file()
    )


def load(settings: Settings, city_id: str) -> City:
    if not _CITY_ID.match(city_id):
        raise HTTPException(404, f"unknown city {city_id!r}")
    try:
        config = load_city(settings.cities_dir / city_id / "city.toml")
    except CityConfigError:
        raise HTTPException(404, f"unknown city {city_id!r}") from None
    return City(config=config, data=settings.processed_dir / config.city.id)


def get_city(city: str, settings: SettingsDep) -> City:
    return load(settings, city)


CityDep = Annotated[City, Depends(get_city)]


def require(path: Path, command: str) -> Path:
    """``path`` if it was built, else a 404 that says which command builds it."""
    if not path.exists():
        raise HTTPException(404, f"{path.name} has not been built; run `{command}`")
    return path
