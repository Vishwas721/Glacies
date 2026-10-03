from fastapi.testclient import TestClient

from glacies import __version__
from glacies.api.app import app


def test_health_reports_ok_and_version() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
