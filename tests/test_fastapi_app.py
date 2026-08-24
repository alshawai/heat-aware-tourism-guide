from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app


def test_fastapi_app_exposes_fixture_heatmap_contract() -> None:
    client = TestClient(create_app(Path("fixtures/heatmap-historical.json")))
    response = client.post(
        "/api/heatmap",
        json={
            "analytic_type": "tcm",
            "latitude": 29.4241,
            "longitude": -98.4936,
            "start_date": date(2026, 8, 23).isoformat(),
            "forecast": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["provenance"]["source"] == "fixture"


def test_fastapi_app_does_not_allow_public_live_mode() -> None:
    client = TestClient(create_app(Path("fixtures/heatmap-historical.json")))
    response = client.post(
        "/api/heatmap",
        json={
            "analytic_type": "tcm",
            "latitude": 29.4241,
            "longitude": -98.4936,
            "start_date": date(2026, 8, 23).isoformat(),
            "forecast": False,
            "execution_mode": "live",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["status"] == "unavailable"
