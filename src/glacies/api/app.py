"""FastAPI application entry point. Run with ``uvicorn glacies.api.app:app``."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from glacies import __version__


class Health(BaseModel):
    status: str
    version: str


app = FastAPI(title="Glacies API", version=__version__)


@app.get("/api/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", version=__version__)
