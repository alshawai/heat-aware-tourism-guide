"""Provenance and cache-identity contracts shared by live and fixture execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class CacheKey:
    value: str

    @classmethod
    def create(cls, endpoint: str, schema_version: str, payload: dict[str, Any]) -> "CacheKey":
        canonical = json.dumps(
            {"endpoint": endpoint, "schema_version": schema_version, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        return cls(digest)


@dataclass(frozen=True)
class Provenance:
    source: str
    retrieved_at: datetime
    data_date: str
    stale: bool
    forecast: bool
    activity_id: str | None = None
    raw_payload: dict[str, Any] | None = None

    @classmethod
    def cached(
        cls,
        *,
        retrieved_at: datetime,
        data_date: str,
        activity_id: str | None = None,
        raw_payload: dict[str, Any] | None = None,
        forecast: bool = False,
    ) -> "Provenance":
        return cls("cache", retrieved_at, data_date, True, forecast, activity_id, raw_payload)
