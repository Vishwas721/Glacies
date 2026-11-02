"""M5 toy case on the real engine: brute force 2 routes x 3 headways, then NSGA-II.

Toyville with two bus routes that each run both ways every 10 minutes from 06:00 to 11:00:
route 10 between stops A and B, route 20 between B and C (5 minutes a way, 5-minute layovers,
so a 20-minute round trip: 4, 2 or 1 vehicles at 5, 10 or 20 minutes). The fleet is 7, so
both routes every 5 minutes (8 vehicles) is never allowed. Every other vector goes through
the scenario engine and an all-or-nothing assignment of Toyville's baseline demand (12.8
transit trips). The exhaustive front is four vectors: 20/20, 20/10, 10/10 and 10/5; for
example 10/20 (15 vehicle-hours, 2.08 h waiting) loses to 20/10 (15, 1.98).
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pytest

from glacies.cities import load_assignment, load_city
from glacies.config import Settings
from glacies.model.transit.schema import TABLES
from glacies.optimise.config import Optimise, OptimiseRoute
from glacies.optimise.evaluator import AonEvaluator
from glacies.optimise.problem import HeadwayProblem, pareto_front
from glacies.optimise.routes import route_facts
from glacies.optimise.run import run_nsga2
from glacies.scenario.mutations import apply
from glacies.scenario.schema import parse_seconds
from tests import toy_city
from tests.gtfs_edit import copy_toy_feed

HEADWAYS = [5, 10, 20]
OPTIMISE = Optimise(
    routes=[OptimiseRoute(route_id="R1", label="10"), OptimiseRoute(route_id="R2", label="20")],
    headways_min=HEADWAYS,
    window=("06:00", "11:00"),
    layover_min=5,
    max_load_factor=1000.0,  # the load limit is checked by hand in test_optimise_problem
    fleet_vehicles=7,
)


def clock(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:00"


def frequent_feed(target: Path) -> Path:
    """The toy feed with routes 10 (A-B) and 20 (C-D) every 10 min; the metro trip stays."""
    feed = copy_toy_feed(target)
    (feed / "routes.txt").write_text(
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "R1,toy,10,A to B,3\nR2,toy,20,B to C,3\nR3,toy,M1,Central to D,1\n",
        encoding="utf-8",
        newline="\n",
    )
    trips = ["route_id,service_id,trip_id,shape_id,direction_id", "R3,WK,T4,,0"]
    times = ["trip_id,arrival_time,departure_time,stop_id,stop_sequence"]
    times += ["T4,23:58:00,23:58:30,P1,1", "T4,24:05:00,24:05:00,D,2"]
    for route, ends in (("R1", ("A", "B")), ("R2", ("B", "C"))):
        for direction, (first, last) in enumerate((ends, ends[::-1])):
            for start in range(6 * 3600, 11 * 3600 + 1, 600):
                trip = f"{route}-{direction}-{start}"
                trips.append(f"{route},WK,{trip},,{direction}")
                times.append(f"{trip},{clock(start)},{clock(start)},{first},1")
                times.append(f"{trip},{clock(start + 300)},{clock(start + 300)},{last},2")
    for name, lines in (("trips.txt", trips), ("stop_times.txt", times)):
        (feed / name).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (feed / "shapes.txt").unlink()
    return feed


@pytest.fixture(scope="module")
def city(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    tmp = tmp_path_factory.mktemp("toy-optimise")
    with pytest.MonkeyPatch.context() as mp:
        feed = frequent_feed(tmp / "feed")
        (tmp / "city").mkdir()
        processed = toy_city.build(tmp / "city", mp, feed)
        toy_city.assign(processed)
        shutil.rmtree(feed)
        yield processed


@pytest.fixture
def problem(city: Path, monkeypatch: pytest.MonkeyPatch) -> HeadwayProblem:
    data = city.parents[1]
    monkeypatch.setenv("GLACIES_CITIES_DIR", str(toy_city.FIXTURES / "cities"))
    monkeypatch.setenv("GLACIES_CITY", "toyville")
    monkeypatch.setenv("GLACIES_DATA_DIR", str(data))
    settings = Settings()
    config = load_city(settings.city_config_path)
    window = load_assignment(settings.assignment_config_path).assignment
    tables = {n: pl.read_parquet(city / "transit" / f"{n}.parquet") for n in TABLES}
    facts = route_facts(
        tables,
        pl.read_parquet(city / "assignment" / "baseline" / "loads.parquet"),
        OPTIMISE,
        assignment_window=(parse_seconds(window.window_start), parse_seconds(window.window_end)),
        report_window=window.report_window(),
    )
    return HeadwayProblem(OPTIMISE, facts, AonEvaluator(settings, config))


def test_route_facts_from_the_timetable(problem: HeadwayProblem) -> None:
    for facts in problem.facts:
        assert facts.directions == 2
        assert facts.running_s == 600  # 5 min each way
        assert facts.cycle_s == 1200  # plus 5 min at each end
        assert facts.headway_now_s == 600
        assert [facts.vehicles(h * 60) for h in HEADWAYS] == [4, 2, 1]


def test_current_headways_change_nothing(problem: HeadwayProblem, city: Path) -> None:
    tables = {n: pl.read_parquet(city / "transit" / f"{n}.parquet") for n in TABLES}
    applied = apply(
        tables, problem.scenario([10, 10]), load_city(Settings().city_config_path).scenario
    )
    assert [(c.trips_removed, c.trips_added) for c in applied.changes] == [(0, 0), (0, 0)]


def test_brute_force_front_is_recovered_by_nsga2(problem: HeadwayProblem) -> None:
    vectors = [[a, b] for a in HEADWAYS for b in HEADWAYS]
    every = {tuple(v): problem.evaluate(v) for v in vectors}
    assert not every[5, 5].feasible
    assert every[5, 5].waiting_hours is None
    assert problem.evaluator_calls == 8
    waiting = {k: e.waiting_hours for k, e in every.items() if e.waiting_hours is not None}
    assert all(w > 0 for w in waiting.values())
    # Less frequent service never shortens waits: each route's headway, the other held.
    for other in HEADWAYS:
        for keys in ([(h, other) for h in HEADWAYS], [(other, h) for h in HEADWAYS]):
            series = [waiting[k] for k in keys if k in waiting]
            assert series == sorted(series)
    brute = [e.headways_min for e in pareto_front(list(every.values()))]
    assert brute == [[20, 20], [20, 10], [10, 10], [10, 5]]

    calls = problem.evaluator_calls
    result = run_nsga2(problem, population=6, generations=15, seed=7)
    assert [e.headways_min for e in result.front] == brute
    assert all(e.feasible for e in result.front)
    assert problem.evaluator_calls == calls  # every candidate was already known
