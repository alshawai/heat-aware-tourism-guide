"""Exact-cache and sidecar-fixture execution for shared OSM building acquisition.

One returned route set means one provider execution. When the provider fails,
replay falls back to an exact cache entry, then to a fixture whose sidecar
identity matches this request exactly, and finally to explicit unavailability —
never to a silently substituted building set (ADR 0004, ADR 0007).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from app.domain.hotels import BoundingBox
from app.domain.provenance import CacheKey
from app.integrations.overpass.buildings import building_request_payload, osm_source_timestamp
from app.integrations.overpass.errors import OverpassError
from app.services.cache import CacheService
from app.services.sidecars import load_acquisition_record

DEFAULT_SCHEMA_VERSION = "building-v1"
DEFAULT_PROVIDER_CONFIG_VERSION = "overpass-building-config-v1"
DEFAULT_MODEL_VERSION = "route-shade-v1"


class BuildingsUnavailable(RuntimeError):
    """No provider, exact cache entry, or matching fixture can supply buildings."""


@dataclass(frozen=True)
class BuildingOutcome:
    """One shared building response and where it actually came from.

    ``retrieved_at`` is ``None`` only for a synthesized fixture, which has no
    provider retrieval time to report; ``data_date`` is always the true OSM
    source date, including on stale replay.
    """

    payload: Mapping[str, Any]
    source: str
    stale: bool
    retrieved_at: datetime | None
    data_date: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.source not in {"provider", "cache", "fixture"}:
            raise ValueError("building source must be provider, cache, or fixture")
        if not self.data_date.strip():
            raise ValueError("building outcome requires the OSM data date")


class BuildingExecution:
    """Acquire one shared building set: live, then exact cache, then exact fixture."""

    def __init__(
        self,
        *,
        live_loader: Callable[[BoundingBox], Mapping[str, Any]] | None = None,
        cache: CacheService | None = None,
        fixture_path: Path | None = None,
        endpoint: str,
        schema_version: str = DEFAULT_SCHEMA_VERSION,
        provider_config_version: str = DEFAULT_PROVIDER_CONFIG_VERSION,
        model_version: str = DEFAULT_MODEL_VERSION,
        search_distance_m: float,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        if not endpoint.strip():
            raise ValueError("building execution requires an Overpass endpoint")
        self.live_loader = live_loader
        self.cache = cache
        self.fixture_path = fixture_path
        self.endpoint = endpoint
        self.schema_version = schema_version
        self.provider_config_version = provider_config_version
        self.model_version = model_version
        self.search_distance_m = search_distance_m
        self.clock = clock

    def identity(self, aoi: BoundingBox) -> dict[str, Any]:
        """The complete request identity this AOI caches and replays under."""
        return building_request_payload(
            aoi,
            search_distance_m=self.search_distance_m,
            model_version=self.model_version,
        )

    def run(self, aoi: BoundingBox) -> BuildingOutcome:
        identity = self.identity(aoi)
        if self.live_loader is None:
            fallback = self._fallback(identity)
            if fallback is not None:
                return fallback
            raise BuildingsUnavailable("live building acquisition is not configured")
        try:
            payload = self.live_loader(aoi)
            data_date = osm_source_timestamp(payload).date().isoformat()
        except (OverpassError, ConnectionError, OSError, TimeoutError, ValueError):
            fallback = self._fallback(identity)
            if fallback is not None:
                return fallback
            raise BuildingsUnavailable(
                "the building request failed and no matching cache entry or fixture is available"
            ) from None
        retrieved_at = self.clock()
        if self.cache is not None:
            self.cache.put(
                self.endpoint,
                self.schema_version,
                identity,
                payload,
                retrieved_at=retrieved_at,
                data_date=data_date,
                provider_config_version=self.provider_config_version,
            )
        return BuildingOutcome(payload, "provider", False, retrieved_at, data_date)

    def _fallback(self, identity: dict[str, Any]) -> BuildingOutcome | None:
        if self.cache is not None:
            cached = self.cache.get(
                CacheKey.create(
                    self.endpoint,
                    self.schema_version,
                    identity,
                    self.provider_config_version,
                )
            )
            if cached is not None:
                return BuildingOutcome(
                    cached.payload,
                    "cache",
                    True,
                    cached.provenance.retrieved_at,
                    cached.provenance.data_date,
                    reason="replayed the exact cached building response; stale",
                )
        return self._fixture(identity)

    def _fixture(self, identity: dict[str, Any]) -> BuildingOutcome | None:
        """Replay the committed fixture only when its sidecar identity matches exactly."""
        if self.fixture_path is None:
            return None
        try:
            record = load_acquisition_record(self.fixture_path)
            if (
                record is None
                or not record.replayable
                or record.endpoint != self.endpoint
                or record.schema_version != self.schema_version
                or record.provider_config_version != self.provider_config_version
                or record.request_configuration != identity
                or record.data_date is None
            ):
                return None
            payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                return None
        except (OSError, ValueError, KeyError):
            return None
        return BuildingOutcome(
            payload,
            "fixture",
            True,
            record.retrieved_at,
            record.data_date,
            reason="replayed the matching committed building fixture; stale",
        )
