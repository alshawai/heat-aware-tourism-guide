from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Iterator

import pytest

from app.fortyguard import (
    AnalyticType,
    HeatmapRequest,
    ProviderErrorKind,
    FortyGuardClient,
    classify_provider_error,
    normalize_heatmap_response,
    poll_activity,
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
            {"features": [{"geometry": {"type": "Point", "coordinates": [1]}, "properties": {"value": 35, "unit": "C", "valid_time": "2026-08-23T15:00:00+00:00"}}]},
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
        {"features": [{"geometry": {"type": "Point", "coordinates": [-98.49, 29.42]}, "properties": {"value": 35.5, "unit": "C", "valid_time": "2026-08-23T15:00:00+00:00"}}]},
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
            {"features": [{"geometry": {"type": "Point", "coordinates": [-98.49, 29.42]}, "properties": {"value": True, "unit": "C", "valid_time": "2026-08-23T15:00:00+00:00"}}]},
            request=request,
            retrieved_at=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        )


def test_normalizer_rejects_non_finite_metric_values() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    with pytest.raises(ValueError, match="units"):
        normalize_heatmap_response(
            {"features": [{"geometry": {"type": "Point", "coordinates": [-98.49, 29.42]}, "properties": {"value": float("nan"), "unit": "C", "valid_time": "2026-08-23T15:00:00+00:00"}}]},
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )


def test_normalizer_rejects_provider_mode_mismatch() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    with pytest.raises(ValueError, match="mode"):
        normalize_heatmap_response(
            {"mode": "historical", "features": [{"geometry": {"type": "Point", "coordinates": [-98.49, 29.42]}, "properties": {"value": 35, "unit": "C", "valid_time": "2026-08-23T15:00:00+00:00"}}]},
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    ("fixture_name", "analytic_type", "forecast", "value"),
    [
        ("heatmap-forecast.json", AnalyticType.TCM, True, 35.5),
        ("heatmap-historical.json", AnalyticType.TCM, False, 33.2),
        ("heatmap-exceedance.json", AnalyticType.EXCEEDANCE, False, 6.0),
        ("heatmap-persistence.json", AnalyticType.PERSISTENCE, False, 4.0),
    ],
)
def test_committed_fixtures_normalize_to_the_same_tile_schema(
    fixture_name: str, analytic_type: AnalyticType, forecast: bool, value: float
) -> None:
    from app.execution import HeatmapExecution

    request = HeatmapRequest(
        analytic_type,
        29.4241,
        -98.4936,
        date.today() if forecast else date(2026, 8, 23),
        forecast=forecast,
        threshold_celsius=35 if analytic_type is not AnalyticType.TCM else None,
        direction="above" if analytic_type is not AnalyticType.TCM else None,
    )
    result = HeatmapExecution(fixture_path=Path("fixtures") / fixture_name).run(request)
    if analytic_type is AnalyticType.TCM:
        assert result.tiles[0].value_celsius == value
    else:
        assert result.tiles[0].value_celsius is None
    assert result.tiles[0].metric_value == value
    assert result.tiles[0].metric is analytic_type
    assert result.tiles[0].source == "fixture"
    assert result.provenance.forecast is forecast


def test_empty_failed_and_malformed_fixtures_are_rejected() -> None:
    from app.execution import HeatmapExecution

    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    for name in ("heatmap-empty.json", "heatmap-failed.json", "heatmap-malformed.json"):
        with pytest.raises(ValueError):
            HeatmapExecution(fixture_path=Path("fixtures") / name).run(request)


def test_fixture_mode_must_match_forecast_or_historical_request() -> None:
    from app.execution import HeatmapExecution

    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today(), forecast=True)
    with pytest.raises(ValueError, match="mode"):
        HeatmapExecution(fixture_path=Path("fixtures") / "heatmap-historical.json").run(request)


def test_fixture_request_identity_must_match_scenario() -> None:
    from app.execution import HeatmapExecution

    request = HeatmapRequest(AnalyticType.TCM, 30.2672, -97.7431, date(2026, 8, 23), forecast=False)
    with pytest.raises(ValueError, match="scenario"):
        HeatmapExecution(fixture_path=Path("fixtures") / "heatmap-historical.json").run(request)


def test_live_failure_replays_matching_cache_as_stale_data() -> None:
    from app.cache import CacheService
    from app.execution import HeatmapExecution

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
        },
        payload,
        retrieved_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        data_date="2026-08-20",
    )

    def failed(_: HeatmapRequest) -> dict[str, object]:
        raise ConnectionError("provider unavailable")

    result = HeatmapExecution(fixture_path=Path("fixtures") / "heatmap-historical.json", live_loader=failed, cache=cache).run(request, live=True)
    assert result.provenance.source == "cache"
    assert result.provenance.stale is True
    assert result.provenance.data_date == "2026-08-20"


def test_live_result_preserves_activity_id_and_malformed_payload_uses_cache() -> None:
    from app.cache import CacheService
    from app.execution import HeatmapExecution, LiveHeatmapPayload

    cache = CacheService()
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    payload = json.loads((Path("fixtures") / "heatmap-historical.json").read_text())
    cache.put(
        "/v1/heatmap", "v1", {"analytic_type": "tcm", "latitude": 29.4241, "longitude": -98.4936, "start_date": "2026-08-23", "forecast": False, "threshold_celsius": None, "direction": None}, payload,
        retrieved_at=datetime(2026, 8, 20, tzinfo=timezone.utc), data_date="2026-08-20", activity_id="cached",
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


def test_live_provenance_uses_provider_freshness_date() -> None:
    from app.execution import HeatmapExecution, LiveHeatmapPayload

    payload = json.loads((Path("fixtures") / "heatmap-historical.json").read_text())
    result = HeatmapExecution(
        fixture_path=Path("fixtures") / "heatmap-historical.json",
        live_loader=lambda _: LiveHeatmapPayload(payload, "live-1"),
    ).run(HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False), live=True)
    assert result.provenance.data_date == "2026-08-20"


def test_live_failure_without_matching_cache_is_not_silently_successful() -> None:
    from app.cache import CacheService
    from app.execution import HeatmapExecution

    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    with pytest.raises(ConnectionError, match="provider unavailable"):
        HeatmapExecution(
            fixture_path=Path("fixtures") / "heatmap-historical.json",
            live_loader=lambda _: (_ for _ in ()).throw(ConnectionError("provider unavailable")),
            cache=CacheService(),
        ).run(request, live=True)


def test_fixture_and_live_execution_share_normalized_schema(tmp_path: Path) -> None:
    from app.execution import HeatmapExecution

    fixture = tmp_path / "heatmap.json"
    fixture.write_text('{"mode": "historical", "features": [{"geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"value": 35.5, "unit": "C", "valid_time": "2026-08-23T15:00:00+00:00"}}]}')
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False)
    execution = HeatmapExecution(fixture_path=fixture, live_loader=lambda _: json.loads(fixture.read_text()))
    fixture_result = execution.run(request)
    live_result = execution.run(request, live=True)
    assert fixture_result.tiles[0].geometry == live_result.tiles[0].geometry
    assert fixture_result.tiles[0].value_celsius == live_result.tiles[0].value_celsius
    assert fixture_result.tiles[0].metric == live_result.tiles[0].metric
    assert fixture_result.provenance.source == "fixture"
    assert live_result.provenance.source == "provider"
    assert fixture_result.provenance.forecast is False


def test_polling_tolerates_one_post_submit_404_but_does_not_resubmit() -> None:
    responses: Iterator[dict[str, object]] = iter([{"status_code": 404}, {"status_code": 200, "status": "Completed", "result": {"ok": True}}])
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
        poll_activity("activity-1", get_status=lambda _: {"status": "Processing"}, sleep=lambda _: None, max_polls=1)


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
        FortyGuardClient(Transport(), "secret", clock=lambda: datetime.now(timezone.utc)).submit_and_poll("/v1/heatmap", {})


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
    from app.ledger import CreditLedger

    class Transport:
        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            return {"activity_id": "activity-1"}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            return {"status": "Completed", "credits_used": 4, "result": {"ok": True}}

    ledger = CreditLedger(5)
    FortyGuardClient(
        Transport(), "secret", clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc), ledger=ledger
    ).submit_and_poll("/v1/heatmap", {}, sleep=lambda _: None)
    assert ledger.total_used == 4
    assert ledger.records[0].endpoint == "/v1/heatmap"


def test_client_rejects_invalid_provider_credit_metadata() -> None:
    class Transport:
        def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
            return {"activity_id": "activity-1"}

        def get(self, endpoint: str, api_key: str) -> dict[str, object]:
            return {"status": "Completed", "credits_used": 1.5, "result": {"ok": True}}

    with pytest.raises(Exception, match="invalid credit"):
        FortyGuardClient(Transport(), "secret", clock=lambda: datetime.now(timezone.utc)).submit_and_poll(
            "/v1/heatmap", {}, sleep=lambda _: None
        )
