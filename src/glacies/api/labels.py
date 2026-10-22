"""Data-nature labels carried by every API response (PRD §56, CLAUDE.md rule 4).

Responses list each number they contain under ``fields``: its unit, how it was obtained and
what it means. The UI renders a badge from this block, so a quantity without a label cannot
reach the screen silently; ``tests/test_api_network.py`` checks every numeric field has one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from glacies.provenance import DataNature


class FieldInfo(BaseModel):
    nature: DataNature
    unit: str | None = Field(default=None, description="None for identifiers and labels.")
    description: str


class Labelled(BaseModel):
    """Base of every response that carries numbers."""

    fields: dict[str, FieldInfo] = Field(
        description="Unit and data nature of each numeric field in this response."
    )


def field(nature: DataNature, description: str, unit: str | None = None) -> FieldInfo:
    return FieldInfo(nature=nature, unit=unit, description=description)
