import json
from datetime import datetime

import pytest

from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.errors import ProviderError, ProviderErrorKind
from app.integrations.fortyguard.live import LiveFortyGuardTransport
from app.integrations.fortyguard.transport import HttpFortyGuardTransport


class _Response:
    def __init__(self, body: object) -> None:
        self._body = json.dumps(body).encode() if not isinstance(body, bytes) else body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _recording_transport(responses: list[object]) -> tuple[LiveFortyGuardTransport, list[tuple[str, dict[str, str]]]]:
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
        [{"error": False, "status_code": 200, "message": "Heatmap Submitted", "data": {"activity_id": "a1"}}]
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
            {"data": {"activity_id": "a1", "status": "Completed", "result": {"map_data": {}, "stats_data": {}}}},
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
            {"data": {"activity_id": "a1", "status": "Completed", "result": {"map_data": {}, "stats_data": {}}}},
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
