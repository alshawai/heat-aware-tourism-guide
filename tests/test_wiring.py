from datetime import date
import json
import logging
from pathlib import Path
from typing import Any, Mapping, cast

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.integrations.fortyguard.contracts import EnvParamsRequest, HeatmapRequest
from app.integrations.fortyguard.errors import ProviderError, ProviderErrorKind
from app.services.execution import EnvParamsExecution, HeatmapExecution, LiveEnvParamsPayload
from app.settings import AppSettings, FortyGuardPollingSettings, SettingsError
from app.wiring import (
    build_live_env_params_execution,
    build_live_heatmap_execution,
    create_production_app,
    json_event_sink,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _env_body() -> dict[str, object]:
    return {
        "latitude": 29.4241,
        "longitude": -98.4936,
        "start_date": "2026-08-24",
        "temperature_anchor_celsius": 35.0,
    }


def test_env_params_route_serves_fixture_series() -> None:
    app = create_app(FIXTURES / "heatmap-historical.json")
    client = TestClient(app)
    response = client.post("/api/env-params", json=_env_body())
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "GMT-7"
    assert body["forecast"] is False
    assert "not a real 24-hour forecast" in body["warning"]
    assert body["entries"][0]["heat_index_celsius"] == 33.2
    assert body["entries"][0]["humidity_percent"] == 21.5
    assert body["provenance"] == {
        "source": "fixture",
        "stale": False,
        "activity_id": None,
        "transformations": [],
    }


def test_env_params_route_rejects_missing_anchor_and_bad_hour() -> None:
    app = create_app(FIXTURES / "heatmap-historical.json")
    client = TestClient(app)
    missing_anchor = {**_env_body(), "temperature_anchor_celsius": None}
    assert client.post("/api/env-params", json=missing_anchor).status_code == 400
    bad_hour = {**_env_body(), "hour": 24}
    assert client.post("/api/env-params", json=bad_hour).status_code == 400


def test_env_params_route_rejects_live_when_not_enabled() -> None:
    app = create_app(FIXTURES / "heatmap-historical.json")
    client = TestClient(app)
    response = client.post("/api/env-params", json={**_env_body(), "execution_mode": "live"})
    assert response.status_code == 400
    assert response.json()["detail"]["status"] == "unavailable"


def test_env_params_route_uses_injected_live_loader() -> None:
    def live_loader(request: EnvParamsRequest) -> LiveEnvParamsPayload:
        return LiveEnvParamsPayload(
            {
                "timestamp": "2026-08-24T13:00:00-07:00",
                "timezone": "GMT-7",
                "count": 1,
                "heat_index_celsius": [31.0],
                "relative_humidity_percent": [40.0],
            },
            "env-activity-1",
        )

    app = create_app(
        FIXTURES / "heatmap-historical.json",
        allow_live=True,
        env_params_execution=EnvParamsExecution(
            fixture_path=FIXTURES / "env-params.json", live_loader=live_loader
        ),
    )
    client = TestClient(app)
    response = client.post("/api/env-params", json={**_env_body(), "execution_mode": "live"})
    assert response.status_code == 200
    body = response.json()
    assert body["entries"][0]["heat_index_celsius"] == 31.0
    assert body["provenance"] == {
        "source": "provider",
        "stale": False,
        "activity_id": "env-activity-1",
        "transformations": [],
    }


def test_env_params_live_without_loader_is_explicitly_unavailable() -> None:
    app = create_app(
        FIXTURES / "heatmap-historical.json",
        allow_live=True,
        env_params_execution=EnvParamsExecution(fixture_path=FIXTURES / "env-params.json"),
    )
    client = TestClient(app)
    response = client.post("/api/env-params", json={**_env_body(), "execution_mode": "live"})
    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]["error"]


def test_provider_errors_surface_error_kind_in_unavailable_response() -> None:
    def failing_loader(request: HeatmapRequest) -> Mapping[str, object]:
        raise ProviderError(ProviderErrorKind.TASK_FAILURE, detail="provider task failed")

    app = create_app(
        FIXTURES / "heatmap-historical.json",
        allow_live=True,
        execution=HeatmapExecution(
            fixture_path=FIXTURES / "heatmap-historical.json",
            live_loader=failing_loader,
        ),
    )
    client = TestClient(app)
    response = client.post(
        "/api/heatmap",
        json={
            "analytic_type": "tcm",
            "latitude": 29.4241,
            "longitude": -98.4936,
            "start_date": "2026-08-23",
            "forecast": False,
            "execution_mode": "live",
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["status"] == "unavailable"
    assert detail["error_kind"] == "task_failure"


def test_build_live_heatmap_execution_composes_adapter_and_cache() -> None:
    settings = AppSettings(
        allow_live=True,
        fortyguard_api_key="key-123",
        fortyguard_base_url="https://api.example.test",
        polling=FortyGuardPollingSettings(max_polls=7),
    )
    execution = build_live_heatmap_execution(settings, fixture_path=FIXTURES / "heatmap-historical.json")
    assert execution.live_loader is not None
    assert execution.cache is not None


def test_build_live_stack_requires_api_key() -> None:
    settings = AppSettings(
        allow_live=True,
        fortyguard_api_key=None,
        fortyguard_base_url="https://api.example.test",
    )
    with pytest.raises(SettingsError, match="FORTYGUARD_API_KEY"):
        build_live_heatmap_execution(settings, fixture_path=FIXTURES / "heatmap-historical.json")
    with pytest.raises(SettingsError, match="FORTYGUARD_API_KEY"):
        build_live_env_params_execution(settings, fixture_path=FIXTURES / "env-params.json")


def test_json_event_sink_emits_sanitized_json_log_records(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.fortyguard"):
        json_event_sink({"event": "fortyguard.submitted", "api-key": "secret", "activity_id": "a1"})
    assert len(caplog.records) == 1
    record = json.loads(caplog.records[0].message)
    assert record["event"] == "fortyguard.submitted"
    assert record["activity_id"] == "a1"
    assert "secret" not in caplog.records[0].message


def test_create_production_app_fails_fast_when_live_key_missing() -> None:
    settings = AppSettings(
        allow_live=True,
        fortyguard_api_key=None,
        fortyguard_base_url="https://api.example.test",
    )
    with pytest.raises(SettingsError, match="FORTYGUARD_API_KEY"):
        create_production_app(settings)


def test_create_production_app_enables_live_only_with_settings() -> None:
    fixture_only = create_production_app(
        AppSettings(allow_live=False, fortyguard_api_key=None, fortyguard_base_url="https://api.example.test")
    )
    client = TestClient(fixture_only)
    assert client.get("/health").json()["mode"] == "fixture"

    live = create_production_app(
        AppSettings(allow_live=True, fortyguard_api_key="key-1", fortyguard_base_url="https://api.example.test")
    )
    live_client = TestClient(live)
    assert live_client.get("/health").json()["mode"] == "live"


def test_heatmap_route_accepts_granularity_from_request_body() -> None:
    from app.integrations.fortyguard.contracts import HeatmapRequest
    from app.services.execution import HeatmapExecution

    seen: list[HeatmapRequest] = []

    def live_loader(request: HeatmapRequest) -> Mapping[str, object]:
        seen.append(request)
        return {
            "mode": "historical",
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [1, 1]},
                    "properties": {"value": 35.5, "unit": "C", "valid_time": "2026-08-23T15:00:00+00:00"},
                }
            ],
        }

    app = create_app(
        FIXTURES / "heatmap-historical.json",
        allow_live=True,
        execution=HeatmapExecution(
            fixture_path=FIXTURES / "heatmap-historical.json", live_loader=live_loader
        ),
    )
    client = TestClient(app)
    response = client.post(
        "/api/heatmap",
        json={
            "analytic_type": "tcm",
            "latitude": 29.4241,
            "longitude": -98.4936,
            "start_date": "2026-08-23",
            "forecast": False,
            "granularity": 100,
            "execution_mode": "live",
        },
    )
    assert response.status_code == 200
    assert seen[0].granularity == 100
    bad = client.post(
        "/api/heatmap",
        json={
            "analytic_type": "tcm",
            "latitude": 29.4241,
            "longitude": -98.4936,
            "start_date": "2026-08-23",
            "forecast": False,
            "granularity": 70,
        },
    )
    assert bad.status_code == 400


def test_env_params_live_loader_receives_documented_date_windows() -> None:
    from app.integrations.fortyguard.live import build_documented_env_params_payload

    request = EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 24), 35.0)
    payload = build_documented_env_params_payload(request)
    date_time = cast(dict[str, Any], payload["date_time"])
    assert date_time["filter_type"] == 3
    assert payload["temperature"] == 35.0
    assert payload["analysis"] == ["heat_index_celsius", "relative_humidity_percent"]
    hourly = build_documented_env_params_payload(EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 24), 35.0, hour=13))
    assert hourly["date_time"] == {"start_date": "2026-08-24", "filter_type": 1, "start_time": "13:00"}
