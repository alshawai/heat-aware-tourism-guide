import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from app.integrations.overpass.errors import OverpassRateLimited
from app.integrations.overpass.transport import HttpOverpassTransport


def test_http_transport_posts_query_with_descriptive_user_agent() -> None:
    calls: list[object] = []

    class Response:
        def read(self) -> bytes:
            return json.dumps({"elements": []}).encode()

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def opener(request: object, timeout: float) -> Response:
        calls.append(request)
        assert timeout == 20
        return Response()

    transport = HttpOverpassTransport(
        "https://overpass.example.test/api/interpreter",
        user_agent="HeatAwareTourismGuide/0.1 (contact: team@example.test)",
        timeout_seconds=20,
        opener=opener,
    )
    assert transport.execute("[out:json];out;") == {"elements": []}
    request = calls[0]
    assert request.full_url == "https://overpass.example.test/api/interpreter"  # type: ignore[attr-defined]
    assert request.headers["User-agent"] == (  # type: ignore[attr-defined]
        "HeatAwareTourismGuide/0.1 (contact: team@example.test)"
    )
    assert request.data == b"data=%5Bout%3Ajson%5D%3Bout%3B"  # type: ignore[attr-defined]


def test_http_transport_classifies_429_for_client_retry() -> None:
    def opener(request: object, timeout: float) -> object:
        raise HTTPError("url", 429, "limited", Message(), None)

    transport = HttpOverpassTransport(
        "https://overpass.example.test/api/interpreter",
        user_agent="HeatAwareTourismGuide/0.1 (contact: team@example.test)",
        opener=opener,
    )
    with pytest.raises(OverpassRateLimited):
        transport.execute("query")


def test_http_transport_rejects_non_descriptive_user_agent() -> None:
    with pytest.raises(ValueError, match="descriptive User-Agent"):
        HttpOverpassTransport("https://overpass.example.test", user_agent="python")
