"""Simulations (PRD §45-46): queue a scenario run, follow it, cancel it, read its results.

The run uses a snapshot of the scenario taken when it is queued, so editing the scenario
afterwards does not change a run in progress, and the record says exactly what was run.
"""

from __future__ import annotations

import secrets
import shutil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from redis import Redis

from glacies.api.deps import City, SettingsDep, load
from glacies.api.routers import results, scenarios
from glacies.jobs.state import Simulation, Status, Store, now
from glacies.jobs.worker import cancel_queued, enqueue

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


RedisDep = Annotated[Redis, Depends(get_redis)]


class SimulationRequest(BaseModel):
    city: str
    scenario_id: str


class SimulationCreated(BaseModel):
    job_id: str
    status: Status


@router.post("", response_model=SimulationCreated, status_code=202)
def create_simulation(
    body: SimulationRequest, settings: SettingsDep, redis: RedisDep
) -> SimulationCreated:
    city = load(settings, body.city)
    hit = scenarios.find(settings, city, body.scenario_id)
    if hit is None:
        raise HTTPException(404, f"no scenario {body.scenario_id!r}")
    if not (city.data / "accessibility" / "baseline" / "manifest.json").is_file():
        raise HTTPException(409, "no baseline to compare with; run `glacies build accessibility`")
    sim_id = f"sim_{secrets.token_hex(6)}"
    folder = settings.data_dir / "simulations" / sim_id
    folder.mkdir(parents=True)
    snapshot = folder / f"{body.scenario_id}.json"  # the runner wants <scenario_id>.json
    shutil.copyfile(hit[1], snapshot)
    sim = Simulation(
        id=sim_id,
        city=city.config.city.id,
        scenario_id=body.scenario_id,
        scenario_file=str(snapshot),
        created_at=now(),
    )
    store = Store(redis)
    store.create(sim)
    enqueue(redis, sim, settings.simulation_timeout_s)
    return SimulationCreated(job_id=sim_id, status=sim.status)


@router.get("", response_model=list[Simulation])
def list_simulations(
    redis: RedisDep, city: Annotated[str | None, Query(description="Only this city.")] = None
) -> list[Simulation]:
    return Store(redis).list(city)


def _get(redis: Redis, sim_id: str) -> Simulation:
    sim = Store(redis).get(sim_id)
    if sim is None:
        raise HTTPException(404, f"no simulation {sim_id!r}")
    return sim


@router.get("/{sim_id}", response_model=Simulation)
def get_simulation(sim_id: str, redis: RedisDep) -> Simulation:
    return _get(redis, sim_id)


@router.post("/{sim_id}/cancel", response_model=Simulation)
def cancel_simulation(sim_id: str, redis: RedisDep) -> Simulation:
    store = Store(redis)
    sim = _get(redis, sim_id)
    if sim.status.finished:
        raise HTTPException(409, f"{sim_id} has already {sim.status.value}")
    if sim.status is Status.QUEUED and cancel_queued(redis, sim_id):
        sim.status, sim.finished_at = Status.CANCELLED, now()
        store.save(sim)
        return sim
    store.request_cancel(sim_id)  # the job checks every half second and ends its child
    return sim


def _result(settings: SettingsDep, redis: Redis, sim_id: str) -> tuple[City, results.Result]:
    sim = _get(redis, sim_id)
    if sim.status is not Status.COMPLETED or sim.result_key is None:
        raise HTTPException(409, f"{sim_id} is {sim.status.value}, not completed")
    city = load(settings, sim.city)
    return city, results.resolve(city, sim.result_key)


@router.get("/{sim_id}/metrics", response_model=results.Metrics)
def simulation_metrics(sim_id: str, settings: SettingsDep, redis: RedisDep) -> results.Metrics:
    _, result = _result(settings, redis, sim_id)
    return results.metrics(result)


@router.get("/{sim_id}/accessibility", response_model=results.Accessibility)
def simulation_accessibility(
    sim_id: str,
    settings: SettingsDep,
    redis: RedisDep,
    percentile: results.PercentileQuery = None,
    threshold_min: results.ThresholdQuery = None,
) -> results.Accessibility:
    city, result = _result(settings, redis, sim_id)
    return results.accessibility(city, result, percentile, threshold_min)


@router.get("/{sim_id}/crowding", response_model=results.Crowding)
def simulation_crowding(sim_id: str, settings: SettingsDep, redis: RedisDep) -> results.Crowding:
    city, result = _result(settings, redis, sim_id)
    return results.crowding(settings, city, result)


@router.get("/{sim_id}/flows", response_model=results.Flows)
def simulation_flows(sim_id: str, settings: SettingsDep, redis: RedisDep) -> results.Flows:
    city, result = _result(settings, redis, sim_id)
    return results.flows(settings, city, result)


@router.get("/{sim_id}/changes", response_model=results.Changes)
def simulation_changes(sim_id: str, settings: SettingsDep, redis: RedisDep) -> results.Changes:
    city, result = _result(settings, redis, sim_id)
    return results.changes(city, result, top=10)
