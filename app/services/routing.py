"""Exact-cache and sidecar-fixture execution for OSRM routes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from app.domain.provenance import CacheKey
from app.domain.routing import RouteRequest, RouteSet
from app.integrations.osrm.client import normalize_response
from app.integrations.osrm.errors import OsrmError
from app.services.cache import CacheService
from app.services.sidecars import load_acquisition_record


class RouteUnavailable(RuntimeError):
    """No provider, exact cache entry, or exact fixture can supply routes."""


@dataclass(frozen=True)
class RouteOutcome:
    routes: RouteSet
    source: str
    stale: bool
    retrieved_at: datetime
    data_date: str


class RouteExecution:
    def __init__(
        self,
        *,
        fixture_path: Path,
        live_loader: Callable[[RouteRequest], Mapping[str, object]] | None = None,
        cache: CacheService | None = None,
        endpoint: str = "https://routing.openstreetmap.de/routed-foot/route/v1",
        schema_version: str = "v1",
        provider_config_version: str = "osrm-config-v1",
    ) -> None:
        self.fixture_path = fixture_path
        self.live_loader = live_loader
        self.cache = cache
        self.endpoint = endpoint
        self.schema_version = schema_version
        self.provider_config_version = provider_config_version

    def run(self, request: RouteRequest, *, live: bool = False) -> RouteOutcome:
        if not live:
            fixture = self._fixture(request, stale=False)
            if fixture is None:
                raise RouteUnavailable("no matching fixture for the requested route scenario")
            return fixture
        if self.live_loader is None:
            raise RouteUnavailable("live route execution is not configured")
        identity = route_request_payload(request)
        try:
            payload = self.live_loader(request)
            routes = normalize_response(payload, provider_instance=request.provider_instance)
        except (OsrmError, OSError, TimeoutError, ValueError):
            fallback = self._fallback(request, identity)
            if fallback is not None:
                return fallback
            raise RouteUnavailable(
                "live route request failed and no matching cache entry or fixture is available"
            ) from None
        retrieved_at = datetime.now().astimezone()
        data_date = retrieved_at.date().isoformat()
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
        return RouteOutcome(routes, "provider", False, retrieved_at, data_date)

    def _fallback(
        self, request: RouteRequest, identity: dict[str, object]
    ) -> RouteOutcome | None:
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
                routes = normalize_response(
                    cached.payload, provider_instance=request.provider_instance
                )
                return RouteOutcome(
                    routes,
                    "cache",
                    True,
                    cached.provenance.retrieved_at,
                    cached.provenance.data_date,
                )
        return self._fixture(request, stale=True)

    def _fixture(self, request: RouteRequest, *, stale: bool) -> RouteOutcome | None:
        try:
            record = load_acquisition_record(self.fixture_path)
            if (
                record is None
                or not record.replayable
                or record.endpoint != self.endpoint
                or record.schema_version != self.schema_version
                or record.provider_config_version != self.provider_config_version
                or record.request_configuration != route_request_payload(request)
                or record.retrieved_at is None
                or record.data_date is None
            ):
                return None
            payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                return None
            routes = normalize_response(payload, provider_instance=request.provider_instance)
        except (OSError, ValueError, KeyError, OsrmError):
            return None
        return RouteOutcome(routes, "fixture", stale, record.retrieved_at, record.data_date)


def route_request_payload(request: RouteRequest) -> dict[str, object]:
    """Complete route cache and fixture identity."""
    return {
        "origin": {
            "latitude": request.origin.latitude,
            "longitude": request.origin.longitude,
        },
        "destination": {
            "latitude": request.destination.latitude,
            "longitude": request.destination.longitude,
        },
        "profile": request.profile,
        "alternatives": request.alternatives,
        "overview": request.overview,
        "geometries": request.geometries,
        "steps": request.steps,
        "provider_instance": request.provider_instance,
        "request_version": request.request_version,
    }
