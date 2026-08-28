from datetime import date
import json
from typing import cast
from urllib.request import Request

import pytest

from app.integrations.fortyguard.usage import default_usage_window, fetch_custom_usage


def test_default_usage_window_is_thirty_days() -> None:
    assert default_usage_window(date(2026, 8, 24)) == (date(2026, 7, 25), date(2026, 8, 24))


def test_fetch_custom_usage_sends_quickstart_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"total_credits_used": 12}).encode()

    def fake_urlopen(request: object, timeout: float) -> Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("app.integrations.fortyguard.usage.urlopen", fake_urlopen)
    result = fetch_custom_usage("secret", date(2026, 8, 1), date(2026, 8, 24))

    request = cast(Request, captured["request"])
    assert result == {"total_credits_used": 12}
    assert cast(bytes, request.data).decode() == json.dumps(
        {
            "api_key": "secret",
            "start_date": "2026-08-01T00:00:00Z",
            "end_date": "2026-08-24T23:59:59Z",
        }
    )
    assert request.headers["Api-key"] == "secret"


def test_fetch_custom_usage_rejects_reversed_dates() -> None:
    with pytest.raises(ValueError, match="end date"):
        fetch_custom_usage("secret", date(2026, 8, 24), date(2026, 8, 1))
