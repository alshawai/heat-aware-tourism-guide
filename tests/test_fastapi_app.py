from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from app.api import create_app
from app.domain.contracts import ExecutionMode
from app.services.hotel_heat_score import HotelHeatAnalysisService

from test_hotel_heat_score_service import _discovery, _evidence


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
    assert response.json()["detail"]["status"] == "error"


def test_hotel_ranking_api_serializes_provider_neutral_result() -> None:
    aoi = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)])
    service = HotelHeatAnalysisService(
        _discovery,
        _evidence,
        aoi=aoi,
    )
    client = TestClient(
        create_app(
            Path("fixtures/heatmap-historical.json"),
            hotel_heat_analysis_service=service,
        )
    )

    response = client.post(
        "/api/hotels/rank",
        json={"district_name": "Downtown", "execution_mode": ExecutionMode.FIXTURE.value},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "available"
    assert payload["discovered_count"] == 6
    assert payload["components"]["night"]["coverage"] == 0.95
    assert payload["ranking"]["weight_label"] == "product defaults"
    assert payload["ranking"]["hotels"][0]["components"]["night"]["unit"] == "C"
    assert "activity_id" not in response.text


def test_hotel_ranking_api_rejects_invalid_weights() -> None:
    client = TestClient(create_app(Path("fixtures/heatmap-historical.json")))

    response = client.post(
        "/api/hotels/rank",
        json={
            "district_name": "Downtown",
            "execution_mode": "fixture",
            "weights": {"night": 1.0},
        },
    )

    assert response.status_code == 400
    assert "weights" in response.json()["detail"]["error"]


def test_hotel_ranking_api_uses_default_fixture_service_offline() -> None:
    client = TestClient(create_app(Path("fixtures/heatmap-historical.json")))

    response = client.post(
        "/api/hotels/rank",
        json={"district_name": "Downtown San Antonio", "execution_mode": "fixture"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "available"
    assert payload["usable_count"] == 6
    assert set(payload["components"]) == {"night", "hot_hours", "persistence", "day"}
    assert all(component["available"] for component in payload["components"].values())
