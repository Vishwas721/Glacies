from pathlib import Path

from fastapi.testclient import TestClient

from glacies import __version__
from glacies.api.app import app, create_app
from glacies.config import Settings


def test_health_reports_ok_and_version() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_the_built_web_app_is_served_at_the_root(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<title>Glacies</title>", encoding="utf-8")
    client = TestClient(create_app(Settings(web_dist=tmp_path)))

    assert "<title>Glacies</title>" in client.get("/").text
    assert "<title>Glacies</title>" in client.get("/easy").text  # a page of the app, reloaded
    assert "<title>Glacies</title>" in client.get("/pro?mode=compare").text
    assert client.get("/api/health").json()["status"] == "ok"


def test_without_a_build_only_the_api_answers(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(web_dist=tmp_path / "missing")))

    assert client.get("/").status_code == 404
