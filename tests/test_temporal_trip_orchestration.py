"""Temporal trip orchestration tests for issue #44 phase 4."""

from pathlib import Path
import shutil
import threading
from typing import Any, Mapping

import pytest
from fastapi.testclient import TestClient

import app.wiring as wiring
from app.api import create_app
from app.domain.contracts import (
    Coordinates,
    ExecutionMode,
    ResultState,
    RouteDecisionState,
    TripAnalysisRequest,
    TripMode,
)
from app.domain.ledger import BudgetExceededError
from app.integrations.fortyguard.contracts import EnvParamsRequest, HeatmapRequest
from app.services.execution import EnvParamsExecution, HeatmapExecution
from app.services.route_analysis import RouteAnalysisService
from app.services.routing import RouteExecution
from app.services.trip_adapters import TemporalTripAnalysisAdapter
from app.settings import AppSettings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _copy_hotel_fixture(tmp_path: Path) -> None:
    for name in (
        "hotel-heat-analysis.json",
        "hotel-heat-analysis.acquisition.json",
    ):
        shutil.copyfile(FIXTURES / name, tmp_path / name)


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


def _hour_payload(hour: int, value: float) -> dict[str, object]:
    """A single-hour TCM response stamped with the hour it was asked for.

    This mirrors the live provider: the heatmap product carries no per-hour
    timestamp, so every tile of a request is stamped with that request's start
    hour. Only one request per hour can therefore produce an hourly series.
    """
    return {
        "mode": "historical",
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [-98.485833, 29.425833]},
                "properties": {
                    "id": f"tcm-{hour:02d}",
                    "value": value,
                    "unit": "C",
                    "valid_time": f"2026-08-23T{hour:02d}:00:00-05:00",
                },
            }
        ],
    }


def _framing_payload(value: float) -> dict[str, object]:
    return {
        "mode": "historical",
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [-98.485833, 29.425833]},
                "properties": {
                    "id": "framing",
                    "value": value,
                    "unit": "hours",
                    "valid_time": "2026-08-23T08:00:00-05:00",
                },
            }
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
        if request.analytic_type.value == "exceedance":
            return _framing_payload(4.0)
        if request.analytic_type.value == "persistence":
            return _framing_payload(2.0)
        return _heatmap_payload()

    def load_environment(request: EnvParamsRequest) -> Mapping[str, object]:
        env_requests.append(request)
        return _env_payload()

    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(fixture_path=tmp_path / "heatmap.json", live_loader=load_heatmap),
        EnvParamsExecution(fixture_path=tmp_path / "env.json", live_loader=load_environment),
    )

    response = adapter.analyze(_request(), ExecutionMode.LIVE)

    tcm_requests = [request for request in heatmap_requests if request.analytic_type.value == "tcm"]
    assert len(heatmap_requests) == 14
    assert len(tcm_requests) == 12
    assert len(env_requests) == 1
    heatmap_request = tcm_requests[0]
    env_request = env_requests[0]
    assert (heatmap_request.latitude, heatmap_request.longitude) == (
        _request().destination.latitude,
        _request().destination.longitude,
    )
    assert (env_request.latitude, env_request.longitude) == (
        heatmap_request.latitude,
        heatmap_request.longitude,
    )
    assert heatmap_request.start_date == env_request.start_date
    assert (env_request.start_hour, env_request.end_hour) == (
        _request().start_hour,
        _request().end_hour,
    )
    assert env_request.temperature_anchor_celsius == 39.4
    assert response.state is ResultState.DEGRADED
    assert response.environment is None
    assert response.best_time is not None
    assert response.best_time.recommendation_hour == 15
    assert response.best_time.recommended_hour_tcm_celsius == 39.4
    assert response.best_time.exceedance_hours == 4.0
    assert response.best_time.persistence_hours == 2.0
    assert response.best_time.framing_threshold_celsius == 35.0
    assert response.best_time.framing_direction == "above"
    assert response.best_time.environmental_concerns is not None
    assert response.best_time.environmental_concerns[0].not_reported_count == 16
    assert response.hotels is None
    assert response.routes is None
    assert response.best_time.provenance.request_configuration["anchor_policy"] == (
        "maximum_in_window_temperature_celsius"
    )
    assert response.best_time.provenance.request_configuration["forecast"] is False
    assert response.best_time.metric_label.value == "provider_tcm"
    assert response.best_time.hourly[0].metric.label.value == "noaa_heat_index"
    assert response.best_time.hourly[1].metric.label.value == "provider_tcm"


def test_hourly_fanout_issues_one_heatmap_request_per_hour(tmp_path: Path) -> None:
    """Twelve single-hour requests, twelve hourly entries — the chart's precondition."""
    requested: list[HeatmapRequest] = []
    lock = threading.Lock()

    def load_heatmap(request: HeatmapRequest) -> Mapping[str, object]:
        with lock:
            requested.append(request)
        if request.analytic_type.value != "tcm":
            return _framing_payload(1.0)
        assert request.start_hour is not None
        return _hour_payload(request.start_hour, 30.0 + request.start_hour)

    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(fixture_path=tmp_path / "heatmap.json", live_loader=load_heatmap),
        EnvParamsExecution(
            fixture_path=tmp_path / "env.json",
            live_loader=lambda request: _env_payload(),
        ),
    )

    response = adapter.analyze(_request(), ExecutionMode.LIVE)

    tcm_windows: list[tuple[int, int]] = []
    for request in requested:
        if request.analytic_type.value != "tcm":
            continue
        assert request.start_hour is not None and request.end_hour is not None
        tcm_windows.append((request.start_hour, request.end_hour))
    assert sorted(start for start, _ in tcm_windows) == list(range(8, 20))
    assert all(end == start + 1 for start, end in tcm_windows)
    assert response.best_time is not None
    assert tuple(entry.hour for entry in response.best_time.hourly) == tuple(range(8, 20))
    assert response.best_time.provenance.request_configuration["unavailable_hours"] == []


def test_one_failing_hour_keeps_the_remaining_series_and_records_the_gap(tmp_path: Path) -> None:
    def load_heatmap(request: HeatmapRequest) -> Mapping[str, object]:
        if request.analytic_type.value != "tcm":
            raise ConnectionError("framing unavailable")
        assert request.start_hour is not None
        if request.start_hour == 13:
            raise ConnectionError("hour 13 unavailable")
        return _hour_payload(request.start_hour, 30.0 + request.start_hour)

    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(fixture_path=tmp_path / "heatmap.json", live_loader=load_heatmap),
        EnvParamsExecution(
            fixture_path=tmp_path / "env.json",
            live_loader=lambda request: _env_payload(),
        ),
    )

    response = adapter.analyze(_request(), ExecutionMode.LIVE)

    assert response.state is ResultState.DEGRADED
    assert response.best_time is not None
    hours = tuple(entry.hour for entry in response.best_time.hourly)
    assert hours == tuple(hour for hour in range(8, 20) if hour != 13)
    assert response.best_time.provenance.request_configuration["unavailable_hours"] == [13]
    assert response.best_time.provenance.note is not None
    assert "13:00" in response.best_time.provenance.note
    assert "13:00" in response.best_time.recommendation_reason


def test_preflight_budget_guard_refuses_without_spending_a_call(tmp_path: Path) -> None:
    calls = 0

    def load_heatmap(request: HeatmapRequest) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        return _heatmap_payload()

    env_calls = 0

    def load_environment(request: EnvParamsRequest) -> Mapping[str, object]:
        nonlocal env_calls
        env_calls += 1
        return _env_payload()

    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(fixture_path=tmp_path / "heatmap.json", live_loader=load_heatmap),
        EnvParamsExecution(fixture_path=tmp_path / "env.json", live_loader=load_environment),
        remaining_calls=lambda: 10,
    )

    response = adapter.analyze(_request(), ExecutionMode.LIVE)

    assert calls == 0
    assert env_calls == 0
    assert response.state is ResultState.UNAVAILABLE
    assert response.unavailable is not None
    assert response.unavailable.code == "insufficient_call_budget"
    assert "17 provider calls" in response.unavailable.reason
    assert "only 10 remain" in response.unavailable.reason


def test_preflight_budget_guard_allows_an_affordable_window(tmp_path: Path) -> None:
    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(
            fixture_path=tmp_path / "heatmap.json",
            live_loader=lambda request: _heatmap_payload(),
        ),
        EnvParamsExecution(
            fixture_path=tmp_path / "env.json",
            live_loader=lambda request: _env_payload(),
        ),
        remaining_calls=lambda: 17,
    )

    response = adapter.analyze(_request(), ExecutionMode.LIVE)

    assert response.state is ResultState.DEGRADED
    assert response.best_time is not None


def test_temporal_adapter_preserves_best_time_for_unavailable_routes(
    tmp_path: Path,
) -> None:
    route_service = RouteAnalysisService(
        RouteExecution(
            fixture_path=tmp_path / "route.json",
            live_loader=lambda request: {"code": "NoRoute", "routes": []},
        ),
        profile="foot",
        alternatives=True,
        overview="full",
        geometries="geojson",
        steps=False,
        provider_instance="fossgis-routed-foot",
        request_version="v1",
        representative_distance_m=1500.0,
        minimum_heat_coverage=0.70,
        corridor_buffer_m=25.0,
        corridor_granularity=100,
    )
    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(
            fixture_path=tmp_path / "heatmap.json",
            live_loader=lambda request: _heatmap_payload(),
        ),
        EnvParamsExecution(
            fixture_path=tmp_path / "env.json",
            live_loader=lambda request: _env_payload(),
        ),
        route_analysis=route_service,
    )

    response = adapter.analyze(_request(), ExecutionMode.LIVE)

    assert response.best_time is not None
    assert response.routes is not None
    assert response.routes.decision_state is RouteDecisionState.NO_SUITABLE_RETURNED_ROUTE
    assert response.routes.alternatives == ()
    assert response.routes.recommended_id is None
    assert response.degraded_reasons is not None
    assert "routes" in response.degraded_reasons


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

    assert heatmap_calls == 14
    assert env_calls == 1
    assert response.state is ResultState.DEGRADED
    assert response.best_time is not None
    assert response.best_time.recommendation_hour == 9
    assert "TCM-only fallback" in response.best_time.recommendation_reason
    assert response.best_time.environmental_concerns is not None
    assert all(
        profile.not_reported_count == 17 for profile in response.best_time.environmental_concerns
    )


def test_framing_metrics_are_optional_when_their_calls_fail(tmp_path: Path) -> None:
    def load_heatmap(request: HeatmapRequest) -> Mapping[str, object]:
        if request.analytic_type.value != "tcm":
            raise ConnectionError("framing unavailable")
        return _heatmap_payload()

    adapter = TemporalTripAnalysisAdapter(
        HeatmapExecution(fixture_path=tmp_path / "heatmap.json", live_loader=load_heatmap),
        EnvParamsExecution(
            fixture_path=tmp_path / "env.json",
            live_loader=lambda request: _env_payload(),
        ),
    )

    response = adapter.analyze(_request(), ExecutionMode.LIVE)

    assert response.state is ResultState.DEGRADED
    assert response.best_time is not None
    assert response.best_time.exceedance_hours is None
    assert response.best_time.persistence_hours is None
    assert response.best_time.recommendation_hour == 15


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
    monkeypatch.setattr(
        wiring,
        "build_live_route_analysis_service",
        lambda *args, **kwargs: None,
    )
    _copy_hotel_fixture(tmp_path)
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
    assert body["state"] == "degraded"
    assert body["environment"] is None
    assert body["best_time"]["recommendation_hour"] == 15
    assert body["best_time"]["recommended_hour_tcm_celsius"] == 39.4


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
    _copy_hotel_fixture(tmp_path)
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
