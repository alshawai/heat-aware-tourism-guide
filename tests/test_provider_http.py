from datetime import date
import json
import socket
from urllib.error import URLError

import pytest

from app.integrations.fortyguard.contracts import (
    AnalyticType,
    EnvParamsRequest,
    HeatmapRequest,
)
from app.integrations.fortyguard.errors import (
    ProviderErrorKind,
    classify_provider_error,
)
from app.integrations.fortyguard.transport import HttpFortyGuardTransport


def test_heatmap_payload_preserves_forecast_history_and_threshold_contract() -> None:
    payload = HeatmapRequest(
        AnalyticType.EXCEEDANCE,
        29.4241,
        -98.4936,
        date(2026, 8, 20),
        forecast=False,
        threshold_celsius=35,
        direction="above",
    ).to_payload()
    assert payload == {
        "analytic_type": "exceedance",
        "latitude": 29.4241,
        "longitude": -98.4936,
        "start_date": "2026-08-20",
        "forecast": False,
        "threshold_celsius": 35,
        "direction": "above",
    }


def test_env_params_requires_temperature_anchor_and_marks_anchor_series() -> None:
    request = EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 23), temperature_anchor_celsius=35)
    assert request.to_payload()["temperature_anchor_celsius"] == 35
    assert request.is_real_forecast is False
    with pytest.raises(ValueError, match="temperature anchor"):
        EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 23), temperature_anchor_celsius=None)
    with pytest.raises(ValueError, match="real forecast"):
        EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 23), 35, is_real_forecast=True)
    with pytest.raises(ValueError, match="temperature anchor"):
        EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 23), float("nan"))


def test_area_request_rejects_unknown_analytic_members() -> None:
    with pytest.raises(ValueError, match="analytic types"):
        from app.integrations.fortyguard.contracts import AreaHeatmapRequest

        AreaHeatmapRequest(
            {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 1]]]},
            ("unknown",),  # type: ignore[arg-type]
            "district",
            "C",
            "explicit",
        )


def test_area_request_rejects_malformed_polygon_coordinates() -> None:
    from app.integrations.fortyguard.contracts import AreaHeatmapRequest

    with pytest.raises(ValueError, match="polygon geometry"):
        AreaHeatmapRequest(
            {"type": "Polygon", "coordinates": [[[1, 1], [2, 1]]]},
            (AnalyticType.TCM,),
            "district",
            "C",
            "explicit",
        )


def test_area_request_rejects_unclosed_polygon_ring() -> None:
    from app.integrations.fortyguard.contracts import AreaHeatmapRequest

    with pytest.raises(ValueError, match="polygon geometry"):
        AreaHeatmapRequest(
            {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 2]]]},
            (AnalyticType.TCM,),
            "district",
            "C",
            "explicit",
        )


def test_area_request_rejects_self_intersecting_polygon() -> None:
    from app.integrations.fortyguard.contracts import AreaHeatmapRequest

    with pytest.raises(ValueError, match="polygon geometry"):
        AreaHeatmapRequest(
            {"type": "Polygon", "coordinates": [[[1, 1], [2, 2], [2, 1], [1, 2], [1, 1]]]},
            (AnalyticType.TCM,),
            "district",
            "C",
            "explicit",
        )


def test_area_request_accepts_valid_multipolygon_coordinates() -> None:
    from app.integrations.fortyguard.contracts import AreaHeatmapRequest

    request = AreaHeatmapRequest(
        {"type": "MultiPolygon", "coordinates": [[[[1, 1], [2, 1], [2, 2], [1, 1]]]]},
        (AnalyticType.TCM,),
        "district",
        "C",
        "explicit",
    )
    assert request.to_payload()["context"] == "district"


def test_http_transport_sends_auth_json_and_classifies_http_errors() -> None:
    calls: list[tuple[str, dict[str, object], dict[str, str]]] = []

    class Response:
        def read(self) -> bytes:
            return json.dumps({"activity_id": "a1"}).encode()

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def opener(request: object, timeout: float) -> Response:
        calls.append((request.full_url, json.loads(request.data), dict(request.headers)))  # type: ignore[attr-defined]
        return Response()

    transport = HttpFortyGuardTransport("https://api.example.test", opener=opener)
    assert transport.post("/v1/heatmap", {"analytic_type": "tcm"}, "secret") == {"activity_id": "a1"}
    assert calls[0][0] == "https://api.example.test/v1/heatmap"
    assert calls[0][1] == {"analytic_type": "tcm"}
    assert calls[0][2]["Api-key"] == "secret"

    class ErrorResponse:
        status = 429
        reason = "too many requests"

        def read(self) -> bytes:
            return b"ignored"

    def error_opener(request: object, timeout: float) -> ErrorResponse:
        raise HttpFortyGuardTransport.HttpError(ErrorResponse())

    failing = HttpFortyGuardTransport("https://api.example.test", opener=error_opener)
    assert failing.get("/v1/status/a1", "secret") == {"status_code": 429}


def test_status_transport_returns_transient_status_for_bounded_poller() -> None:
    class ErrorResponse:
        status = 404

    def opener(request: object, timeout: float) -> object:
        raise HttpFortyGuardTransport.HttpError(ErrorResponse())

    transport = HttpFortyGuardTransport("https://api.example.test", opener=opener)
    assert transport.get("/v1/status/a1", "secret") == {"status_code": 404}


def test_http_408_is_classified_as_timeout() -> None:
    assert classify_provider_error(408).kind is ProviderErrorKind.TIMEOUT


def test_wrapped_socket_timeout_is_classified_as_timeout() -> None:
    def opener(request: object, timeout: float) -> object:
        raise URLError(socket.timeout("timed out"))

    with pytest.raises(Exception) as error:
        HttpFortyGuardTransport("https://api.example.test", opener=opener).get("/v1/status/a1", "secret")
    assert error.value.kind is ProviderErrorKind.TIMEOUT
