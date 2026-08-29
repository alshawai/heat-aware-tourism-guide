"""Temporal trip orchestration tests for issue #44 phase 4."""

from pathlib import Path
from typing import Any, Mapping

import pytest
from fastapi.testclient import TestClient

import app.wiring as wiring
from app.api import create_app
from app.domain.contracts import (
    Coordinates,
    ExecutionMode,
    ResultState,
    TripAnalysisRequest,
    TripMode,
)
from app.domain.ledger import BudgetExceededError
from app.integrations.fortyguard.contracts import EnvParamsRequest, HeatmapRequest
from app.services.execution import EnvParamsExecution, HeatmapExecution
from app.services.trip_adapters import TemporalTripAnalysisAdapter
from app.settings import AppSettings


def _request() -> TripAnalysisRequest:
    return TripAnalysisRequest(
        mode=TripMode.CURATED,
        origin=Coordinates(29.4245914, -98.4864288),
        destination=Coordinates(29.425833, -98.485833),
        landmark_name="The Alamo",
        district_name="Downtown San Antonio",
        date="2026-08-23",
        start_hour=8,
        end_hour=20,
        cautious=False,
    )


def _heatmap_payload() -> dict[str, object]:
    return {
        "mode": "historical",
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [-98.485833, 29.425833]},
                "properties": {
                    "id": "morning",
                    "value": 32.1,
                    "unit": "C",
                    "valid_time": "2026-08-23T09:00:00-05:00",
                },
            },
            {
                "geometry": {"type": "Point", "coordinates": [-98.485833, 29.425833]},
                "properties": {
                    "id": "afternoon",
                    "value": 39.4,
                    "unit": "C",
                    "valid_time": "2026-08-23T15:00:00-05:00",
                },
            },
        ],
    }


def _env_payload() -> dict[str, object]:
    return {
        "metadata": {
            "timestamps": [
                "2026-08-23T08:00:00-05:00",
                "2026-08-23T09:00:00-05:00",
            ],
            "timezone": "America/Chicago",
        },
        "locations": [
            {
                "parameters": {
                    "heat_index_celsius": [None, 36.8],
                    "relative_humidity_percent": [58.0, None],
                }
            }
        ],
    }


def test_temporal_adapter_chains_one_heatmap_call_into_one_env_params_call(
    tmp_path: Path,
) -> None:
    heatmap_requests: list[HeatmapRequest] = []
    env_requests: list[EnvParamsRequest] = []

    def load_heatmap(request: HeatmapRequest) -> Mapping[str, object]:
        heatmap_requests.append(request)
        return _heatmap_payload()

    def load_environment(request: EnvParamsRequest) -> Mapping[str, object]:
        env_requests.append(request)
        return _env_payload()

    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(fixture_path=tmp_path / "heatmap.json", live_loader=load_heatmap),
        EnvParamsExecution(fixture_path=tmp_path / "env.json", live_loader=load_environment),
    )

    response = adapter.analyze(_request(), ExecutionMode.LIVE)

    assert len(heatmap_requests) == 1
    assert len(env_requests) == 1
    heatmap_request = heatmap_requests[0]
    env_request = env_requests[0]
    assert (heatmap_request.latitude, heatmap_request.longitude) == (
        _request().destination.latitude,
        _request().destination.longitude,
    )
    assert (env_request.latitude, env_request.longitude) == (
        heatmap_request.latitude,
        heatmap_request.longitude,
    )
    assert (heatmap_request.start_date, heatmap_request.start_hour, heatmap_request.end_hour) == (
        env_request.start_date,
        env_request.start_hour,
        env_request.end_hour,
    )
    assert env_request.temperature_anchor_celsius == 39.4
    assert response.state is ResultState.SERIES_READY
    assert response.environment is not None
    assert response.environment.temperature_anchor_celsius == 39.4
    assert response.environment.entries[0].heat_index_celsius is None
    assert response.environment.entries[1].humidity_percent is None
    assert response.best_time is None
    assert response.hotels is None
    assert response.routes is None
    assert response.environment.provenance.request_configuration["anchor_policy"] == (
        "maximum_in_window_temperature_celsius"
    )


def test_heatmap_unavailable_stops_before_env_params_call(tmp_path: Path) -> None:
    env_calls = 0

    def fail_heatmap(request: HeatmapRequest) -> Mapping[str, object]:
        raise ConnectionError("heatmap unavailable")

    def load_environment(request: EnvParamsRequest) -> Mapping[str, object]:
        nonlocal env_calls
        env_calls += 1
        return _env_payload()

    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(fixture_path=tmp_path / "heatmap.json", live_loader=fail_heatmap),
        EnvParamsExecution(fixture_path=tmp_path / "env.json", live_loader=load_environment),
    )

    response = adapter.analyze(_request(), ExecutionMode.LIVE)

    assert response.state is ResultState.UNAVAILABLE
    assert response.unavailable is not None
    assert "heatmap" in response.unavailable.reason
    assert env_calls == 0


def test_env_params_unavailable_returns_explicit_unavailable_after_one_call(
    tmp_path: Path,
) -> None:
    heatmap_calls = 0
    env_calls = 0

    def load_heatmap(request: HeatmapRequest) -> Mapping[str, object]:
        nonlocal heatmap_calls
        heatmap_calls += 1
        return _heatmap_payload()

    def fail_environment(request: EnvParamsRequest) -> Mapping[str, object]:
        nonlocal env_calls
        env_calls += 1
        raise ConnectionError("environment unavailable")

    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(fixture_path=tmp_path / "heatmap.json", live_loader=load_heatmap),
        EnvParamsExecution(fixture_path=tmp_path / "env.json", live_loader=fail_environment),
    )

    response = adapter.analyze(_request(), ExecutionMode.LIVE)

    assert heatmap_calls == 1
    assert env_calls == 1
    assert response.state is ResultState.UNAVAILABLE
    assert response.unavailable is not None
    assert "environmental-parameters" in response.unavailable.reason


def test_production_wiring_uses_temporal_adapter_for_live_trip_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heatmap_execution = HeatmapExecution(
        fixture_path=tmp_path / "heatmap.json",
        live_loader=lambda request: _heatmap_payload(),
    )
    env_execution = EnvParamsExecution(
        fixture_path=tmp_path / "env.json",
        live_loader=lambda request: _env_payload(),
    )
    monkeypatch.setattr(wiring, "build_live_client", lambda settings, ledger=None: object())
    monkeypatch.setattr(
        wiring,
        "build_live_heatmap_execution",
        lambda *args, **kwargs: heatmap_execution,
    )
    monkeypatch.setattr(
        wiring,
        "build_live_env_params_execution",
        lambda *args, **kwargs: env_execution,
    )
    app = wiring.create_production_app(
        AppSettings(
            allow_live=True,
            fortyguard_api_key="test-key",
            fortyguard_base_url="https://api.example.test",
        ),
        fixture_path=tmp_path / "heatmap.json",
        env_params_fixture_path=tmp_path / "env.json",
        frontend_dist=tmp_path / "dist",
    )

    response = TestClient(app).post(
        "/api/trip/analyze",
        json={
            "origin_latitude": 29.4245914,
            "origin_longitude": -98.4864288,
            "destination_latitude": 29.425833,
            "destination_longitude": -98.485833,
            "mode": "curated",
            "landmark_name": "The Alamo",
            "district_name": "Downtown San Antonio",
            "date": "2026-08-23",
            "start_hour": 8,
            "end_hour": 20,
            "execution_mode": "live",
        },
    )

    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["state"] == "series_ready"
    assert body["environment"]["temperature_anchor_celsius"] == 39.4
    assert body["best_time"] is None


def test_trip_endpoint_maps_orchestration_budget_failure_to_503(tmp_path: Path) -> None:
    def exceed_budget(request: HeatmapRequest) -> Mapping[str, object]:
        raise BudgetExceededError("credit budget exceeded")

    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(fixture_path=tmp_path / "heatmap.json", live_loader=exceed_budget),
        EnvParamsExecution(
            fixture_path=tmp_path / "env.json",
            live_loader=lambda request: _env_payload(),
        ),
    )
    client = TestClient(
        create_app(
            tmp_path / "heatmap.json",
            allow_live=True,
            trip_adapter=adapter,
        )
    )

    response = client.post(
        "/api/trip/analyze",
        json={
            "origin_latitude": 29.4245914,
            "origin_longitude": -98.4864288,
            "destination_latitude": 29.425833,
            "destination_longitude": -98.485833,
            "mode": "curated",
            "landmark_name": "The Alamo",
            "district_name": "Downtown San Antonio",
            "date": "2026-08-23",
            "start_hour": 8,
            "end_hour": 20,
            "execution_mode": "live",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_kind"] == "budget_exceeded"
