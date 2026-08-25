"""Credential-safe FortyGuard account usage queries."""

from __future__ import annotations

from datetime import date, timedelta
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://api.fortyguard.com"


def fetch_custom_usage(
    api_key: str,
    start_date: date,
    end_date: date,
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    """Fetch the provider's credit breakdown without exposing the API key."""
    if not api_key:
        raise ValueError("an API key is required")
    if end_date < start_date:
        raise ValueError("end date must not precede start date")

    payload = {
        "api_key": api_key,
        "start_date": f"{start_date.isoformat()}T00:00:00Z",
        "end_date": f"{end_date.isoformat()}T23:59:59Z",
    }
    request = Request(
        f"{base_url.rstrip('/')}/v1/system/fetch-api-key-custom-usage",
        data=json.dumps(payload).encode(),
        headers={"api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        raise RuntimeError(f"FortyGuard usage request failed with HTTP {error.code}") from None
    except (URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"FortyGuard usage request failed: {type(error).__name__}") from None
    if not isinstance(result, dict):
        raise ValueError("FortyGuard usage response must be an object")
    return result


def default_usage_window(today: date | None = None) -> tuple[date, date]:
    """Return the quickstart's rolling 30-day usage window."""
    end_date = today or date.today()
    return end_date - timedelta(days=30), end_date


def load_api_key_from_environment() -> str:
    """Load the key from the process environment without reading or printing it."""
    api_key = os.environ.get("FORTYGUARD_API_KEY", "")
    if not api_key:
        raise RuntimeError("FORTYGUARD_API_KEY is not set")
    return api_key
