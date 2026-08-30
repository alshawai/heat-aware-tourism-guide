"""Short-lived signed references to server-owned analysis result sets."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from typing import Any, Mapping


class ResultTokenError(ValueError):
    """Raised when a result-set token is malformed, expired, or invalid."""


def issue_result_token(
    payload: Mapping[str, Any],
    secret: str,
    *,
    now: datetime | None = None,
    ttl: timedelta = timedelta(minutes=15),
) -> str:
    if not secret:
        raise ValueError("result token secret is required")
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    body = dict(payload)
    body["issued_at"] = issued.isoformat()
    body["expires_at"] = (issued + ttl).isoformat()
    encoded = _encode(body)
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return f"{_b64(encoded)}.{_b64(signature)}"


def verify_result_token(
    token: str,
    secret: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not secret or not isinstance(token, str):
        raise ResultTokenError("invalid result_set_token")
    try:
        encoded_text, signature_text = token.split(".", 1)
        encoded = _unb64(encoded_text)
        signature = _unb64(signature_text)
        expected = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ResultTokenError("invalid result_set_token")
        payload = json.loads(encoded)
        if not isinstance(payload, dict):
            raise ResultTokenError("invalid result_set_token")
        expires = datetime.fromisoformat(payload["expires_at"])
        if expires <= (now or datetime.now(timezone.utc)).astimezone(timezone.utc):
            raise ResultTokenError("result_set_expired")
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        if isinstance(error, ResultTokenError):
            raise
        raise ResultTokenError("invalid result_set_token") from error


def _encode(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
