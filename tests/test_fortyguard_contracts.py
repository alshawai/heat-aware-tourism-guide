from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Iterator

import pytest

from app.integrations.fortyguard.client import ActivityMetadata, FortyGuardClient, poll_activity
from app.integrations.fortyguard.contracts import (
    AnalyticType,
    HeatmapRequest,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.errors import (
    ProviderError,
    ProviderErrorKind,
    classify_provider_error,
)


def test_heatmap_request_requires_threshold_and_direction_for_exceedance() -> None:
    with pytest.raises(ValueError, match="threshold"):
        HeatmapRequest(
            analytic_type=AnalyticType.EXCEEDANCE,
            latitude=29.4241,
            longitude=-98.4936,
            start_date=date(2026, 8, 23),
            forecast=False,
        )


def test_heatmap_request_rejects_non_finite_thresholds() -> None:
    with pytest.raises(ValueError, match="threshold"):
        HeatmapRequest(
            AnalyticType.EXCEEDANCE,
            29.4241,
            -98.4936,
            date(2026, 8, 23),
            forecast=False,
            threshold_celsius=float("inf"),
            direction="above",
        )


def test_heatmap_request_rejects_non_finite_coordinates() -> None:
    with pytest.raises(ValueError, match="coordinates"):
        HeatmapRequest(AnalyticType.TCM, float("nan"), -98.4936, date.today())


def test_normalizer_rejects_malformed_point_coordinates() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    with pytest.raises(ValueError, match="geometry"):
        normalize_heatmap_response(
            {
                "features": [
                    {
                        "geometry": {"type": "Point", "coordinates": [1]},
                        "properties": {
                            "value": 35,
                            "unit": "C",
                            "valid_time": "2026-08-23T15:00:00+00:00",
                        },
                    }
                ]
            },
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )


def test_normalizer_accepts_valid_multipolygon_geometry() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [[[[1, 1], [2, 1], [2, 2], [1, 1]]]],
                    },
                    "properties": {
                        "value": 35,
                        "unit": "C",
                        "valid_time": "2026-08-23T15:00:00+00:00",
                    },
                }
            ]
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
    )
    assert result.tiles[0].geometry["type"] == "MultiPolygon"


def test_normalizer_accepts_flat_analytic_value_and_preserves_conversion() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [-98.49, 29.42]},
                    "properties": {
                        "metric": "tcm",
                        "value": 95,
                        "unit": "F",
                        "valid_time": "2026-08-23T15:00:00+00:00",
                    },
                }
            ]
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
    )
    assert result.tiles[0].value_celsius == pytest.approx((95 - 32) * 5 / 9)
    assert result.tiles[0].unit == "C"
    assert result.tiles[0].unit_source == "explicit"
    assert result.tiles[0].source_value == 95
    assert result.tiles[0].source_unit == "F"
    assert result.tiles[0].converted is True


def test_normalizer_rejects_missing_temperature_unit_instead_of_inferring() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    with pytest.raises(ValueError, match="unit"):
        normalize_heatmap_response(
            {
                "features": [
                    {
                        "geometry": {"type": "Point", "coordinates": [1, 1]},
                        "properties": {"value": 35, "valid_time": "2026-08-23T15:00:00+00:00"},
                    }
                ]
            },
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )


def test_normalizer_marks_caller_declared_unit_as_inferred() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [1, 1]},
                    "properties": {"value": 35, "valid_time": "2026-08-23T15:00:00Z"},
                }
            ]
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
        inferred_unit="C",
    )
    assert result.tiles[0].unit_source == "inferred"
    assert result.tiles[0].converted is False


def test_normalizer_rejects_mixed_temperature_source_units() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    features = [
        {
            "geometry": {"type": "Point", "coordinates": [1, 1]},
            "properties": {"value": 35, "unit": "C", "valid_time": "2026-08-23T15:00:00Z"},
        },
        {
            "geometry": {"type": "Point", "coordinates": [2, 2]},
            "properties": {"value": 95, "unit": "F", "valid_time": "2026-08-23T15:00:00Z"},
        },
    ]
    with pytest.raises(ValueError, match="mixed"):
        normalize_heatmap_response(
            {"features": features},
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )


def test_normalizer_rejects_conflicting_unit_fields_on_one_feature() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    properties = {
        "value": 35,
        "unit": "F",
        "temperature_unit": "C",
        "valid_time": "2026-08-23T15:00:00Z",
    }
    with pytest.raises(ValueError, match="conflicting metric units"):
        normalize_heatmap_response(
            {
                "features": [
                    {"geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": properties}
                ]
            },
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )


def test_normalizer_accepts_equivalent_unit_fields_on_one_feature() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [1, 1]},
                    "properties": {
                        "value": 35,
                        "unit": "Celsius",
                        "temperature_unit": "°C",
                        "valid_time": "2026-08-23T15:00:00Z",
                    },
                }
            ]
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
    )
    assert result.tiles[0].source_unit == "C"


def test_normalizer_reads_recorded_map_data_temperature_shape() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    result = normalize_heatmap_response(
        {
            "map_data": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 1]]],
                        },
                        "properties": {
                            "temperature": 36.71,
                            "unit": "C",
                            "valid_time": "2026-08-23T15:00:00Z",
                        },
                    }
                ],
            }
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
    )
    assert result.tiles[0].metric_value == 36.71


def test_recorded_map_data_without_provider_unit_or_freshness_is_rejected() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    payload = {
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 1]]],
                    },
                    "properties": {"temperature": 36.71},
                }
            ],
        }
    }
    with pytest.raises(ValueError, match="freshness"):
        normalize_heatmap_response(
            payload, request=request, retrieved_at=datetime.now(timezone.utc)
        )


def test_map_data_rejects_non_feature_members() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    payload = {
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Garbage",
                    "geometry": {"type": "Point", "coordinates": [1, 1]},
                    "properties": {
                        "temperature": 35,
                        "unit": "C",
                        "valid_time": "2026-08-23T15:00:00Z",
                    },
                }
            ],
        }
    }
    with pytest.raises(ValueError, match="feature"):
        normalize_heatmap_response(
            payload, request=request, retrieved_at=datetime.now(timezone.utc)
        )


def test_map_data_requires_feature_collection_type() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    map_data: dict[str, object] = {
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1, 1]},
                "properties": {"value": 35, "unit": "C", "valid_time": "2026-08-23T15:00:00Z"},
            }
        ],
    }
    payload: dict[str, object] = {"map_data": map_data}
    with pytest.raises(ValueError, match="feature collection"):
        normalize_heatmap_response(
            payload, request=request, retrieved_at=datetime.now(timezone.utc)
        )
    map_data["type"] = "NotAFeatureCollection"
    with pytest.raises(ValueError, match="feature collection"):
        normalize_heatmap_response(
            payload, request=request, retrieved_at=datetime.now(timezone.utc)
        )


def test_normalizer_rejects_conflicting_value_and_temperature() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    payload = {
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [1, 1]},
                "properties": {
                    "value": 35,
                    "temperature": 37,
                    "unit": "C",
                    "valid_time": "2026-08-23T15:00:00Z",
                },
            }
        ]
    }
    with pytest.raises(ValueError, match="conflicting properties.value and properties.temperature"):
        normalize_heatmap_response(
            payload, request=request, retrieved_at=datetime.now(timezone.utc)
        )


def test_normalizer_accepts_matching_value_and_temperature() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [1, 1]},
                    "properties": {
                        "value": 35,
                        "temperature": 35,
                        "unit": "C",
                        "valid_time": "2026-08-23T15:00:00Z",
                    },
                }
            ]
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
    )
    assert result.tiles[0].metric_value == 35


@pytest.mark.parametrize("temperature", [None, "35", {"value": 35}, [35]])  # type: ignore[misc]
def test_normalizer_rejects_malformed_temperature_when_value_is_present(
    temperature: object,
) -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    payload = {
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [1, 1]},
                "properties": {
                    "value": 35,
                    "temperature": temperature,
                    "unit": "C",
                    "valid_time": "2026-08-23T15:00:00Z",
                },
            }
        ]
    }
    with pytest.raises(ValueError, match="properties.temperature"):
        normalize_heatmap_response(
            payload,
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )


@pytest.mark.parametrize("feature_type", ["Garbage", None])  # type: ignore[misc]
def test_root_features_reject_present_non_feature_type(feature_type: object) -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    payload = {
        "features": [
            {
                "type": feature_type,
                "geometry": {"type": "Point", "coordinates": [1, 1]},
                "properties": {"value": 35, "unit": "C", "valid_time": "2026-08-23T15:00:00Z"},
            }
        ]
    }
    with pytest.raises(ValueError, match="feature"):
        normalize_heatmap_response(
            payload, request=request, retrieved_at=datetime.now(timezone.utc)
        )


def test_normalizer_rejects_missing_freshness_and_unknown_temperature_unit() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    base = {
        "geometry": {"type": "Point", "coordinates": [1, 1]},
        "properties": {"value": 35, "unit": "K"},
    }
    with pytest.raises(ValueError, match="freshness"):
        normalize_heatmap_response(
            {"features": [base]}, request=request, retrieved_at=datetime.now(timezone.utc)
        )
    base = {
        "geometry": {"type": "Point", "coordinates": [1, 1]},
        "properties": {"value": 35, "unit": "K", "valid_time": "2026-08-23T15:00:00+00:00"},
    }
    with pytest.raises(ValueError, match="units"):
        normalize_heatmap_response(
            {"features": [base]}, request=request, retrieved_at=datetime.now(timezone.utc)
        )


@pytest.mark.parametrize("valid_time", ["2026-08-23T15:00:00", "not-a-date"])  # type: ignore[misc]
def test_normalizer_rejects_ambiguous_or_malformed_freshness(valid_time: str) -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    with pytest.raises(ValueError, match="freshness"):
        normalize_heatmap_response(
            {
                "features": [
                    {
                        "geometry": {"type": "Point", "coordinates": [1, 1]},
                        "properties": {"value": 35, "unit": "C", "valid_time": valid_time},
                    }
                ]
            },
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )


def test_normalizer_preserves_complete_activity_metadata() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    activity = ActivityMetadata(
        "activity-1",
        datetime(2026, 8, 23, 14, tzinfo=timezone.utc),
        "/v1/heatmap",
        ("analytic_type",),
        ("Processing", "Completed"),
        {"request_id": "request-1"},
    )
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [1, 1]},
                    "properties": {"value": 35, "unit": "C", "valid_time": "2026-08-23T15:00:00Z"},
                }
            ]
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
        activity=activity,
    )
    assert result.activity == activity
    assert result.tiles[0].activity_id == "activity-1"


def test_heatmap_request_rejects_unknown_analytic_type() -> None:
    with pytest.raises(ValueError, match="analytic type"):
        HeatmapRequest(
            analytic_type="unknown",  # type: ignore[arg-type]
            latitude=29.4241,
            longitude=-98.4936,
            start_date=date(2026, 8, 23),
        )


def test_heatmap_request_rejects_non_boolean_forecast() -> None:
    with pytest.raises(ValueError, match="forecast"):
        HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today(), forecast="false")  # type: ignore[arg-type]


def test_normalizer_preserves_forecast_provenance_and_units() -> None:
    request = HeatmapRequest(
        analytic_type=AnalyticType.TCM,
        latitude=29.4241,
        longitude=-98.4936,
        start_date=date.today(),
    )
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [-98.49, 29.42]},
                    "properties": {
                        "value": 35.5,
                        "unit": "C",
                        "valid_time": "2026-08-23T15:00:00+00:00",
                    },
                }
            ]
        },
        request=request,
        retrieved_at=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        activity_id="activity-1",
    )
    assert result.tiles[0].value_celsius == 35.5
    assert result.provenance.forecast is True
    assert result.provenance.activity_id == "activity-1"


def test_normalizer_rejects_boolean_metric_values() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    with pytest.raises(ValueError, match="units"):
        normalize_heatmap_response(
            {
                "features": [
                    {
                        "geometry": {"type": "Point", "coordinates": [-98.49, 29.42]},
                        "properties": {
                            "value": True,
                            "unit": "C",
                            "valid_time": "2026-08-23T15:00:00+00:00",
                        },
                    }
                ]
            },
            request=request,
            retrieved_at=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        )


def test_normalizer_rejects_non_finite_metric_values() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    with pytest.raises(ValueError, match="units"):
        normalize_heatmap_response(
            {
                "features": [
                    {
                        "geometry": {"type": "Point", "coordinates": [-98.49, 29.42]},
                        "properties": {
                            "value": float("nan"),
                            "unit": "C",
                            "valid_time": "2026-08-23T15:00:00+00:00",
                        },
                    }
                ]
            },
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )


def test_normalizer_rejects_provider_mode_mismatch() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    with pytest.raises(ValueError, match="mode"):
        normalize_heatmap_response(
            {
                "mode": "historical",
                "features": [
                    {
                        "geometry": {"type": "Point", "coordinates": [-98.49, 29.42]},
                        "properties": {
                            "value": 35,
                            "unit": "C",
                            "valid_time": "2026-08-23T15:00:00+00:00",
                        },
                    }
                ],
            },
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )


@pytest.mark.parametrize(  # type: ignore[misc]
    ("fixture_name", "analytic_type", "forecast", "value"),
    [
        ("heatmap-forecast.json", AnalyticType.TCM, True, 35.5),
        ("heatmap-historical.json", AnalyticType.TCM, False, 33.2),
        ("heatmap-exceedance.json", AnalyticType.EXCEEDANCE, False, 6.0),
        ("heatmap-persistence.json", AnalyticType.PERSISTENCE, False, 4.0),
    ],
)
def test_committed_fixtures_normalize_to_the_same_tile_schema(
    fixture_name: str,
    analytic_type: AnalyticType,
    forecast: bool,
    value: float,
    tmp_path: Path,
) -> None:
    from app.services.execution import HeatmapExecution

    fixture_path = Path("fixtures") / fixture_name
    request_date = date.today() if forecast else date(2026, 8, 23)
    if forecast:
        fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixture_payload["request"]["start_date"] = request_date.isoformat()
        fixture_path = tmp_path / fixture_name
        fixture_path.write_text(json.dumps(fixture_payload), encoding="utf-8")

    request = HeatmapRequest(
        analytic_type,
        29.4241,
        -98.4936,
        request_date,
        forecast=forecast,
        threshold_celsius=35 if analytic_type is not AnalyticType.TCM else None,
        direction="above" if analytic_type is not AnalyticType.TCM else None,
    )
    result = HeatmapExecution(fixture_path=fixture_path).run(request)
    if analytic_type is AnalyticType.TCM:
        assert result.tiles[0].value_celsius == value
    else:
        assert result.tiles[0].value_celsius is None
    assert result.tiles[0].metric_value == value
    assert result.tiles[0].metric is analytic_type
    assert result.tiles[0].source == "fixture"
    assert result.provenance.forecast is forecast


def test_empty_failed_and_malformed_fixtures_are_rejected() -> None:
    from app.services.execution import HeatmapExecution, UnavailableError

    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    for name in ("heatmap-empty.json", "heatmap-failed.json", "heatmap-malformed.json"):
        with pytest.raises(UnavailableError):
            HeatmapExecution(fixture_path=Path("fixtures") / name).run(request)


def test_fixture_mode_must_match_forecast_or_historical_request() -> None:
    from app.services.execution import HeatmapExecution, UnavailableError

    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today(), forecast=True)
    with pytest.raises(UnavailableError, match="no matching fixture"):
        HeatmapExecution(fixture_path=Path("fixtures") / "heatmap-historical.json").run(request)


def test_fixture_request_identity_must_match_scenario() -> None:
    from app.services.execution import HeatmapExecution, UnavailableError

    request = HeatmapRequest(AnalyticType.TCM, 30.2672, -97.7431, date(2026, 8, 23), forecast=False)
    with pytest.raises(UnavailableError, match="no matching fixture"):
        HeatmapExecution(fixture_path=Path("fixtures") / "heatmap-historical.json").run(request)


def test_live_failure_replays_matching_cache_as_stale_data() -> None:
    from app.services.cache import CacheService
    from app.services.execution import HeatmapExecution

    cache = CacheService()
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    payload = json.loads((Path("fixtures") / "heatmap-historical.json").read_text())
    cache.put(
        "/v1/heatmap",
        "v1",
        {
            "analytic_type": "tcm",
            "latitude": 29.4241,
            "longitude": -98.4936,
            "start_date": "2026-08-23",
            "forecast": False,
            "threshold_celsius": None,
            "direction": None,
            "granularity": 60,
        },
        payload,
        retrieved_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        data_date="2026-08-20",
        provider_config_version="fortyguard-config-v1",
    )

    def failed(_: HeatmapRequest) -> dict[str, object]:
        raise ConnectionError("provider unavailable")

    result = HeatmapExecution(
        fixture_path=Path("fixtures") / "heatmap-historical.json", live_loader=failed, cache=cache
    ).run(request, live=True)
    assert result.provenance.source == "cache"
    assert result.provenance.stale is True
    assert result.provenance.data_date == "2026-08-20"


def test_live_result_preserves_activity_id_and_malformed_payload_uses_cache() -> None:
    from app.services.cache import CacheService
    from app.integrations.fortyguard.live import LiveHeatmapPayload
    from app.services.execution import HeatmapExecution

    cache = CacheService()
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    payload = json.loads((Path("fixtures") / "heatmap-historical.json").read_text())
    cache.put(
        "/v1/heatmap",
        "v1",
        {
            "analytic_type": "tcm",
            "latitude": 29.4241,
            "longitude": -98.4936,
            "start_date": "2026-08-23",
            "forecast": False,
            "threshold_celsius": None,
            "direction": None,
            "granularity": 60,
        },
        payload,
        retrieved_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        data_date="2026-08-20",
        activity_id="cached",
        provider_config_version="fortyguard-config-v1",
    )
    live = HeatmapExecution(
        fixture_path=Path("fixtures") / "heatmap-historical.json",
        live_loader=lambda _: LiveHeatmapPayload(payload, "live-1"),
    ).run(request, live=True)
    assert live.provenance.activity_id == "live-1"
    replayed = HeatmapExecution(
        fixture_path=Path("fixtures") / "heatmap-historical.json",
        live_loader=lambda _: {"features": [{"geometry": {}, "properties": {}}]},
        cache=cache,
    ).run(request, live=True)
    assert replayed.provenance.source == "cache"


def test_cache_replay_preserves_complete_activity_metadata() -> None:
    from app.integrations.fortyguard.live import LiveHeatmapPayload
    from app.services.cache import CacheService
    from app.services.execution import HeatmapExecution

    payload = json.loads((Path("fixtures") / "heatmap-historical.json").read_text())
    activity = ActivityMetadata(
        "live-1",
        datetime(2026, 8, 23, tzinfo=timezone.utc),
        "/v1/heatmap",
        ("analytic_type",),
        ("Completed",),
    )
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    cache = CacheService()
    execution = HeatmapExecution(
        fixture_path=Path("fixtures") / "heatmap-historical.json",
        live_loader=lambda _: LiveHeatmapPayload(payload, activity=activity),
        cache=cache,
    )
    assert execution.run(request, live=True).activity == activity
    execution.live_loader = lambda _: (_ for _ in ()).throw(ConnectionError("offline"))
    assert execution.run(request, live=True).activity == activity


def test_live_map_data_inferred_unit_survives_cache_replay() -> None:
    from app.integrations.fortyguard.live import LiveHeatmapPayload
    from app.services.cache import CacheService
    from app.services.execution import HeatmapExecution

    payload = {
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 1]]],
                    },
                    "properties": {"temperature": 36.71, "valid_time": "2026-08-23T15:00:00Z"},
                }
            ],
        }
    }
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    execution = HeatmapExecution(
        fixture_path=Path("fixtures") / "heatmap-historical.json",
        live_loader=lambda _: LiveHeatmapPayload(payload, inferred_unit="C"),
        cache=CacheService(),
    )
    assert execution.run(request, live=True).tiles[0].unit_source == "inferred"
    execution.live_loader = lambda _: (_ for _ in ()).throw(ConnectionError("offline"))
    assert execution.run(request, live=True).tiles[0].unit_source == "inferred"


def test_live_execution_rejects_conflicting_provider_unit_fields() -> None:
    from app.services.execution import HeatmapExecution, UnavailableError

    payload = {
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-98.4936, 29.4241]},
                    "properties": {
                        "temperature": 35,
                        "temperature_unit": "C",
                        "unit": "F",
                        "valid_time": "2026-08-23T15:00:00Z",
                    },
                }
            ],
        }
    }
    execution = HeatmapExecution(
        fixture_path=Path("fixtures") / "missing.json",
        live_loader=lambda _: payload,
    )
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    with pytest.raises(UnavailableError, match="live heatmap request failed"):
        execution.run(request, live=True)


def test_live_provenance_uses_provider_freshness_date() -> None:
    from app.integrations.fortyguard.live import LiveHeatmapPayload
    from app.services.execution import HeatmapExecution

    payload = json.loads((Path("fixtures") / "heatmap-historical.json").read_text())
    result = HeatmapExecution(
        fixture_path=Path("fixtures") / "heatmap-historical.json",
        live_loader=lambda _: LiveHeatmapPayload(payload, "live-1"),
    ).run(
        HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False),
        live=True,
    )
    assert result.provenance.data_date == "2026-08-20"


def test_live_failure_without_any_replay_source_is_not_silently_successful() -> None:
    from app.services.cache import CacheService
    from app.services.execution import HeatmapExecution, UnavailableError

    request = HeatmapRequest(AnalyticType.TCM, 29.43, -98.48, date(2026, 8, 23), forecast=False)
    with pytest.raises(UnavailableError, match="no matching cache entry or fixture"):
        HeatmapExecution(
            fixture_path=Path("fixtures") / "heatmap-historical.json",
            live_loader=lambda _: (_ for _ in ()).throw(ConnectionError("provider unavailable")),
            cache=CacheService(),
        ).run(request, live=True)


def test_fixture_and_live_execution_share_normalized_schema(tmp_path: Path) -> None:
    from app.services.execution import HeatmapExecution

    fixture = tmp_path / "heatmap.json"
    fixture.write_text(
        '{"mode": "historical", "request": {"analytic_type": "tcm", "latitude": 29.4241, "longitude": -98.4936, "start_date": "2026-08-23", "forecast": false, "threshold_celsius": null, "direction": null, "granularity": 60}, "features": [{"geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"value": 35.5, "unit": "C", "valid_time": "2026-08-23T15:00:00+00:00"}}]}'
    )
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    execution = HeatmapExecution(
        fixture_path=fixture, live_loader=lambda _: json.loads(fixture.read_text())
    )
    fixture_result = execution.run(request)
    live_result = execution.run(request, live=True)
    assert fixture_result.tiles[0].geometry == live_result.tiles[0].geometry
    assert fixture_result.tiles[0].value_celsius == live_result.tiles[0].value_celsius
    assert fixture_result.tiles[0].metric == live_result.tiles[0].metric
    assert fixture_result.provenance.source == "fixture"
    assert live_result.provenance.source == "provider"
    assert fixture_result.provenance.forecast is False


def test_polling_tolerates_one_post_submit_404_but_does_not_resubmit() -> None:
    responses: Iterator[dict[str, object]] = iter(
        [{"status_code": 404}, {"status_code": 200, "status": "Completed", "result": {"ok": True}}]
    )
    submitted = 0

    def get_status(_: str) -> dict[str, object]:
        return next(responses)

    result = poll_activity("activity-1", get_status=get_status, sleep=lambda _: None, max_polls=2)
    assert result == {"ok": True}
    assert submitted == 0


def test_polling_reports_failed_tasks_and_timeouts() -> None:
    with pytest.raises(Exception, match="task_failure"):
        poll_activity("activity-1", get_status=lambda _: {"status": "Failed"}, sleep=lambda _: None)
    with pytest.raises(Exception, match="timed out"):
        poll_activity(
            "activity-1",
            get_status=lambda _: {"status": "Processing"},
            sleep=lambda _: None,
            max_polls=1,
        )


def test_provider_errors_are_classified_without_exposing_response_body() -> None:
    error = classify_provider_error(401, "api key=secret")
    assert error.kind is ProviderErrorKind.AUTHENTICATION
    assert "secret" not in str(error)


def test_client_submits_once_and_captures_sanitized_activity_metadata() -> None:
    class Transport:
        def __init__(self) -> None:
            self.posts = 0

        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            self.posts += 1
            assert api_key == "secret"
            return {"activity_id": "activity-1"}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            return {"status": "Completed", "result": {"features": []}}

    transport = Transport()
    result, metadata = FortyGuardClient(
        transport, "secret", clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc)
    ).submit_and_poll("/v1/heatmap", {"analytic_type": "tcm"}, sleep=lambda _: None)
    assert result["features"] == []
    assert transport.posts == 1
    assert metadata.request_fields == ("analytic_type",)


def test_client_classifies_submit_errors_before_activity_lookup() -> None:
    class Transport:
        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            return {"status_code": 429, "detail": "slow down"}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            raise AssertionError("status lookup must not run")

    with pytest.raises(Exception, match="rate_limit"):
        FortyGuardClient(
            Transport(), "secret", clock=lambda: datetime.now(timezone.utc)
        ).submit_and_poll("/v1/heatmap", {})


def test_polling_retries_transient_status_transport_without_resubmission() -> None:
    responses: Iterator[dict[str, object]] = iter(
        [
            {"status_code": 429},
            {"status_code": 503},
            {"status_code": 200, "status": "Completed", "result": {"ok": True}},
        ]
    )
    transitions: list[str] = []

    result = poll_activity(
        "activity-1",
        get_status=lambda _: next(responses),
        sleep=lambda _: None,
        max_polls=3,
        on_transition=transitions.append,
    )

    assert result == {"ok": True}
    assert transitions == ["rate_limited", "server_error", "Completed"]


def test_polling_retries_status_timeout_within_bound() -> None:
    responses: Iterator[dict[str, object]] = iter(
        [{"status_code": 408}, {"status_code": 200, "status": "Completed", "result": {"ok": True}}]
    )
    assert poll_activity(
        "activity-1", get_status=lambda _: next(responses), sleep=lambda _: None, max_polls=2
    ) == {"ok": True}


def test_client_emits_sanitized_structured_activity_events() -> None:
    class Transport:
        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            return {"activity_id": "activity-1"}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            return {
                "status": "Completed",
                "result": {"features": []},
                "credits_used": 4,
            }

    events: list[dict[str, object]] = []
    _, metadata = FortyGuardClient(
        Transport(),
        "secret",
        clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc),
        event_sink=lambda event: events.append(dict(event)),
    ).submit_and_poll(
        "/v1/heatmap",
        {"analytic_type": "tcm", "api_key": "must-not-appear"},
        sleep=lambda _: None,
    )

    assert [event["event"] for event in events] == [
        "fortyguard.submitted",
        "fortyguard.status_transition",
        "fortyguard.completed",
    ]
    assert events[0]["request"] == {"analytic_type": "tcm", "api_key": "[redacted]"}
    assert "must-not-appear" not in repr(events)
    assert metadata.status_transitions == ("Completed",)


def test_client_records_provider_reported_credits_in_ledger() -> None:
    from app.domain.ledger import CreditLedger

    class Transport:
        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            return {"activity_id": "activity-1"}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            return {"status": "Completed", "credits_used": 4, "result": {"ok": True}}

    ledger = CreditLedger(5)
    FortyGuardClient(
        Transport(),
        "secret",
        clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc),
        ledger=ledger,
    ).submit_and_poll("/v1/heatmap", {}, sleep=lambda _: None)
    assert ledger.reported_credits == 4
    assert ledger.call_count == 1
    assert ledger.records[0].endpoint == "/v1/heatmap"


def test_client_logs_the_call_when_provider_reports_no_credits() -> None:
    """The real provider omits credits_used entirely (ADR 0004 §5).

    A silent provider must still produce a call record, otherwise the ledger
    stays empty in production and the budget can never enforce.
    """
    from app.domain.ledger import CreditLedger

    class SilentTransport:
        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            return {"activity_id": "activity-1"}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            return {"status": "Completed", "result": {"ok": True}}

    ledger = CreditLedger(5)
    FortyGuardClient(
        SilentTransport(),
        "secret",
        clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc),
        ledger=ledger,
    ).submit_and_poll("/v1/heatmap", {}, sleep=lambda _: None)
    assert ledger.call_count == 1
    assert ledger.records[0].credits_used is None
    assert ledger.reported_credits == 0


def test_client_refuses_to_spend_once_the_call_budget_is_exhausted() -> None:
    """Enforcement happens before the provider call, so no request is sent."""
    from app.domain.ledger import BudgetExceededError, CreditLedger, UsageRecord

    posts: list[str] = []

    class CountingTransport:
        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            posts.append(endpoint)
            return {"activity_id": "activity-2"}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            return {"status": "Completed", "result": {"ok": True}}

    clock = datetime(2026, 8, 23, tzinfo=timezone.utc)
    ledger = CreditLedger(
        1, initial_records=[UsageRecord("activity-1", "/v1/heatmap", None, clock, "completed")]
    )
    client = FortyGuardClient(CountingTransport(), "secret", clock=lambda: clock, ledger=ledger)
    with pytest.raises(BudgetExceededError):
        client.submit_and_poll("/v1/heatmap", {}, sleep=lambda _: None)
    assert posts == []


def test_client_rejects_invalid_provider_credit_metadata() -> None:
    class Transport:
        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            return {"activity_id": "activity-1"}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            return {"status": "Completed", "credits_used": 1.5, "result": {"ok": True}}

    with pytest.raises(Exception, match="invalid credit"):
        FortyGuardClient(
            Transport(), "secret", clock=lambda: datetime.now(timezone.utc)
        ).submit_and_poll("/v1/heatmap", {}, sleep=lambda _: None)


def test_client_records_accepted_submission_when_activity_id_is_missing() -> None:
    from app.domain.ledger import CreditLedger

    class Transport:
        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            return {"status_code": 202}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            raise AssertionError("malformed submission must not poll")

    ledger = CreditLedger(enrichment_budget=1)
    with pytest.raises(ProviderError, match="missing activity id"):
        FortyGuardClient(
            Transport(), "secret", clock=lambda: datetime.now(timezone.utc), ledger=ledger
        ).submit_and_poll("/v1/env_params", {}, scope="enrichment")
    assert len(ledger.records) == 1
    assert ledger.records[0].scope == "enrichment"
    assert ledger.records[0].status == "failed"


def test_client_keeps_core_environment_calls_on_core_budget() -> None:
    from app.domain.ledger import CreditLedger

    class Transport:
        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            return {"activity_id": "core-env"}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            return {"status": "Completed", "result": {"ok": True}}

    ledger = CreditLedger(budget=1, enrichment_budget=0)
    FortyGuardClient(
        Transport(), "secret", clock=lambda: datetime.now(timezone.utc), ledger=ledger
    ).submit_and_poll("/v1/env_params", {}, scope="core", sleep=lambda _: None)
    assert ledger.records[0].scope == "core"
