"""Degradation chain, raw-fixture replay, and sidecar matching (ADR 0004)."""

from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.domain.ledger import BudgetExceededError
from app.integrations.fortyguard.contracts import AnalyticType, EnvParamsRequest, HeatmapRequest
from app.integrations.fortyguard.errors import ProviderError, ProviderErrorKind
from app.services.cache import CacheService
from app.integrations.fortyguard.live import LiveEnvParamsPayload, LiveHeatmapPayload
from app.services.execution import (
    EnvParamsExecution,
    HeatmapExecution,
    UnavailableError,
)

RAW_TCM_RESULT: dict[str, Any] = {
    "map_data": {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[-98.50, 29.42], [-98.49, 29.42], [-98.49, 29.43], [-98.50, 29.43], [-98.50, 29.42]]
                    ],
                },
                "properties": {"id": "tile-1", "average_temperature": 36.7},
            }
        ],
    },
    "stats_data": {"average": 36.7},
}

TCM_STAMPS = (
    ("live_envelope_unwrapped", 1),
    ("point_to_aoi_expansion", 1),
    ("valid_time_from_request", 1),
    ("tcm_unit_celsius", 1),
)

HISTORICAL_REQUEST_PAYLOAD = {
    "analytic_type": "tcm",
    "latitude": 29.4241,
    "longitude": -98.4936,
    "start_date": "2026-08-23",
    "forecast": False,
    "threshold_celsius": None,
    "direction": None,
    "granularity": 60,
}


def _heatmap_request(**overrides: Any) -> HeatmapRequest:
    values: dict[str, Any] = {
        "analytic_type": AnalyticType.TCM,
        "latitude": 29.4241,
        "longitude": -98.4936,
        "start_date": date(2026, 8, 23),
        "forecast": False,
    }
    values.update(overrides)
    return HeatmapRequest(**values)


def _write_sidecar(
    fixture_path: Path,
    request_configuration: Mapping[str, Any],
    *,
    endpoint: str = "/v1/heatmap",
    activity_id: str | None = "activity-raw-1",
    retrieved_at: str | None = "2026-08-23T12:00:00+00:00",
    data_date: str = "2026-08-23",
    status: str = "ok",
    source: str = "provider",
    transformations: list[dict[str, Any]] | None = None,
) -> None:
    payload = {
        "source": source,
        "endpoint": endpoint,
        "request_configuration": dict(request_configuration),
        "retrieved_at": retrieved_at,
        "data_date": data_date,
        "status": status,
        "schema_version": "v1",
        "provider_config_version": "fortyguard-config-v1",
        "activity_id": activity_id,
        "transformations": transformations or [],
    }
    fixture_path.with_name(f"{fixture_path.stem}.acquisition.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _stamp_names(result: Any) -> tuple[tuple[str, int], ...]:
    return tuple((t.name, t.version) for t in result.provenance.transformations)


def test_raw_fixture_replays_through_translation_with_sidecar_provenance(tmp_path: Path) -> None:
    fixture = tmp_path / "heatmap-tcm-historical.json"
    fixture.write_text(json.dumps(RAW_TCM_RESULT), encoding="utf-8")
    _write_sidecar(fixture, HISTORICAL_REQUEST_PAYLOAD, transformations=[
        {"name": name, "version": version} for name, version in TCM_STAMPS
    ])

    result = HeatmapExecution(fixture_path=fixture).run(_heatmap_request())
    assert result.provenance.source == "fixture"
    assert result.tiles[0].value_celsius == 36.7
    assert result.tiles[0].geometry["type"] == "Polygon"
    assert result.provenance.activity_id == "activity-raw-1"
    assert result.provenance.retrieved_at == datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
    assert result.provenance.data_date == "2026-08-23"
    assert result.provenance.stale is False
    assert _stamp_names(result) == TCM_STAMPS


def test_raw_fixture_and_live_share_identical_normalized_schema(tmp_path: Path) -> None:
    fixture = tmp_path / "heatmap-tcm-historical.json"
    fixture.write_text(json.dumps(RAW_TCM_RESULT), encoding="utf-8")
    _write_sidecar(fixture, HISTORICAL_REQUEST_PAYLOAD, transformations=[
        {"name": name, "version": version} for name, version in TCM_STAMPS
    ])

    from app.integrations.fortyguard.live import (
        request_transformations,
        translate_heatmap_response,
    )

    request = _heatmap_request()

    def live_loader(request: HeatmapRequest) -> LiveHeatmapPayload:
        return LiveHeatmapPayload(
            translate_heatmap_response(RAW_TCM_RESULT, request=request),
            "activity-live-1",
            request_transformations(request),
        )

    execution = HeatmapExecution(fixture_path=fixture, live_loader=live_loader)
    live_result = execution.run(request, live=True)
    fixture_result = execution.run(request)
    fixture_tile, live_tile = fixture_result.tiles[0], live_result.tiles[0]
    assert (fixture_tile.identity, fixture_tile.geometry, fixture_tile.metric) == (
        live_tile.identity,
        live_tile.geometry,
        live_tile.metric,
    )
    assert (fixture_tile.value_celsius, fixture_tile.metric_value, fixture_tile.unit) == (
        live_tile.value_celsius,
        live_tile.metric_value,
        live_tile.unit,
    )
    assert (fixture_tile.valid_time, fixture_tile.forecast) == (live_tile.valid_time, live_tile.forecast)
    assert _stamp_names(fixture_result) == _stamp_names(live_result)
    assert fixture_result.provenance.source == "fixture"
    assert live_result.provenance.source == "provider"


def test_live_failure_falls_back_to_matching_fixture_as_stale_data(tmp_path: Path) -> None:
    fixture = tmp_path / "heatmap-tcm-historical.json"
    fixture.write_text(json.dumps(RAW_TCM_RESULT), encoding="utf-8")
    _write_sidecar(fixture, HISTORICAL_REQUEST_PAYLOAD)

    def failed(request: HeatmapRequest) -> Mapping[str, object]:
        raise ConnectionError("provider unavailable")

    result = HeatmapExecution(fixture_path=fixture, live_loader=failed).run(
        _heatmap_request(), live=True
    )
    assert result.provenance.source == "fixture"
    assert result.provenance.stale is True
    assert result.provenance.activity_id == "activity-raw-1"
    assert result.provenance.retrieved_at == datetime(2026, 8, 23, 12, tzinfo=timezone.utc)


def test_cache_replay_is_preferred_over_fixture_fallback(tmp_path: Path) -> None:
    fixture = tmp_path / "heatmap-tcm-historical.json"
    fixture.write_text(json.dumps(RAW_TCM_RESULT), encoding="utf-8")
    _write_sidecar(fixture, HISTORICAL_REQUEST_PAYLOAD)
    cache = CacheService()
    cached_payload = {
        "mode": "historical",
        "data_date": "2026-08-22",
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [-98.4936, 29.4241]},
                "properties": {"value": 34.1, "unit": "C", "valid_time": "2026-08-22T15:00:00+00:00"},
            }
        ],
    }
    cache.put(
        "/v1/heatmap",
        "v1",
        dict(HISTORICAL_REQUEST_PAYLOAD),
        cached_payload,
        retrieved_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        data_date="2026-08-22",
        provider_config_version="fortyguard-config-v1",
    )

    def failed(request: HeatmapRequest) -> Mapping[str, object]:
        raise ConnectionError("provider unavailable")

    result = HeatmapExecution(fixture_path=fixture, live_loader=failed, cache=cache).run(
        _heatmap_request(), live=True
    )
    assert result.provenance.source == "cache"


def test_live_failure_chain_exhausts_to_explicit_unavailable(tmp_path: Path) -> None:
    def failed(request: HeatmapRequest) -> Mapping[str, object]:
        raise ConnectionError("provider unavailable")

    execution = HeatmapExecution(
        fixture_path=tmp_path / "absent.json", live_loader=failed, cache=CacheService()
    )
    with pytest.raises(UnavailableError, match="no matching cache entry or fixture"):
        execution.run(_heatmap_request(), live=True)


def test_unavailable_error_preserves_provider_error_kind(tmp_path: Path) -> None:
    def failed(request: HeatmapRequest) -> Mapping[str, object]:
        raise ProviderError(ProviderErrorKind.RATE_LIMIT, detail="slow down")

    execution = HeatmapExecution(fixture_path=tmp_path / "absent.json", live_loader=failed)
    with pytest.raises(UnavailableError) as caught:
        execution.run(_heatmap_request(latitude=30.1, longitude=-97.9), live=True)
    assert caught.value.error_kind == "rate_limit"
    assert isinstance(caught.value.__cause__, ProviderError)


def test_budget_exceeded_is_never_swallowed_by_fallback(tmp_path: Path) -> None:
    fixture = tmp_path / "heatmap-tcm-historical.json"
    fixture.write_text(json.dumps(RAW_TCM_RESULT), encoding="utf-8")
    _write_sidecar(fixture, HISTORICAL_REQUEST_PAYLOAD)

    def overspend(request: HeatmapRequest) -> Mapping[str, object]:
        raise BudgetExceededError("credit budget exceeded")

    with pytest.raises(BudgetExceededError):
        HeatmapExecution(fixture_path=fixture, live_loader=overspend).run(
            _heatmap_request(), live=True
        )


def test_forecast_fixture_matches_date_relaxed_and_is_stale(tmp_path: Path) -> None:
    fixture = tmp_path / "heatmap-tcm-forecast.json"
    fixture.write_text(json.dumps(RAW_TCM_RESULT), encoding="utf-8")
    forecast_payload = {**HISTORICAL_REQUEST_PAYLOAD, "start_date": "2026-08-25", "forecast": True}
    _write_sidecar(fixture, forecast_payload, data_date="2026-08-25")

    result = HeatmapExecution(fixture_path=fixture).run(
        _heatmap_request(forecast=True, start_date=date.today())
    )
    assert result.provenance.source == "fixture"
    assert result.provenance.stale is True
    assert result.provenance.data_date == "2026-08-25"


def test_historical_fixture_requires_strict_date_match(tmp_path: Path) -> None:
    fixture = tmp_path / "heatmap-tcm-historical.json"
    fixture.write_text(json.dumps(RAW_TCM_RESULT), encoding="utf-8")
    _write_sidecar(fixture, HISTORICAL_REQUEST_PAYLOAD)

    with pytest.raises(UnavailableError, match="no matching fixture"):
        HeatmapExecution(fixture_path=fixture).run(
            _heatmap_request(start_date=date(2026, 8, 20)), live=False
        )


def test_non_replayable_fixture_sidecars_are_skipped(tmp_path: Path) -> None:
    fixture = tmp_path / "heatmap-failed.json"
    fixture.write_text(json.dumps({"status": "Failed", "error_code": "provider_task_failed"}), encoding="utf-8")
    _write_sidecar(fixture, HISTORICAL_REQUEST_PAYLOAD, status="failed", activity_id=None, retrieved_at=None)

    with pytest.raises(UnavailableError, match="no matching fixture"):
        HeatmapExecution(fixture_path=fixture).run(_heatmap_request())


def test_additional_fixtures_are_searched_after_the_primary(tmp_path: Path) -> None:
    primary = tmp_path / "primary.json"
    primary.write_text(json.dumps({"mode": "historical", "features": []}), encoding="utf-8")
    acquired = tmp_path / "acquired" / "heatmap-tcm-historical.json"
    acquired.parent.mkdir()
    acquired.write_text(json.dumps(RAW_TCM_RESULT), encoding="utf-8")
    _write_sidecar(acquired, HISTORICAL_REQUEST_PAYLOAD)

    result = HeatmapExecution(
        fixture_path=primary, additional_fixtures=[acquired]
    ).run(_heatmap_request())
    assert result.provenance.source == "fixture"
    assert result.tiles[0].value_celsius == 36.7


# --- Environmental parameters execution --- #


def _env_request(**overrides: Any) -> EnvParamsRequest:
    values: dict[str, Any] = {
        "latitude": 29.4259,
        "longitude": -98.4861,
        "start_date": date(2026, 8, 24),
        "temperature_anchor_celsius": 35.0,
    }
    values.update(overrides)
    return EnvParamsRequest(**values)


def _env_request_payload(**overrides: Any) -> dict[str, Any]:
    request = _env_request(**overrides)
    return {
        "latitude": request.latitude,
        "longitude": request.longitude,
        "start_date": request.start_date.isoformat(),
        "temperature_anchor_celsius": request.temperature_anchor_celsius,
        "hour": request.hour,
    }


ENV_FLAT_RESULT: dict[str, Any] = {
    "timestamp": "2026-08-24T13:00:00-07:00",
    "timezone": "GMT-7",
    "offset": -7,
    "interval": "1h",
    "count": 1,
    "heat_index_celsius": [33.2],
    "relative_humidity_percent": [21.5],
}


def _write_env_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "env-params.json"
    fixture.write_text(json.dumps(ENV_FLAT_RESULT), encoding="utf-8")
    _write_sidecar(
        fixture,
        _env_request_payload(),
        endpoint="/v1/env_params",
        activity_id="0b592283-ef6f-4783-bacb-79ea59e7254a",
        data_date="2026-08-24",
    )
    return fixture


def test_env_params_live_success_is_cached_then_replayed_as_stale(tmp_path: Path) -> None:
    fixture = _write_env_fixture(tmp_path)
    cache = CacheService()
    live = EnvParamsExecution(
        fixture_path=fixture,
        live_loader=lambda request: LiveEnvParamsPayload(ENV_FLAT_RESULT, "env-live-1"),
        cache=cache,
    )
    fresh = live.run(_env_request(), live=True)
    assert fresh.source == "provider"
    assert fresh.stale is False

    def failed(request: EnvParamsRequest) -> Mapping[str, object]:
        raise ConnectionError("provider unavailable")

    replaying = EnvParamsExecution(fixture_path=fixture, live_loader=failed, cache=cache)
    replayed = replaying.run(_env_request(), live=True)
    assert replayed.source == "cache"
    assert replayed.stale is True
    assert replayed.activity_id == "env-live-1"
    assert replayed.retrieved_at is not None
    assert replayed.data_date == "2026-08-24"
    assert replayed.result.entries[0].heat_index_celsius == 33.2


def test_env_params_live_failure_falls_back_to_matching_fixture(tmp_path: Path) -> None:
    fixture = _write_env_fixture(tmp_path)

    def failed(request: EnvParamsRequest) -> Mapping[str, object]:
        raise ConnectionError("provider unavailable")

    outcome = EnvParamsExecution(fixture_path=fixture, live_loader=failed).run(
        _env_request(), live=True
    )
    assert outcome.source == "fixture"
    assert outcome.stale is True
    assert outcome.activity_id == "0b592283-ef6f-4783-bacb-79ea59e7254a"
    assert outcome.retrieved_at == datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
    assert outcome.data_date == "2026-08-24"


def test_env_params_anchor_mismatch_is_unavailable_not_fallback(tmp_path: Path) -> None:
    fixture = _write_env_fixture(tmp_path)

    def failed(request: EnvParamsRequest) -> Mapping[str, object]:
        raise ConnectionError("provider unavailable")

    with pytest.raises(UnavailableError, match="no matching cache entry or fixture"):
        EnvParamsExecution(fixture_path=fixture, live_loader=failed).run(
            _env_request(temperature_anchor_celsius=28.0), live=True
        )


def test_env_params_fixture_mode_requires_matching_scenario(tmp_path: Path) -> None:
    fixture = _write_env_fixture(tmp_path)
    execution = EnvParamsExecution(fixture_path=fixture)
    assert execution.run(_env_request()).source == "fixture"
    with pytest.raises(UnavailableError, match="no matching fixture"):
        execution.run(_env_request(latitude=29.43, longitude=-98.49))


def test_forecast_fixture_with_matching_date_is_still_labelled_stale(tmp_path: Path) -> None:
    """A committed forecast replayed for its own calendar date is still not current (AC 4)."""
    fixture = tmp_path / "heatmap-tcm-forecast.json"
    fixture.write_text(json.dumps(RAW_TCM_RESULT), encoding="utf-8")
    today = date.today()
    forecast_payload = {**HISTORICAL_REQUEST_PAYLOAD, "start_date": today.isoformat(), "forecast": True}
    _write_sidecar(fixture, forecast_payload, data_date=today.isoformat())

    result = HeatmapExecution(fixture_path=fixture).run(
        _heatmap_request(forecast=True, start_date=today)
    )
    assert result.provenance.source == "fixture"
    assert result.provenance.stale is True


def test_corrupt_fixture_payload_is_skipped_and_scan_continues(tmp_path: Path) -> None:
    """A corrupt candidate is a server-side data problem, never a client error (ADR 0004 §6)."""
    broken = tmp_path / "heatmap-broken.json"
    broken.write_text(json.dumps({"map_data": {"features": []}}), encoding="utf-8")
    _write_sidecar(broken, HISTORICAL_REQUEST_PAYLOAD)
    good = tmp_path / "heatmap-good.json"
    good.write_text(json.dumps(RAW_TCM_RESULT), encoding="utf-8")
    _write_sidecar(good, HISTORICAL_REQUEST_PAYLOAD)

    result = HeatmapExecution(fixture_path=broken, additional_fixtures=[good]).run(_heatmap_request())
    assert result.provenance.source == "fixture"
    assert result.tiles[0].value_celsius == 36.7

    with pytest.raises(UnavailableError, match="no matching fixture"):
        HeatmapExecution(fixture_path=broken).run(_heatmap_request())
