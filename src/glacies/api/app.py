"""FastAPI application entry point. Run with ``uvicorn glacies.api.app:app``."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from glacies import __version__
from glacies.api.routers import cities, network
from glacies.config import Settings, get_settings


class Health(BaseModel):
    status: str
    version: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app; tests pass their own settings, the server reads the environment."""
    app = FastAPI(title="Glacies API", version=__version__)
    app.state.settings = settings or get_settings()
    # Map layers are megabytes of repetitive JSON; gzip shrinks them several-fold.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok", version=__version__)

    app.include_router(cities.router)
    app.include_router(network.router)
    return app


app = create_app()
