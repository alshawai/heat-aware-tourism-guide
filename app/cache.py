"""Small cache contract that keeps replayed data visibly distinct from live data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
import re

from app.domain import CacheKey, Provenance


@dataclass(frozen=True)
class CacheEntry:
    payload: Mapping[str, Any]
    provenance: Provenance


class CacheService:
    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}

    def put(
        self,
        endpoint: str,
        schema_version: str,
        request_payload: dict[str, Any],
        response_payload: Mapping[str, Any],
        *,
        retrieved_at: datetime,
        data_date: str,
        activity_id: str | None = None,
    ) -> CacheKey:
        key = CacheKey.create(endpoint, schema_version, request_payload)
        sanitized = _sanitize(response_payload)
        self._entries[key.value] = CacheEntry(
            sanitized,
            Provenance("provider", retrieved_at, data_date, False, False, activity_id, sanitized),
        )
        return key

    def get(self, key: CacheKey) -> CacheEntry | None:
        entry = self._entries.get(key.value)
        if entry is None:
            return None
        return CacheEntry(entry.payload, Provenance.cached(
            retrieved_at=entry.provenance.retrieved_at,
            data_date=entry.provenance.data_date,
            activity_id=entry.provenance.activity_id,
            raw_payload=entry.provenance.raw_payload,
            forecast=entry.provenance.forecast,
        ))


def _sanitize(value: object) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if re.search(r"(?i)(api[_ -]?key|authorization|token)", str(key)) else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if not isinstance(value, (str, int, float, bool, type(None))):
        raise ValueError("cached response must be an object")
    return value
