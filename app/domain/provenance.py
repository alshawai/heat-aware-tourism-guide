"""Provenance and cache-identity contracts shared by live and fixture execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import PurePosixPath
import re
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
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class UpstreamAcquisitionReference:
    """A content-addressed link to an upstream fixture acquisition."""

    fixture: str
    role: str
    sha256: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.fixture)
        if not self.fixture or path.is_absolute() or path == PurePosixPath("."):
            raise ValueError("upstream fixture path must be repository-relative")
        if "\\" in self.fixture or ".." in path.parts:
            raise ValueError("upstream fixture path must not contain traversal")
        if not self.role.strip():
            raise ValueError("upstream acquisition role is required")
        if _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("upstream acquisition sha256 must be lowercase hexadecimal")

    def to_payload(self) -> dict[str, str]:
        return {"fixture": self.fixture, "role": self.role, "sha256": self.sha256}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "UpstreamAcquisitionReference":
        expected = {"fixture", "role", "sha256"}
        if set(payload) != expected:
            raise ValueError("upstream acquisition reference has invalid fields")
        if not all(isinstance(payload[field], str) for field in expected):
            raise ValueError("upstream acquisition reference fields must be strings")
        return cls(payload["fixture"], payload["role"], payload["sha256"])


@dataclass(frozen=True)
class AcquisitionRecord:
    """Where a committed fixture came from and under which request identity (ADR 0004).

    The sidecar ``request_configuration`` is the single authoritative fixture
    match identity; ``source`` tells the truth about origin — synthesized
    fixtures never carry fabricated activity IDs or retrieval times.
    """

    source: str
    provider: str
    endpoint: str
    request_configuration: dict[str, Any]
    retrieved_at: datetime | None
    data_date: str | None
    status: str
    schema_version: str
    provider_config_version: str | None
    activity_id: str | None
    derived_from: tuple[UpstreamAcquisitionReference, ...]
    transformations: tuple[Transformation, ...] = ()

    def __post_init__(self) -> None:
        if self.source not in _ACQUISITION_SOURCES:
            raise ValueError("acquisition source must be provider or synthesized")
        if not self.provider.strip():
            raise ValueError("acquisition provider is required")
        if not self.endpoint.strip():
            raise ValueError("acquisition endpoint is required")
        if self.source == "provider":
            if self.retrieved_at is None:
                raise ValueError("provider acquisitions require a retrieval time")
            if not (self.provider_config_version or "").strip():
                raise ValueError("provider acquisitions require a provider configuration version")
        elif self.retrieved_at is not None or self.activity_id is not None:
            raise ValueError("synthesized acquisitions cannot have retrieval times or activity IDs")
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
            "provider": self.provider,
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
            "derived_from": [reference.to_payload() for reference in self.derived_from],
            "transformations": [
                {"name": t.name, "version": t.version} for t in self.transformations
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AcquisitionRecord":
        expected = {
            "source",
            "provider",
            "endpoint",
            "request_configuration",
            "retrieved_at",
            "data_date",
            "status",
            "schema_version",
            "provider_config_version",
            "activity_id",
            "derived_from",
            "transformations",
        }
        if set(payload) != expected:
            raise ValueError("acquisition record has invalid fields")
        retrieved_at = payload["retrieved_at"]
        if retrieved_at is not None and not isinstance(retrieved_at, str):
            raise ValueError("acquisition retrieved_at must be an ISO 8601 string or null")
        request_configuration = payload["request_configuration"]
        if not isinstance(request_configuration, dict):
            raise ValueError("acquisition request_configuration must be an object")
        transformations = payload["transformations"]
        derived_from = payload["derived_from"]
        if not isinstance(transformations, list):
            raise ValueError("acquisition transformations must be an array")
        if not isinstance(derived_from, list):
            raise ValueError("acquisition derived_from must be an array")
        if not all(isinstance(item, dict) for item in derived_from):
            raise ValueError("acquisition derived_from entries must be objects")
        if not all(isinstance(item, dict) for item in transformations):
            raise ValueError("acquisition transformation entries must be objects")
        return cls(
            source=payload["source"],
            provider=payload["provider"],
            endpoint=payload["endpoint"],
            request_configuration=dict(request_configuration),
            retrieved_at=datetime.fromisoformat(retrieved_at) if retrieved_at is not None else None,
            data_date=payload["data_date"],
            status=payload["status"],
            schema_version=payload["schema_version"],
            provider_config_version=payload.get("provider_config_version"),
            activity_id=payload.get("activity_id"),
            derived_from=tuple(
                UpstreamAcquisitionReference.from_payload(item) for item in derived_from
            ),
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
