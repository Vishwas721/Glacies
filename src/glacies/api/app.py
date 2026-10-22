"""FastAPI application entry point. Run with ``uvicorn glacies.api.app:app``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Thread

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from glacies import __version__
from glacies.api.routers import cities, network, routing, scenarios
from glacies.config import Settings, get_settings


class Health(BaseModel):
    status: str
    version: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app; tests pass their own settings, the server reads the environment."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Seconds of router building happen in the background while the UI loads.
        Thread(target=routing.warm, args=(app.state.routers, settings), daemon=True).start()
        yield

    app = FastAPI(title="Glacies API", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.routers = {}  # city id -> routing.Planner, built once
    # Map layers are megabytes of repetitive JSON; gzip shrinks them several-fold.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok", version=__version__)

    app.include_router(cities.router)
    app.include_router(network.router)
    app.include_router(routing.router)
    app.include_router(scenarios.router)
    return app


app = create_app()
