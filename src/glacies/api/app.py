"""FastAPI application entry point. Run with ``uvicorn glacies.api.app:app``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Thread

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from glacies import __version__
from glacies.api.routers import cities, network, results, routing, scenarios, simulations
from glacies.config import Settings, get_settings


class Health(BaseModel):
    status: str
    version: str


WEB_PAGES = ("/easy", "/pro")


def create_app(settings: Settings | None = None, redis: Redis | None = None) -> FastAPI:
    """Build the app; tests pass their own settings and Redis, the server reads the environment."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Seconds of router building happen in the background while the UI loads.
        Thread(target=routing.warm, args=(app.state.routers, settings), daemon=True).start()
        yield

    app = FastAPI(title="Glacies API", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.routers = {}  # city id -> routing.Planner, built once
    # Connects on first use: everything but simulations works without Redis running.
    app.state.redis = redis or Redis.from_url(settings.redis_url, socket_connect_timeout=2)

    async def redis_down(request: Request, exc: Exception) -> JSONResponse:
        detail = f"cannot reach Redis at {settings.redis_url}; run docker compose up -d"
        return JSONResponse(status_code=503, content={"detail": detail})

    # A refused port raises ConnectionError; on Windows an unanswered one times out instead.
    app.add_exception_handler(RedisConnectionError, redis_down)
    app.add_exception_handler(RedisTimeoutError, redis_down)

    # Map layers are megabytes of repetitive JSON; gzip shrinks them several-fold.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok", version=__version__)

    app.include_router(cities.router)
    app.include_router(network.router)
    app.include_router(routing.router)
    app.include_router(scenarios.router)
    app.include_router(results.listing)
    app.include_router(results.router)
    app.include_router(simulations.router)
    # The built web app (`pnpm build`), so one server is enough on a fresh machine. Mounted
    # last: /api routes match first.
    index = settings.web_dist / "index.html"
    if index.is_file():
        # The web app's pages other than / (ADR 0024) are the same document: the app reads the
        # path. Without these, reloading /easy would be a 404.
        for page in WEB_PAGES:
            app.add_api_route(page, lambda: FileResponse(index), include_in_schema=False)
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")
    return app


app = create_app()
