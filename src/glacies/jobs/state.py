"""What the API and the worker share about a simulation, kept in Redis (PRD §50).

RQ only runs the job; the record here is ours, so it survives RQ's result expiry and can say
which stage a run is in. Timestamps are for display and never enter a computation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from pydantic import BaseModel, Field
from redis import Redis

PREFIX = "glacies:sim:"
INDEX = "glacies:sims"  # sorted set of ids, scored by creation order
SEQUENCE = "glacies:sims:seq"
CANCEL = "glacies:sim-cancel:"

# Stage messages from the scenario runner start with these, in this order; the comparison
# against the baseline is the job's own last stage.
STAGES = (
    "applying mutations",
    "travel-time matrix",
    "accessibility",
    "assignment with crowding",
    "comparison",
)


class Status(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def finished(self) -> bool:
        return self in (Status.COMPLETED, Status.FAILED, Status.CANCELLED)


class Progress(BaseModel):
    stage: str | None = Field(default=None, description="One of the runner's stages.")
    stage_index: int | None = Field(default=None, description="0-based position in `stages`.")
    stages: list[str] = Field(default_factory=lambda: list(STAGES))
    message: str | None = Field(default=None, description="The runner's last stage message.")
    done: int | None = Field(default=None, description="Chunks done in the current stage.")
    total: int | None = Field(default=None, description="Chunks in the current stage.")


class Simulation(BaseModel):
    id: str
    city: str
    scenario_id: str
    scenario_file: str = Field(description="The snapshot of the scenario this run uses.")
    status: Status = Status.QUEUED
    progress: Progress = Field(default_factory=Progress)
    result_key: str | None = Field(default=None, description="Cache key of the result folder.")
    cached: bool | None = Field(default=None, description="The result already existed.")
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def create(self, sim: Simulation) -> None:
        order = self.redis.incr(SEQUENCE)
        self.save(sim)
        self.redis.zadd(INDEX, {sim.id: order})

    def save(self, sim: Simulation) -> None:
        self.redis.set(PREFIX + sim.id, sim.model_dump_json())

    def get(self, sim_id: str) -> Simulation | None:
        raw = cast(bytes | None, self.redis.get(PREFIX + sim_id))
        return None if raw is None else Simulation.model_validate_json(raw)

    def list(self, city: str | None = None) -> list[Simulation]:
        """Newest first."""
        ids = cast(list[bytes], self.redis.zrevrange(INDEX, 0, -1))
        sims = [s for s in (self.get(i.decode()) for i in ids) if s is not None]
        return [s for s in sims if city is None or s.city == city]

    def request_cancel(self, sim_id: str) -> None:
        self.redis.set(CANCEL + sim_id, b"1")

    def cancel_requested(self, sim_id: str) -> bool:
        return bool(self.redis.exists(CANCEL + sim_id))
