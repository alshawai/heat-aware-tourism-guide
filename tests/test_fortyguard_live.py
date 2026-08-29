import json
from datetime import date, datetime, timedelta
from typing import Any, cast

import pytest

from app.integrations.fortyguard.client import FortyGuardClient, poll_activity
from app.integrations.fortyguard.contracts import (
    ENVIRONMENT_PARAMETERS,
    AnalyticType,
    EnvParamsRequest,
    HeatmapRequest,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.errors import ProviderError, ProviderErrorKind
from app.integrations.fortyguard.live import (
    LiveEnvParamsAdapter,
    LiveFortyGuardTransport,
    LiveHeatmapAdapter,
    build_documented_env_params_payload,
    build_documented_heatmap_payload,
    translate_heatmap_response,
)
from app.integrations.fortyguard.transport import HttpFortyGuardTransport
from app.settings import FortyGuardPollingSettings
from app.integrations.fortyguard.live import LiveHeatmapPayload


class _Response:
    def __init__(self, body: object) -> None:
        self._body = json.dumps(body).encode() if not isinstance(body, bytes) else body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _recording_transport(
    responses: list[object],
) -> tuple[LiveFortyGuardTransport, list[tuple[str, dict[str, str]]]]:
    calls: list[tuple[str, dict[str, str]]] = []
    queue = list(responses)

    def opener(request: object, timeout: float) -> _Response:
        calls.append((request.full_url, dict(request.headers)))  # type: ignore[attr-defined]
        return _Response(queue.pop(0))

    return LiveFortyGuardTransport("https://api.example.test", opener=opener), calls


def test_live_transport_sends_documented_api_key_header() -> None:
    transport, calls = _recording_transport([{"data": {"activity_id": "a1"}}])
    transport.post("/v1/heatmap", {"analytic_type": "tcm"}, "secret")
    assert calls[0][1]["Api-key"] == "secret"


def test_live_transport_hoists_submission_envelope_data_activity_id() -> None:
    transport, _ = _recording_transport(
        [
            {
                "error": False,
                "status_code": 200,
                "message": "Heatmap Submitted",
                "data": {"activity_id": "a1"},
            }
        ]
    )
    assert transport.post("/v1/heatmap", {}, "secret") == {
        "error": False,
        "status_code": 200,
        "message": "Heatmap Submitted",
        "activity_id": "a1",
    }


def test_live_transport_hoists_status_envelope_for_poller() -> None:
    transport, _ = _recording_transport(
        [
            {
                "data": {
                    "activity_id": "a1",
                    "status": "Completed",
                    "result": {"map_data": {}, "stats_data": {}},
                }
            },
        ]
    )
    assert transport.get("/v1/status/a1", "secret") == {
        "activity_id": "a1",
        "status": "Completed",
        "result": {"map_data": {}, "stats_data": {}},
    }


def test_live_transport_passes_envelope_free_responses_through() -> None:
    transport, _ = _recording_transport([{"status_code": 404}])
    assert transport.get("/v1/status/a1", "secret") == {"status_code": 404}


def test_live_transport_rejects_non_object_data_envelope() -> None:
    transport, _ = _recording_transport([{"data": ["not", "an", "object"]}])
    with pytest.raises(ProviderError) as error:
        transport.post("/v1/heatmap", {}, "secret")
    assert error.value.kind is ProviderErrorKind.MALFORMED_RESPONSE


def test_live_transport_end_to_end_submit_and_poll_with_client() -> None:
    transport, calls = _recording_transport(
        [
            {"data": {"activity_id": "a1"}},
            {"data": {"activity_id": "a1", "status": "Processing"}},
            {
                "data": {
                    "activity_id": "a1",
                    "status": "Completed",
                    "result": {"map_data": {}, "stats_data": {}},
                }
            },
        ]
    )
    client = FortyGuardClient(transport, "secret", clock=lambda: datetime(2026, 8, 27))
    result, metadata = client.submit_and_poll(
        "/v1/heatmap",
        {"analytic_type": "tcm"},
        sleep=lambda _: None,
        max_polls=3,
    )
    assert result == {"map_data": {}, "stats_data": {}}
    assert metadata.activity_id == "a1"
    assert metadata.status_transitions == ("Processing", "Completed")
    assert calls[0][0] == "https://api.example.test/v1/heatmap"
    assert calls[1][0] == "https://api.example.test/v1/status/a1"


def test_http_transport_base_class_still_sends_documented_header() -> None:
    calls: list[dict[str, str]] = []

    def opener(request: object, timeout: float) -> _Response:
        calls.append(dict(request.headers))  # type: ignore[attr-defined]
        return _Response({"activity_id": "a1"})

    transport = HttpFortyGuardTransport("https://api.example.test", opener=opener)
    transport.post("/v1/heatmap", {}, "secret")
    assert calls[0]["Api-key"] == "secret"


def test_live_transport_rejects_missing_activity_id_in_envelope() -> None:
    transport, _ = _recording_transport([{"data": {"something": "else"}}])
    client = FortyGuardClient(transport, "secret", clock=lambda: datetime(2026, 8, 27))
    with pytest.raises(ProviderError) as error:
        client.submit_and_poll("/v1/heatmap", {}, sleep=lambda _: None)
    assert error.value.kind is ProviderErrorKind.MALFORMED_RESPONSE


# --- Live heatmap adapter: documented payload construction and translation --- #


def _tcm_request(**overrides: object) -> HeatmapRequest:
    defaults: dict[str, object] = {
        "analytic_type": AnalyticType.TCM,
        "latitude": 29.4241,
        "longitude": -98.4936,
        "start_date": date.today(),
        "forecast": True,
    }
    defaults.update(overrides)
    return HeatmapRequest(**defaults)  # type: ignore[arg-type]


def _historical_request(**overrides: object) -> HeatmapRequest:
    defaults: dict[str, object] = {
        "analytic_type": AnalyticType.TCM,
        "latitude": 29.4241,
        "longitude": -98.4936,
        "start_date": date(2026, 8, 20),
        "forecast": False,
    }
    defaults.update(overrides)
    return HeatmapRequest(**defaults)  # type: ignore[arg-type]


def test_documented_payload_shape_for_point_request() -> None:
    payload = build_documented_heatmap_payload(_tcm_request())
    assert set(payload) == {"polygon_aoi", "date_time", "granularity", "analytic_type"}
    assert payload["date_time"] == {"start_date": date.today().isoformat(), "filter_type": 3}
    assert payload["granularity"] == 60
    assert payload["analytic_type"] == "tcm"
    aoi = payload["polygon_aoi"]
    assert isinstance(aoi, dict)
    assert aoi["type"] == "FeatureCollection"
    feature = aoi["features"][0]
    assert feature["type"] == "Feature"
    ring = feature["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    longitudes = [position[0] for position in ring]
    latitudes = [position[1] for position in ring]
    assert abs((max(latitudes) - min(latitudes)) * 111320 - 60) < 0.5
    assert abs((max(longitudes) - min(longitudes)) * 111320 * 0.872 - 60) < 0.5


def test_documented_payload_includes_threshold_and_direction_for_hour_analytics() -> None:
    request = _historical_request(
        analytic_type=AnalyticType.EXCEEDANCE,
        threshold_celsius=35.0,
        direction="above",
        granularity=100,
    )
    payload = build_documented_heatmap_payload(request)
    assert payload["threshold"] == 35.0
    assert payload["direction"] == "above"
    assert payload["granularity"] == 100


def test_heatmap_request_validates_granularity() -> None:
    assert _tcm_request().granularity == 60
    assert _tcm_request(granularity=80).granularity == 80
    assert _tcm_request(granularity=100).granularity == 100
    with pytest.raises(ValueError, match="granularity"):
        _tcm_request(granularity=50)
    with pytest.raises(ValueError, match="granularity"):
        _tcm_request(granularity="60")


def test_forecast_beyond_documented_window_rejected() -> None:
    request = _tcm_request(start_date=date.today() + timedelta(days=1))
    with pytest.raises(ProviderError) as error:
        build_documented_heatmap_payload(request)
    assert error.value.kind is ProviderErrorKind.VALIDATION
    assert "12 hours" in error.value.detail


def test_historical_dates_outside_documented_range_rejected() -> None:
    with pytest.raises(ProviderError, match="2019"):
        build_documented_heatmap_payload(_historical_request(start_date=date(2018, 12, 31)))
    with pytest.raises(ProviderError, match="2019"):
        build_documented_heatmap_payload(
            _historical_request(start_date=date.today() + timedelta(days=1))
        )


def _live_map_data() -> dict[str, object]:
    return {
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-98.5, 29.4],
                                [-98.4, 29.4],
                                [-98.4, 29.5],
                                [-98.5, 29.5],
                                [-98.5, 29.4],
                            ]
                        ],
                    },
                    "properties": {
                        "average_temperature": 36.5,
                        "min_temperature": 28.1,
                        "max_temperature": 41.2,
                    },
                }
            ],
        },
        "stats_data": {"units": "celsius", "analytic_type": "tcm"},
    }


def test_translate_tcm_map_data_to_internal_tiles() -> None:
    translated = translate_heatmap_response(_live_map_data(), request=_historical_request())
    assert translated["mode"] == "historical"
    assert translated["data_date"] == "2026-08-20"
    assert translated["stats_data"] == {"units": "celsius", "analytic_type": "tcm"}
    feature = cast(dict[str, Any], cast(list[object], translated["features"])[0])
    properties = cast(dict[str, Any], feature["properties"])
    assert properties["value"] == 36.5
    assert properties["unit"] == "C"
    assert properties["metric"] == "tcm"
    assert properties["valid_time"] == "2026-08-20T00:00:00+00:00"
    assert cast(dict[str, Any], feature["geometry"])["type"] == "Polygon"


def test_translate_hour_analytics_value_tiles() -> None:
    result = {
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-98.5, 29.4],
                                [-98.4, 29.4],
                                [-98.4, 29.5],
                                [-98.5, 29.5],
                                [-98.5, 29.4],
                            ]
                        ],
                    },
                    "properties": {"value": 5.0},
                }
            ],
        },
        "stats_data": {"units": "hour", "analytic_type": "exceedance"},
    }
    request = _historical_request(
        analytic_type=AnalyticType.EXCEEDANCE, threshold_celsius=35.0, direction="above"
    )
    translated = translate_heatmap_response(result, request=request)
    hour_feature = cast(dict[str, Any], cast(list[object], translated["features"])[0])
    assert cast(dict[str, Any], hour_feature["properties"])["value"] == 5.0
    assert cast(dict[str, Any], hour_feature["properties"])["unit"] == "hours"
    assert translated["mode"] == "historical"


def test_translate_rejects_missing_map_data_and_empty_features() -> None:
    with pytest.raises(ProviderError) as error:
        translate_heatmap_response({}, request=_historical_request())
    assert error.value.kind is ProviderErrorKind.MALFORMED_RESPONSE
    with pytest.raises(ProviderError):
        translate_heatmap_response({"map_data": {"features": []}}, request=_historical_request())


def test_translate_rejects_undocumented_tile_values() -> None:
    bad_feature = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[-98.5, 29.4], [-98.4, 29.4], [-98.4, 29.5], [-98.5, 29.5], [-98.5, 29.4]]
            ],
        },
        "properties": {"unrelated": True},
    }
    with pytest.raises(ProviderError) as error:
        translate_heatmap_response(
            {"map_data": {"features": [bad_feature]}}, request=_historical_request()
        )
    assert error.value.kind is ProviderErrorKind.MALFORMED_RESPONSE


def _adapter_client(responses: list[object]) -> tuple[FortyGuardClient, list[dict[str, object]]]:
    submissions: list[dict[str, object]] = []
    queue = list(responses)

    def opener(request: object, timeout: float) -> _Response:
        data = getattr(request, "data", None)
        if data is not None:
            submissions.append(json.loads(data))
        return _Response(queue.pop(0))

    transport = LiveFortyGuardTransport("https://api.example.test", opener=opener)
    return FortyGuardClient(transport, "secret", clock=lambda: datetime(2026, 8, 27)), submissions


def test_adapter_load_translates_and_stamps_transformations() -> None:
    client, submissions = _adapter_client(
        [
            {"data": {"activity_id": "a1"}},
            {"data": {"activity_id": "a1", "status": "Completed", "result": _live_map_data()}},
        ]
    )
    adapter = LiveHeatmapAdapter(client)
    loaded = adapter.load(_tcm_request())
    assert isinstance(loaded, LiveHeatmapPayload)
    assert loaded.activity_id == "a1"
    assert submissions[0]["analytic_type"] == "tcm"
    assert submissions[0]["granularity"] == 60
    assert cast(dict[str, Any], submissions[0]["date_time"])["filter_type"] == 3
    stamps = {
        transformation.name: transformation.version for transformation in loaded.transformations
    }
    assert stamps == {
        "live_envelope_unwrapped": 1,
        "point_to_aoi_expansion": 1,
        "valid_time_from_request": 2,
        "tcm_unit_celsius": 1,
    }
    result = normalize_heatmap_response(
        loaded.payload,
        request=_tcm_request(),
        retrieved_at=datetime(2026, 8, 27, 12, 0),
        activity_id=loaded.activity_id,
        transformations=loaded.transformations,
    )
    assert result.tiles[0].value_celsius == 36.5
    assert result.provenance.source == "provider"
    assert result.provenance.activity_id == "a1"
    assert result.provenance.data_date == date.today().isoformat()
    assert {t.name for t in result.provenance.transformations} == set(stamps)


def test_adapter_load_hour_analytics_without_tcm_unit_stamp() -> None:
    client, _ = _adapter_client(
        [
            {"data": {"activity_id": "a2"}},
            {
                "data": {
                    "activity_id": "a2",
                    "status": "Completed",
                    "result": {
                        "map_data": {
                            "features": [
                                {
                                    "geometry": {
                                        "type": "Polygon",
                                        "coordinates": [
                                            [
                                                [-98.5, 29.4],
                                                [-98.4, 29.4],
                                                [-98.4, 29.5],
                                                [-98.5, 29.5],
                                                [-98.5, 29.4],
                                            ]
                                        ],
                                    },
                                    "properties": {"value": 2.0},
                                }
                            ]
                        }
                    },
                }
            },
        ]
    )
    adapter = LiveHeatmapAdapter(client)
    request = _historical_request(
        analytic_type=AnalyticType.PERSISTENCE, threshold_celsius=35.0, direction="above"
    )
    loaded = adapter.load(request)
    assert "tcm_unit_celsius" not in {t.name for t in loaded.transformations}


def test_adapter_load_rejects_out_of_contract_date_before_any_submission() -> None:
    client, submissions = _adapter_client([{"data": {"activity_id": "a1"}}])
    adapter = LiveHeatmapAdapter(client)
    request = _tcm_request(start_date=date.today() + timedelta(days=1))
    with pytest.raises(ProviderError) as error:
        adapter.load(request)
    assert error.value.kind is ProviderErrorKind.VALIDATION
    assert submissions == []


# --- Bounded polling and post-submit 404 tolerance (ADR 0003) --- #


def test_polling_tolerates_404s_within_grace_window() -> None:
    responses: list[dict[str, object]] = [
        {"status_code": 404},
        {"status_code": 404},
        {"status_code": 404},
        {"status_code": 200, "status": "Completed", "result": {"map_data": {}}},
    ]
    result = poll_activity(
        "a1",
        get_status=lambda _: responses.pop(0),
        sleep=lambda _: None,
        max_polls=6,
        status_404_grace_checks=3,
    )
    assert result == {"map_data": {}}


def test_polling_404_after_activity_seen_is_terminal() -> None:
    responses: list[dict[str, object]] = [
        {"status_code": 200, "status": "Processing"},
        {"status_code": 404},
    ]
    with pytest.raises(ProviderError) as error:
        poll_activity(
            "a1",
            get_status=lambda _: responses.pop(0),
            sleep=lambda _: None,
            max_polls=5,
            status_404_grace_checks=3,
        )
    assert error.value.kind is ProviderErrorKind.VALIDATION


def test_polling_404_beyond_grace_window_is_terminal() -> None:
    responses: list[dict[str, object]] = [
        {"status_code": 404},
        {"status_code": 404},
        {"status_code": 404},
        {"status_code": 404},
    ]
    with pytest.raises(ProviderError) as error:
        poll_activity(
            "a1",
            get_status=lambda _: responses.pop(0),
            sleep=lambda _: None,
            max_polls=8,
            status_404_grace_checks=3,
        )
    assert error.value.kind is ProviderErrorKind.VALIDATION


def test_submit_and_poll_threads_interval_seconds() -> None:
    sleeps: list[float] = []
    transport, _ = _recording_transport(
        [
            {"data": {"activity_id": "a1"}},
            {"data": {"activity_id": "a1", "status": "Processing"}},
            {"data": {"activity_id": "a1", "status": "Completed", "result": {"ok": True}}},
        ]
    )
    client = FortyGuardClient(transport, "secret", clock=lambda: datetime(2026, 8, 27))
    client.submit_and_poll(
        "/v1/heatmap", {}, sleep=sleeps.append, max_polls=3, interval_seconds=5.0
    )
    assert sleeps == [5.0]


def test_adapter_uses_polling_settings_bounds() -> None:
    sleeps: list[float] = []
    client, _ = _adapter_client(
        [
            {"data": {"activity_id": "a1"}},
            {"data": {"activity_id": "a1", "status": "Processing"}},
            {"data": {"activity_id": "a1", "status": "Completed", "result": _live_map_data()}},
        ]
    )
    adapter = LiveHeatmapAdapter(
        client,
        polling=FortyGuardPollingSettings(max_polls=3, interval_seconds=2.0),
        sleep=sleeps.append,
    )
    loaded = adapter.load(_tcm_request())
    assert loaded.activity_id == "a1"
    assert sleeps == [2.0]


# --- Live env-params adapter: payload, validation, and stamps --- #


def _env_request(**overrides: object) -> EnvParamsRequest:
    defaults: dict[str, object] = {
        "latitude": 29.4241,
        "longitude": -98.4936,
        "start_date": date(2026, 8, 24),
        "temperature_anchor_celsius": 35.0,
    }
    defaults.update(overrides)
    return EnvParamsRequest(**defaults)  # type: ignore[arg-type]


def test_env_params_documented_payload_full_day_and_hourly() -> None:
    payload = build_documented_env_params_payload(_env_request())
    assert payload["date_time"] == {"start_date": "2026-08-24", "filter_type": 3}
    assert payload["temperature"] == 35.0
    assert payload["analysis"] == list(ENVIRONMENT_PARAMETERS)
    hourly = build_documented_env_params_payload(_env_request(hour=13))
    assert hourly["date_time"] == {
        "start_date": "2026-08-24",
        "filter_type": 1,
        "start_time": "13:00",
    }


def test_env_params_payload_rejects_out_of_contract_dates() -> None:
    with pytest.raises(ProviderError) as early:
        build_documented_env_params_payload(_env_request(start_date=date(2018, 12, 31)))
    assert early.value.kind is ProviderErrorKind.VALIDATION
    with pytest.raises(ProviderError) as late:
        build_documented_env_params_payload(
            _env_request(start_date=date.today() + timedelta(days=30))
        )
    assert late.value.kind is ProviderErrorKind.VALIDATION


def test_env_params_adapter_load_stamps_envelope_transformation() -> None:
    client, submissions = _adapter_client(
        [
            {"data": {"activity_id": "env-1"}},
            {
                "data": {
                    "activity_id": "env-1",
                    "status": "Completed",
                    "result": {
                        "timestamp": "2026-08-24T13:00:00-07:00",
                        "timezone": "GMT-7",
                        "count": 1,
                        "heat_index_celsius": [31.0],
                        "relative_humidity_percent": [40.0],
                    },
                }
            },
        ]
    )
    adapter = LiveEnvParamsAdapter(client, sleep=lambda _: None)
    loaded = adapter.load(_env_request())
    assert loaded.activity_id == "env-1"
    assert submissions[0]["temperature"] == 35.0
    assert cast(dict[str, Any], submissions[0]["date_time"])["filter_type"] == 3
    assert [t.name for t in loaded.transformations] == ["live_envelope_unwrapped"]


def test_env_params_adapter_rejects_bad_date_before_submission() -> None:
    client, submissions = _adapter_client([{"data": {"activity_id": "env-1"}}])
    adapter = LiveEnvParamsAdapter(client, sleep=lambda _: None)
    with pytest.raises(ProviderError) as error:
        adapter.load(_env_request(start_date=date(2015, 1, 1)))
    assert error.value.kind is ProviderErrorKind.VALIDATION
    assert submissions == []
