"""HTTP transport boundary for the FortyGuard API."""

from __future__ import annotations

from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import socket

from app.integrations.fortyguard.errors import (
    ProviderError,
    ProviderErrorKind,
    classify_provider_error,
)


class FortyGuardTransport(Protocol):
    def post(
        self, endpoint: str, payload: Mapping[str, object], api_key: str
    ) -> Mapping[str, object]: ...

    def get(self, endpoint: str, api_key: str) -> Mapping[str, object]: ...


class HttpFortyGuardTransport:
    class HttpError(Exception):
        def __init__(self, response: object) -> None:
            self.response = response

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30,
        opener: Callable[..., object] = urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def post(
        self, endpoint: str, payload: Mapping[str, object], api_key: str
    ) -> Mapping[str, object]:
        return self._request(endpoint, api_key, payload)

    def get(self, endpoint: str, api_key: str) -> Mapping[str, object]:
        return self._request(endpoint, api_key)

    def _request(
        self, endpoint: str, api_key: str, payload: Mapping[str, object] | None = None
    ) -> Mapping[str, object]:
        request = Request(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:  # type: ignore[attr-defined]
                parsed = json.loads(response.read())
        except self.HttpError as error:
            status = getattr(error.response, "status", None)
            if payload is None and (
                status in (404, 408, 429) or isinstance(status, int) and status >= 500
            ):
                return {"status_code": status}
            raise classify_provider_error(status, "provider HTTP request failed") from None
        except HTTPError as error:
            if payload is None and (error.code in (404, 408, 429) or error.code >= 500):
                return {"status_code": error.code}
            raise classify_provider_error(error.code, "provider HTTP request failed") from None
        except (TimeoutError, URLError, OSError) as error:
            wrapped_timeout = isinstance(error, URLError) and isinstance(
                error.reason, socket.timeout
            )
            kind = (
                ProviderErrorKind.TIMEOUT
                if isinstance(error, (TimeoutError, socket.timeout)) or wrapped_timeout
                else ProviderErrorKind.SERVER
            )
            raise ProviderError(kind, detail=type(error).__name__) from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderError(
                ProviderErrorKind.MALFORMED_RESPONSE, detail="invalid JSON response"
            ) from None
        if not isinstance(parsed, Mapping):
            raise ProviderError(
                ProviderErrorKind.MALFORMED_RESPONSE, detail="response must be an object"
            )
        return parsed
