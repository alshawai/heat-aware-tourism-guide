"""Validated transport boundary for OSRM route requests."""

from __future__ import annotations

import json
import socket
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from app.integrations.osrm.errors import OsrmMalformedResponse, OsrmTransportError


class HttpOsrmTransport:
    def __init__(
        self,
        base_url: str,
        *,
        user_agent: str,
        timeout_seconds: float = 15.0,
        opener: Callable[..., object] = urlopen,
    ) -> None:
        if not base_url.strip():
            raise ValueError("OSRM base URL is required")
        if timeout_seconds <= 0:
            raise ValueError("OSRM timeout must be positive")
        if len(user_agent.strip()) < 20 or "contact" not in user_agent.lower():
            raise ValueError("OSRM requires a descriptive User-Agent with contact information")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self._opener = opener

    def get(self, path: str, params: dict[str, str]) -> dict[str, object]:
        query = urlencode(params)
        request = Request(
            f"{self.base_url}/{path.lstrip('/')}?{query}",
            headers={"User-Agent": self.user_agent},
            method="GET",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:  # type: ignore[attr-defined]
                payload = json.loads(response.read())
        except HTTPError as error:
            raise OsrmTransportError(f"OSRM HTTP request failed ({error.code})") from None
        except (TimeoutError, URLError, OSError, socket.timeout) as error:
            raise OsrmTransportError(f"OSRM request failed: {type(error).__name__}") from None
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise OsrmMalformedResponse("OSRM returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise OsrmMalformedResponse("OSRM response must be an object")
        return payload
