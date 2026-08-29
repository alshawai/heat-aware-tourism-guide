"""HTTP transport boundary for Overpass."""

from __future__ import annotations

import json
import socket
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.integrations.overpass.errors import OverpassError, OverpassRateLimited


class HttpOverpassTransport:
    def __init__(
        self,
        endpoint: str,
        *,
        user_agent: str,
        timeout_seconds: float = 30,
        opener: Callable[..., object] = urlopen,
    ) -> None:
        normalized_agent = user_agent.strip().lower()
        if len(normalized_agent) < 20 or "contact" not in normalized_agent:
            raise ValueError("Overpass requires a descriptive User-Agent with contact information")
        if timeout_seconds <= 0:
            raise ValueError("Overpass timeout must be positive")
        self.endpoint = endpoint
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def execute(self, query: str) -> dict[str, object]:
        request = Request(
            self.endpoint,
            data=urlencode({"data": query}).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:  # type: ignore[attr-defined]
                parsed = json.loads(response.read())
        except HTTPError as error:
            if error.code == 429:
                raise OverpassRateLimited("Overpass rate limit exceeded") from None
            raise OverpassError(f"Overpass HTTP request failed ({error.code})") from None
        except (TimeoutError, URLError, OSError, socket.timeout) as error:
            raise OverpassError(f"Overpass request failed: {type(error).__name__}") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise OverpassError("Overpass returned invalid JSON") from None
        if not isinstance(parsed, Mapping):
            raise OverpassError("Overpass response must be an object")
        return dict(parsed)
