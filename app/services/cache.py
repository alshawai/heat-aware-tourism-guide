"""Small cache contract that keeps replayed data visibly distinct from live data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.domain.provenance import CacheKey, Provenance
from app.domain.security import sanitize_payload


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
        forecast: bool = False,
        provider_config_version: str,
    ) -> CacheKey:
        key = CacheKey.create(endpoint, schema_version, request_payload, provider_config_version)
        sanitized = sanitize_payload(response_payload)
        self._entries[key.value] = CacheEntry(
            sanitized,
            Provenance(
                "provider", retrieved_at, data_date, False, forecast, activity_id, sanitized
            ),
        )
        return key

    def get(self, key: CacheKey) -> CacheEntry | None:
        entry = self._entries.get(key.value)
        if entry is None:
            return None
        return CacheEntry(
            entry.payload,
            Provenance.cached(
                retrieved_at=entry.provenance.retrieved_at,
                data_date=entry.provenance.data_date,
                activity_id=entry.provenance.activity_id,
                raw_payload=entry.provenance.raw_payload,
                forecast=entry.provenance.forecast,
            ),
        )
