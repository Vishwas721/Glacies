# syntax=docker/dockerfile:1
# The Glacies API (which also serves the built web app) and the simulation worker, for
# `docker compose --profile app up` on a fresh machine (Phase 7 M9). Data is mounted, not baked.

# --- the web app -------------------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /app/web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
COPY schemas/ /app/schemas/
RUN pnpm build

# --- Python environment, with the Rust core built by maturin ---------------------------------
FROM python:3.11-slim-bookworm AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /usr/local/bin/uv
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# rust-toolchain.toml pins the compiler; rustup installs exactly that one.
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain none
WORKDIR /app
COPY . .
RUN rustup show active-toolchain || rustup toolchain install
RUN uv sync --locked --no-dev --no-editable
# Scenario cache keys include the engine commit; the image has no checkout, so record it now
# with the same rule the runner uses (glacies.scenario.runner.engine_versions).
RUN .venv/bin/python -c "from pathlib import Path; \
from glacies.pipeline import git_state; \
from glacies.scenario.runner import ENGINE_PATHS; \
commit, dirty = git_state(Path('/app'), ENGINE_PATHS); \
Path('ENGINE_COMMIT').write_text(commit or ''); \
Path('ENGINE_DIRTY').write_text('1' if dirty else '0')"

# --- runtime -------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm
# The osmium wheel links the system expat library; everything else ships in the wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/ENGINE_COMMIT /app/ENGINE_DIRTY /app/
COPY --from=web /app/web/dist /app/web/dist
COPY docker/entrypoint.sh /usr/local/bin/glacies-entrypoint
ENV PATH=/app/.venv/bin:$PATH \
    GLACIES_DATA_DIR=/app/data \
    GLACIES_CITIES_DIR=/app/cities \
    GLACIES_SCENARIOS_DIR=/app/scenarios \
    GLACIES_WEB_DIST=/app/web/dist
EXPOSE 8000
ENTRYPOINT ["glacies-entrypoint"]
CMD ["uvicorn", "glacies.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
