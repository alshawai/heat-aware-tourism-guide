from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Mapping, cast

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.integrations.fortyguard.contracts import (
    ENVIRONMENT_PARAMETERS,
    EnvParamsRequest,
    HeatmapRequest,
)
from app.integrations.fortyguard.errors import ProviderError, ProviderErrorKind
from app.integrations.fortyguard.live import LiveEnvParamsPayload
from app.services.execution import EnvParamsExecution, HeatmapExecution
from app.settings import AppSettings, FortyGuardPollingSettings, SettingsError
from app.wiring import (
    build_hotel_discovery_service,
    build_live_env_params_execution,
    build_live_heatmap_execution,
    create_production_app,
    json_event_sink,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _env_body() -> dict[str, object]:
    """The true scenario of the committed env-params observation (issue #7)."""
    return {
        "latitude": 29.4259,
        "longitude": -98.4861,
        "start_date": "2026-08-24",
        "temperature_anchor_celsius": 35.0,
        "hour": 13,
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
        "activity_id": "0b592283-ef6f-4783-bacb-79ea59e7254a",
        "retrieved_at": "2026-08-24T11:28:01+00:00",
        "data_date": "2026-08-24",
        "transformations": [],
        "response_metadata": {
            "freshness_present": False,
            "raw_units_present": [],
            "terminal_status": None,
        },
    }


def test_env_params_route_rejects_non_matching_scenario_as_unavailable() -> None:
    app = create_app(FIXTURES / "heatmap-historical.json")
    client = TestClient(app)
    response = client.post(
        "/api/env-params", json={**_env_body(), "temperature_anchor_celsius": 28.0}
    )
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "unavailable"


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
    assert response.json()["detail"]["status"] == "error"


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
    provenance = body["provenance"]
    assert provenance["source"] == "provider"
    assert provenance["stale"] is False
    assert provenance["activity_id"] == "env-activity-1"
    assert provenance["transformations"] == []
    assert provenance["retrieved_at"] is not None
    assert provenance["data_date"] == "2026-08-24"


def test_env_params_live_without_loader_is_explicitly_unavailable() -> None:
    app = create_app(
        FIXTURES / "heatmap-historical.json",
        allow_live=True,
        env_params_execution=EnvParamsExecution(fixture_path=FIXTURES / "env-params.json"),
    )
    client = TestClient(app)
    response = client.post("/api/env-params", json={**_env_body(), "execution_mode": "live"})
    assert response.status_code == 503
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
            "latitude": 30.2672,
            "longitude": -97.7431,
            "start_date": "2026-08-23",
            "forecast": False,
            "execution_mode": "live",
        },
    )
    assert response.status_code == 503
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
    execution = build_live_heatmap_execution(
        settings, fixture_path=FIXTURES / "heatmap-historical.json"
    )
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


def test_build_hotel_discovery_service_uses_configured_overpass_policy() -> None:
    settings = AppSettings(
        allow_live=False,
        fortyguard_api_key=None,
        fortyguard_base_url="https://api.example.test",
    )
    service = build_hotel_discovery_service(settings)
    assert service.district_aoi == settings.overpass.district_aoi


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
        AppSettings(
            allow_live=False,
            fortyguard_api_key=None,
            fortyguard_base_url="https://api.example.test",
        )
    )
    client = TestClient(fixture_only)
    assert client.get("/health").json()["mode"] == "fixture"

    live = create_production_app(
        AppSettings(
            allow_live=True,
            fortyguard_api_key="key-1",
            fortyguard_base_url="https://api.example.test",
        )
    )
    live_client = TestClient(live)
    assert live_client.get("/health").json()["mode"] == "live"


def _built_frontend(path: Path) -> Path:
    dist = path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>fixture app</html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('fixture app')", encoding="utf-8")
    return dist


def test_public_fixture_requires_deployable_frontend(tmp_path: Path) -> None:
    settings = AppSettings(
        allow_live=False,
        fortyguard_api_key=None,
        fortyguard_base_url="https://api.example.test",
        app_profile="public-fixture",
    )
    with pytest.raises(SettingsError, match="built frontend index.html"):
        create_production_app(settings, frontend_dist=tmp_path / "missing")

    dist = tmp_path / "empty-assets"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    with pytest.raises(SettingsError, match="built frontend assets"):
        create_production_app(settings, frontend_dist=dist)


def test_public_fixture_requires_complete_canonical_fixture_set(tmp_path: Path) -> None:
    settings = AppSettings(
        allow_live=False,
        fortyguard_api_key=None,
        fortyguard_base_url="https://api.example.test",
        app_profile="public-fixture",
    )
    fixture = tmp_path / "fixtures" / "heatmap-historical.json"
    fixture.parent.mkdir()
    fixture.write_text('{"fixture": true}', encoding="utf-8")
    with pytest.raises(SettingsError, match="canonical fixture"):
        create_production_app(
            settings,
            fixture_path=fixture,
            env_params_fixture_path=fixture.parent / "env-params.json",
            frontend_dist=_built_frontend(tmp_path / "frontend"),
        )


def test_public_fixture_rejects_empty_or_invalid_canonical_fixture(tmp_path: Path) -> None:
    settings = AppSettings(
        allow_live=False,
        fortyguard_api_key=None,
        fortyguard_base_url="https://api.example.test",
        app_profile="public-fixture",
    )
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    for name in (
        "heatmap-historical",
        "env-params",
        "trip-analysis",
        "hotel-heat-analysis",
    ):
        (fixture_dir / f"{name}.json").write_text("{}", encoding="utf-8")
        (fixture_dir / f"{name}.acquisition.json").write_text("{}", encoding="utf-8")

    with pytest.raises(SettingsError, match="must not be empty"):
        create_production_app(
            settings,
            fixture_path=fixture_dir / "heatmap-historical.json",
            env_params_fixture_path=fixture_dir / "env-params.json",
            frontend_dist=_built_frontend(tmp_path / "frontend"),
        )


def test_public_fixture_starts_with_built_frontend_and_committed_fixtures(
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        allow_live=False,
        fortyguard_api_key=None,
        fortyguard_base_url="https://api.example.test",
        app_profile="public-fixture",
    )
    client = TestClient(create_production_app(settings, frontend_dist=_built_frontend(tmp_path)))
    assert client.get("/").status_code == 200
    assert client.get("/health").json() == {
        "status": "ok",
        "deployment_profile": "public-fixture",
        "mode": "fixture",
        "execution_capability": "fixture-only",
    }


def test_protected_live_authenticates_every_route_except_health(tmp_path: Path) -> None:
    settings = AppSettings(
        allow_live=True,
        fortyguard_api_key="key-1",
        fortyguard_base_url="https://api.example.test",
        call_budget=10,
        ledger_path=tmp_path / "durable" / "ledger.jsonl",
        app_profile="protected-live",
        live_auth_username="maintainer",
        live_auth_password="secret",
    )
    client = TestClient(
        create_production_app(settings, frontend_dist=_built_frontend(tmp_path / "frontend"))
    )

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["deployment_profile"] == "protected-live"
    assert health.json()["execution_capability"] == "fixture-and-live"

    for path in ("/", "/api/heatmap", "/does-not-exist"):
        response = client.get(path) if path != "/api/heatmap" else client.post(path, json={})
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic ")

    assert client.get("/", auth=("wrong", "secret")).status_code == 401
    assert client.get("/", auth=("maintainer", "wrong")).status_code == 401
    assert client.get("/", headers={"Authorization": "Basic !!!"}).status_code == 401
    assert client.get("/", auth=("maintainer", "secret")).status_code == 200


def test_protected_live_rejects_default_relative_ledger_path() -> None:
    settings = AppSettings(
        allow_live=True,
        fortyguard_api_key="key-1",
        fortyguard_base_url="https://api.example.test",
        call_budget=10,
        app_profile="protected-live",
        live_auth_username="maintainer",
        live_auth_password="secret",
    )
    with pytest.raises(SettingsError, match="absolute FORTYGUARD_LEDGER_PATH"):
        create_production_app(settings)


def test_protected_live_retains_explicit_fixture_requests(tmp_path: Path) -> None:
    settings = AppSettings(
        allow_live=True,
        fortyguard_api_key="key-1",
        fortyguard_base_url="https://api.example.test",
        call_budget=10,
        ledger_path=tmp_path / "ledger.jsonl",
        app_profile="protected-live",
        live_auth_username="maintainer",
        live_auth_password="secret",
    )
    client = TestClient(create_production_app(settings))
    response = client.post(
        "/api/heatmap",
        auth=("maintainer", "secret"),
        json={
            "analytic_type": "tcm",
            "latitude": 29.4241,
            "longitude": -98.4936,
            "start_date": "2026-08-23",
            "forecast": False,
            "execution_mode": "fixture",
        },
    )
    assert response.status_code == 200
    assert response.json()["provenance"]["source"] == "fixture"


def test_default_fixture_production_app_ranks_hotels_with_four_component_evidence() -> None:
    app = create_production_app(
        AppSettings(
            allow_live=False,
            fortyguard_api_key=None,
            fortyguard_base_url="https://api.example.test",
        )
    )

    response = TestClient(app).post(
        "/api/hotels/rank",
        json={"district_name": "Downtown San Antonio", "execution_mode": "fixture"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "available"
    assert payload["ranking"]["ranked_output"] is True
    assert len(payload["ranking"]["hotels"]) == 6
    assert set(payload["components"]) == {"night", "hot_hours", "persistence", "day"}
    assert payload["components"]["night"]["unit"] == "C"
    assert payload["components"]["day"]["unit"] == "C"
    assert payload["components"]["hot_hours"]["unit"] == "hours"
    assert payload["components"]["persistence"]["unit"] == "hours"
    assert payload["components"]["hot_hours"]["threshold_celsius"] == 35.0
    assert payload["components"]["persistence"]["threshold_celsius"] == 35.0


def test_production_hotel_live_mode_replays_canonical_fixture_when_provider_unavailable() -> None:
    app = create_production_app(
        AppSettings(
            allow_live=True,
            fortyguard_api_key="key-1",
            fortyguard_base_url="https://api.example.test",
        )
    )

    response = TestClient(app).post(
        "/api/hotels/rank",
        json={"district_name": "Downtown San Antonio", "execution_mode": "live"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "available"
    assert all(
        component["provenance"] == "fixture:canonical-district-hotel-analysis"
        for component in payload["components"].values()
    )


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
                    "properties": {
                        "value": 35.5,
                        "unit": "C",
                        "valid_time": "2026-08-23T15:00:00+00:00",
                    },
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
    assert payload["analysis"] == list(ENVIRONMENT_PARAMETERS)
    hourly = build_documented_env_params_payload(
        EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 24), 35.0, hour=13)
    )
    assert hourly["date_time"] == {
        "start_date": "2026-08-24",
        "filter_type": 1,
        "start_time": "13:00",
    }


def test_budget_exceeded_maps_to_service_unavailable_with_error_kind() -> None:
    from app.domain.ledger import BudgetExceededError
    from app.services.execution import HeatmapExecution

    def overspend(request: HeatmapRequest) -> Mapping[str, object]:
        raise BudgetExceededError("credit budget exceeded")

    app = create_app(
        FIXTURES / "heatmap-historical.json",
        allow_live=True,
        execution=HeatmapExecution(
            fixture_path=FIXTURES / "heatmap-historical.json",
            live_loader=overspend,
        ),
    )
    client = TestClient(app)
    response = client.post(
        "/api/heatmap",
        json={
            "analytic_type": "tcm",
            "latitude": 30.2672,
            "longitude": -97.7431,
            "start_date": "2026-08-23",
            "forecast": False,
            "execution_mode": "live",
        },
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "unavailable"
    assert detail["error_kind"] == "budget_exceeded"


def test_build_ledger_loads_history_and_applies_budget(tmp_path: Path) -> None:
    from dataclasses import replace

    from app.domain.ledger import UsageRecord
    from app.services.ledger_store import JsonlLedgerStore
    from app.wiring import build_ledger

    ledger_path = tmp_path / "ledger.jsonl"
    JsonlLedgerStore(ledger_path).load().record(
        UsageRecord("activity-1", "/v1/heatmap", 4, datetime.now(timezone.utc), "completed")
    )
    settings = AppSettings(
        allow_live=True,
        fortyguard_api_key="key-1",
        fortyguard_base_url="https://api.example.test",
        call_budget=10,
        ledger_path=ledger_path,
    )
    ledger = build_ledger(settings)
    assert ledger.budget == 10
    assert ledger.call_count == 1
    assert ledger.reported_credits == 4
    assert ledger.remaining == 9

    memory = build_ledger(replace(settings, ledger_path=None))
    assert memory.budget == 10
    assert memory.call_count == 0


def test_heatmap_fixture_candidates_include_acquired_directory(tmp_path: Path) -> None:
    from app.wiring import _fixture_candidates

    primary = tmp_path / "heatmap-historical.json"
    primary.write_text("{}", encoding="utf-8")
    acquired = tmp_path / "acquired" / "heatmap-tcm-historical.json"
    acquired.parent.mkdir()
    acquired.write_text("{}", encoding="utf-8")
    (tmp_path / "env-params.json").write_text("{}", encoding="utf-8")

    candidates = _fixture_candidates(primary, "heatmap-*.json")
    assert primary in candidates
    assert acquired in candidates
    assert (tmp_path / "env-params.json") not in candidates
    assert not any(path.name.endswith(".acquisition.json") for path in candidates)
