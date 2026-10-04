"""City configuration (``cities/<city>/city.toml``).

The engine is city-agnostic: everything that differs between cities is read from this file.
"""

from __future__ import annotations

import tomllib
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


class CityConfig(_Strict):
    city: CityInfo
    zoning: Zoning
    sources: dict[str, Source]

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
