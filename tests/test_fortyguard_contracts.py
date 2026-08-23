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
        )


def test_heatmap_request_rejects_unknown_analytic_type() -> None:
    with pytest.raises(ValueError, match="analytic type"):
        HeatmapRequest(
            analytic_type="unknown",  # type: ignore[arg-type]
            latitude=29.4241,
            longitude=-98.4936,
            start_date=date(2026, 8, 23),
        )


def test_normalizer_preserves_forecast_provenance_and_units() -> None:
    request = HeatmapRequest(
        analytic_type=AnalyticType.TCM,
        latitude=29.4241,
        longitude=-98.4936,
        start_date=date(2026, 8, 23),
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


def test_fixture_and_live_execution_share_normalized_schema(tmp_path: Path) -> None:
    from app.execution import HeatmapExecution

    fixture = tmp_path / "heatmap.json"
    fixture.write_text('{"features": [{"geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"value": 35.5, "unit": "C", "valid_time": "2026-08-23T15:00:00+00:00"}}]}')
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
    assert transitions == (  # type: ignore[comparison-overlap]
        ["rate_limited", "server_error", "Completed"]
    )


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
        event_sink=events.append,
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
