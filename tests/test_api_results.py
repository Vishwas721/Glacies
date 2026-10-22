"""Crowding and flows on hand-made loads over Toyville's stops (report window 08:30-09:30).

Vehicles leaving A for B at 08:31 (30 aboard), 08:41 (90) and 09:31 (50), B for C at 08:35 (10)
and 08:02 (0.001, rounding residue), and A for B at 07:50 (5, before the demand window); every
vehicle has a design capacity of 60.
"""

from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from glacies.api.app import create_app
from glacies.config import Settings
from tests.test_api_network import assert_labelled

URL = "/api/cities/toyville/results/baseline"


def hm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 3600 + int(m) * 60


@pytest.fixture
def client(city_dir: Path) -> TestClient:
    stops = dict(
        pl.read_parquet(city_dir / "transit" / "stops.parquet")
        .select("source_stop_id", "stop_idx")
        .iter_rows()
    )
    a, b, c = stops["A"], stops["B"], stops["C"]
    rows = [
        (a, b, "08:31", 30.0),
        (a, b, "08:41", 90.0),
        (a, b, "09:31", 50.0),
        (b, c, "08:35", 10.0),
        (b, c, "08:02", 0.001),
        (a, b, "07:50", 5.0),
    ]
    folder = city_dir / "assignment" / "baseline"
    folder.mkdir(parents=True)
    pl.DataFrame(
        {
            "from_stop_idx": pl.Series([r[0] for r in rows], dtype=pl.UInt32),
            "to_stop_idx": pl.Series([r[1] for r in rows], dtype=pl.UInt32),
            "departure": pl.Series([hm(r[2]) for r in rows], dtype=pl.UInt32),
            "load": [r[3] for r in rows],
            "capacity": pl.Series([60] * len(rows), dtype=pl.UInt32),
            "vehicle": ["bus_standard"] * len(rows),
        }
    ).write_parquet(folder / "loads.parquet")
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    return TestClient(create_app(Settings()))


def by_pair(body: dict[str, object], *columns: str) -> dict[tuple[int, int], tuple[object, ...]]:
    pairs = body["pairs"]
    assert isinstance(pairs, dict)
    keys = list(zip(pairs["from_stop_idx"], pairs["to_stop_idx"], strict=True))
    values = [body[c] for c in columns]
    return {k: tuple(v[i] for v in values) for i, k in enumerate(keys)}  # type: ignore[index]


def test_crowding_sums_the_report_hour_per_stop_pair(client: TestClient) -> None:
    body = client.get(f"{URL}/crowding").json()

    rows = by_pair(body, "vehicles", "passengers", "load_factor", "max_load_factor")
    assert body["window"] == ["08:30", "09:30"]
    assert sorted(rows.values()) == [(1, 10.0, 0.167, 0.167), (2, 120.0, 1.0, 1.5)]
    assert body["pairs"]["mode"] == ["bus", "bus"]
    assert_labelled(body)


def test_flows_are_15_minute_frames_with_partial_ones_marked(client: TestClient) -> None:
    body = client.get(f"{URL}/flows").json()

    frames = [(f["start"], f["partial"], f["passenger_segments"]) for f in body["frames"]]
    assert frames == [
        ("08:00", True, 0.0),  # the 08:02 residue is dropped
        ("08:15", True, 0.0),
        ("08:30", False, 130.0),
        ("08:45", False, 0.0),
        ("09:00", False, 0.0),
        ("09:15", False, 0.0),
        ("09:30", True, 50.0),
    ]
    rows = sorted(
        zip(
            body["frame_idx"],
            body["pair_idx"],
            body["passengers"],
            body["load_factor"],
            strict=True,
        )
    )
    pair_of = list(zip(body["pairs"]["from_stop_idx"], body["pairs"]["to_stop_idx"], strict=True))
    assert [(f, pair_of[p], pax, lf) for f, p, pax, lf in rows] == [
        (2, pair_of[0], 120.0, 1.0),
        (2, pair_of[1], 10.0, 0.167),
        (6, pair_of[0], 50.0, 0.833),
    ]
    assert body["dropped_passengers"] == pytest.approx(0.001)
    assert_labelled(body)


def test_results_need_an_assignment_and_a_known_ref(city_dir: Path) -> None:
    client = TestClient(create_app(Settings()))

    assert client.get(f"{URL}/crowding").status_code == 404  # no assignment built
    assert client.get("/api/cities/toyville/results/0123/flows").status_code == 404
    assert client.get("/api/cities/toyville/results/..%5Cbaseline/flows").status_code == 404
    assert client.get(f"{URL}/metrics").status_code == 404  # the baseline compares with nothing
