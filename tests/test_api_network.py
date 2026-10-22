"""Read API on Toyville: cities, routes, stops, stop-pair segments and zones.

Toyville on Tuesday 2026-10-13 runs R1 (A -> B -> C) at 08:00 and 08:10 and the metro M1
(platform P1 of Central Station -> D) at 23:58; R2 runs on weekends only. The AM window is
the default 07:30-09:30.
"""

from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

from glacies.api.app import create_app
from glacies.config import Settings

# Keys that hold identifiers or geometry, not quantities, so need no data-nature label.
NOT_QUANTITIES = {"coordinates", "bbox", "resolution", "direction_id", "stops", "routes_idx"}


@pytest.fixture
def client(city_dir: Path) -> TestClient:
    return TestClient(create_app(Settings()))


def numeric_keys(value: Any, key: str = "") -> set[str]:
    """Every key in a JSON document whose value is a number or a list of numbers."""
    if isinstance(value, dict):
        return set().union(*(numeric_keys(v, k) for k, v in value.items()))
    if isinstance(value, list):
        if value and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value):
            return {key}
        return set().union(set(), *(numeric_keys(v, key) for v in value))
    if isinstance(value, int | float) and not isinstance(value, bool):
        return {key}
    return set()


def assert_labelled(body: dict[str, Any]) -> None:
    quantities = {
        k for k in numeric_keys(body) if not k.endswith("_idx") and k not in NOT_QUANTITIES
    }
    assert quantities <= set(body["fields"]), quantities - set(body["fields"])


def test_lists_and_describes_cities(client: TestClient) -> None:
    assert client.get("/api/cities").json() == [
        {"id": "toyville", "name": "Toyville", "country": "XX"}
    ]

    city = client.get("/api/cities/toyville").json()

    assert city["service_date"] == "2026-10-13"
    assert city["window"] == ["07:30", "09:30"]
    available = {o["name"]: o["available"] for o in city["outputs"]}
    assert (available["transit"], available["walk"], available["assignment"]) == (True, True, False)
    assert {s["id"] for s in city["sources"]} >= {"toy_gtfs", "toy_osm"}


@pytest.mark.parametrize("city", ["nowhere", "..", "Toyville"])
def test_unknown_or_unsafe_city_ids_are_not_found(client: TestClient, city: str) -> None:
    assert client.get(f"/api/cities/{city}").status_code == 404


def test_routes_count_trips_on_the_service_date_and_in_the_window(client: TestClient) -> None:
    body = client.get("/api/cities/toyville/routes").json()

    by_id = {r["route_id"]: r for r in body["routes"]}
    assert body["window"] == {"start": "07:30", "end": "09:30"}
    assert (by_id["R1"]["trips"], by_id["R1"]["window_trips"], by_id["R1"]["mode"]) == (2, 2, "bus")
    assert (by_id["R3"]["trips"], by_id["R3"]["window_trips"], by_id["R3"]["mode"]) == (
        1,
        0,
        "metro",
    )
    assert "R2" not in by_id or by_id["R2"]["trips"] == 0  # weekend service only
    assert_labelled(body)


def test_routes_filter_by_mode_and_window(client: TestClient) -> None:
    metro = client.get("/api/cities/toyville/routes", params={"mode": "metro"}).json()
    late = client.get("/api/cities/toyville/routes", params={"start": "08:05", "end": "09:00"})

    assert [r["route_id"] for r in metro["routes"]] == ["R3"]
    r1 = next(r for r in late.json()["routes"] if r["route_id"] == "R1")
    assert r1["window_trips"] == 1  # only the 08:10


@pytest.mark.parametrize(("start", "end"), [("09:00", "08:00"), ("8am", "09:00")])
def test_bad_windows_are_rejected(client: TestClient, start: str, end: str) -> None:
    response = client.get("/api/cities/toyville/routes", params={"start": start, "end": end})

    assert response.status_code == 422


def test_route_detail_draws_each_pattern_stop_to_stop(client: TestClient) -> None:
    routes = client.get("/api/cities/toyville/routes").json()["routes"]
    r1 = next(r for r in routes if r["route_id"] == "R1")

    body = client.get(f"/api/cities/toyville/routes/{r1['route_idx']}").json()

    assert body["route"] == r1
    [pattern] = body["features"]
    assert pattern["geometry"]["coordinates"] == [[77.02, 12.02], [77.03, 12.03], [77.04, 12.04]]
    assert (pattern["properties"]["trips"], pattern["properties"]["window_trips"]) == (2, 2)
    assert len(pattern["properties"]["stops"]) == 3
    assert body["fields"]["geometry"]["nature"] == "assumed"
    assert_labelled(body)
    assert client.get("/api/cities/toyville/routes/999").status_code == 404


def test_stops_include_stations_served_through_their_platforms(client: TestClient) -> None:
    body = client.get("/api/cities/toyville/stops").json()

    by_id = {f["properties"]["stop_id"]: f for f in body["features"]}
    assert set(by_id) == {"S1", "P1", "A", "B", "C", "D"}  # the entrance E1 is not a stop
    station = by_id["S1"]["properties"]
    assert (station["station"], station["modes"], station["routes"]) == (True, ["metro"], 1)
    assert by_id["A"]["properties"]["modes"] == ["bus"]
    assert by_id["A"]["geometry"]["coordinates"] == [77.02, 12.02]
    assert_labelled(body)


def test_network_has_one_segment_per_directed_stop_pair(client: TestClient) -> None:
    body = client.get("/api/cities/toyville/network").json()

    stop_ids = {
        f["properties"]["stop_idx"]: f["properties"]["stop_id"]
        for f in client.get("/api/cities/toyville/stops").json()["features"]
    }
    segments = {
        (stop_ids[p["from_stop_idx"]], stop_ids[p["to_stop_idx"]]): (
            p["modes"],
            p["trips"],
            p["window_trips"],
        )
        for p in (f["properties"] for f in body["features"])
    }
    assert segments == {
        ("A", "B"): (["bus"], 2, 2),
        ("B", "C"): (["bus"], 2, 2),
        ("P1", "D"): (["metro"], 1, 0),
    }
    assert_labelled(body)


def test_zones_are_columns_of_h3_cells_with_estimated_values(
    client: TestClient, city_dir: Path
) -> None:
    assert client.get("/api/cities/toyville/zones").status_code == 404  # not built yet
    (city_dir / "zones").mkdir()
    zones = pl.DataFrame(
        {
            "zone_idx": pl.Series([0, 1], dtype=pl.UInt32),
            "h3_cell": ["8861892a1bfffff", "8861892a1dfffff"],
            "population": [120.0, 80.0],
        }
    )
    zones.write_parquet(city_dir / "zones" / "zones.parquet")

    without_jobs = client.get("/api/cities/toyville/zones").json()
    (city_dir / "attraction").mkdir()
    zones.head(1).select("zone_idx", employment_score=pl.lit(1.0)).write_parquet(
        city_dir / "attraction" / "attraction.parquet"
    )
    body = client.get("/api/cities/toyville/zones").json()

    assert without_jobs["est_employment_share"] is None
    assert body["zone_idx"] == [0, 1]
    assert body["population"] == [120.0, 80.0]
    assert body["est_employment_share"] == [1.0, 0.0]
    assert body["resolution"] == 8
    assert body["fields"]["population"]["nature"] == "estimated"
    assert_labelled(body)


def test_large_layers_are_gzipped(client: TestClient) -> None:
    response = client.get("/api/cities/toyville/stops", headers={"Accept-Encoding": "gzip"})

    assert response.headers["content-encoding"] == "gzip"
