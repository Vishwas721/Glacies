"""POST /route on Toyville: R1 leaves Stop A at 08:00 and reaches Stop C at 08:06 via B."""

from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from glacies.api.app import create_app
from glacies.api.routers.routing import Planner
from glacies.config import Settings

URL = "/api/cities/toyville/route"
A, B, C = [77.02, 12.02], [77.03, 12.03], [77.04, 12.04]  # [lon, lat]


@pytest.fixture
def client(city_dir: Path) -> TestClient:
    return TestClient(create_app(Settings()))


def request(origin: list[float], destination: list[float], at: str) -> dict[str, object]:
    return {"origin": origin, "destination": destination, "departure_time": at}


def test_plans_a_ride_drawn_through_the_stops_it_passes(client: TestClient) -> None:
    r1 = next(
        r
        for r in client.get("/api/cities/toyville/routes").json()["routes"]
        if r["route_id"] == "R1"
    )

    body = client.post(URL, json=request([12.02, 77.02], [12.04, 77.04], "07:59")).json()

    [journey] = body["journeys"]
    assert (journey["departure"], journey["arrival"], journey["transfers"]) == ("07:59", "08:06", 0)
    [ride] = [leg for leg in journey["legs"] if leg["kind"] == "ride"]
    assert (ride["board"], ride["alight"], ride["from_name"], ride["to_name"]) == (
        "08:00",
        "08:06",
        "Stop A",
        "Stop C",
    )
    # The canonical route, not the router's internal one, names the ride.
    assert (ride["route_idx"], ride["route_name"], ride["mode"]) == (r1["route_idx"], "10", "bus")
    assert ride["coordinates"] == [A, B, C]
    assert {f["nature"] for f in body["fields"].values()} == {"simulated"}


def test_rides_are_named_by_their_trip_not_the_routers_internal_route(city_dir: Path) -> None:
    # Canonical route numbers are arbitrary: swap R1 (0) and M1 (1; R2 runs no trips that day
    # and is dropped) so R1's number differs from the router's for its stop sequence (0).
    transit = city_dir / "transit"
    swap = (1 - pl.col("route_idx")).cast(pl.UInt32).alias("route_idx")
    for name in ("routes", "trips", "patterns"):
        table = pl.read_parquet(transit / f"{name}.parquet")
        table.with_columns(swap).write_parquet(transit / f"{name}.parquet")
    client = TestClient(create_app(Settings()))

    body = client.post(URL, json=request([12.02, 77.02], [12.04, 77.04], "07:59")).json()

    [ride] = [leg for j in body["journeys"] for leg in j["legs"] if leg["kind"] == "ride"]
    assert (ride["route_idx"], ride["route_name"]) == (1, "10")


def test_no_service_means_no_journeys(client: TestClient) -> None:
    body = client.post(URL, json=request([12.02, 77.02], [12.04, 77.04], "09:00")).json()

    assert body["journeys"] == []


@pytest.mark.parametrize(
    ("origin", "at", "message"),
    [
        ([12.5, 77.02], "07:59", "outside the study area"),
        ([12.095, 77.095], "07:59", "no stop within"),
    ],
)
def test_unroutable_points_are_explained(
    client: TestClient, origin: list[float], at: str, message: str
) -> None:
    response = client.post(URL, json=request(origin, [12.04, 77.04], at))

    assert response.status_code == 422
    assert message in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        request([12.02, 77.02], [12.04, 77.04], "8am"),
        request([120.0, 77.02], [12.04, 77.04], "08:00"),
    ],
)
def test_invalid_requests_are_rejected(client: TestClient, body: dict[str, object]) -> None:
    assert client.post(URL, json=body).status_code == 422


def test_the_router_is_built_once_and_warmed_at_startup(city_dir: Path) -> None:
    app = create_app(Settings())

    with TestClient(app) as client:  # runs the startup warm-up
        client.post(URL, json=request([12.02, 77.02], [12.04, 77.04], "07:59"))
        first = app.state.routers["toyville"]
        client.post(URL, json=request([12.02, 77.02], [12.04, 77.04], "07:59"))

    assert isinstance(first, Planner)
    assert app.state.routers["toyville"] is first


def test_a_city_without_a_network_is_not_found(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path, cities_dir=Path("cities"))))

    response = client.post(
        "/api/cities/bengaluru/route", json=request([12.97, 77.59], [12.98, 77.64], "08:30")
    )

    assert response.status_code == 404
