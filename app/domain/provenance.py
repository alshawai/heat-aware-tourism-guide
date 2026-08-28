"""Provenance and cache-identity contracts shared by live and fixture execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class Transformation:
    """A named, versioned inference or reshaping step applied on the live path (ADR 0002)."""

    name: str
    version: int

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("transformation name is required")
        if self.version < 1:
            raise ValueError("transformation version must be positive")


@dataclass(frozen=True)
class CacheKey:
    value: str

    @classmethod
    def create(
        cls,
        endpoint: str,
        schema_version: str,
        payload: dict[str, Any],
        provider_config_version: str,
    ) -> "CacheKey":
        """Hash the complete cache identity (ADR 0004).

        Two responses only share a key when endpoint, internal schema version,
        the complete request payload, and the provider configuration version
        all agree.
        """
        canonical = json.dumps(
            {
                "endpoint": endpoint,
                "schema_version": schema_version,
                "payload": payload,
                "provider_config_version": provider_config_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        return cls(digest)


_ACQUISITION_SOURCES = ("provider", "synthesized")
_ACQUISITION_REPLAYABLE_STATUS = "ok"


@dataclass(frozen=True)
class AcquisitionRecord:
    """Where a committed fixture came from and under which request identity (ADR 0004).

    The sidecar ``request_configuration`` is the single authoritative fixture
    match identity; ``source`` tells the truth about origin — synthesized
    fixtures never carry fabricated activity IDs or retrieval times.
    """

    source: str
    endpoint: str
    request_configuration: dict[str, Any]
    retrieved_at: datetime | None
    data_date: str | None
    status: str
    schema_version: str
    provider_config_version: str | None
    activity_id: str | None
    transformations: tuple[Transformation, ...] = ()

    def __post_init__(self) -> None:
        if self.source not in _ACQUISITION_SOURCES:
            raise ValueError("acquisition source must be provider or synthesized")
        if not self.endpoint.strip():
            raise ValueError("acquisition endpoint is required")
        if self.status == _ACQUISITION_REPLAYABLE_STATUS and not (self.data_date or "").strip():
            raise ValueError("replayable acquisitions require a data date")
        if not self.status.strip():
            raise ValueError("acquisition status is required")
        if not self.schema_version.strip():
            raise ValueError("acquisition schema version is required")

    @property
    def replayable(self) -> bool:
        return self.status == _ACQUISITION_REPLAYABLE_STATUS

    def to_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "endpoint": self.endpoint,
            "request_configuration": self.request_configuration,
            "retrieved_at": self.retrieved_at.isoformat()
            if self.retrieved_at is not None
            else None,
            "data_date": self.data_date,
            "status": self.status,
            "schema_version": self.schema_version,
            "provider_config_version": self.provider_config_version,
            "activity_id": self.activity_id,
            "transformations": [
                {"name": t.name, "version": t.version} for t in self.transformations
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AcquisitionRecord":
        retrieved_at = payload.get("retrieved_at")
        transformations = payload.get("transformations") or []
        return cls(
            source=payload["source"],
            endpoint=payload["endpoint"],
            request_configuration=dict(payload.get("request_configuration") or {}),
            retrieved_at=datetime.fromisoformat(retrieved_at) if retrieved_at else None,
            data_date=payload["data_date"],
            status=payload["status"],
            schema_version=payload["schema_version"],
            provider_config_version=payload.get("provider_config_version"),
            activity_id=payload.get("activity_id"),
            transformations=tuple(
                Transformation(item["name"], item["version"]) for item in transformations
            ),
        )


@dataclass(frozen=True)
class Provenance:
    source: str
    retrieved_at: datetime
    data_date: str
    stale: bool
    forecast: bool
    activity_id: str | None = None
    raw_payload: dict[str, Any] | None = None
    transformations: tuple[Transformation, ...] = ()

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
