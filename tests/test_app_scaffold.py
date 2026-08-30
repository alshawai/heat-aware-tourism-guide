from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app


def test_health_endpoint_is_provider_independent() -> None:
    response = TestClient(create_app(Path("fixtures/heatmap-historical.json"))).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "deployment_profile": "local",
        "mode": "fixture",
        "execution_capability": "fixture-only",
    }
