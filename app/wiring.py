"""Composition of the live FortyGuard stack behind the FastAPI service.

The server owns credentials, submission, bounded polling, error classification,
sanitized activity metadata, and provider-specific behavior (ADR 0001). This
module is the only place that assembles transport, client, adapter, cache, and
execution from application settings.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Mapping

from fastapi import FastAPI

from app.api import create_app
from app.domain.contracts import TripAnalysisAdapter
from app.domain.security import sanitize_payload
from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.live import (
    LiveEnvParamsAdapter,
    LiveFortyGuardTransport,
    LiveHeatmapAdapter,
)
from app.services.cache import CacheService
from app.services.execution import EnvParamsExecution, HeatmapExecution
from app.services.trip_adapters import (
    FixtureTripAnalysisAdapter,
    LiveTripAnalysisAdapter,
    ModeDispatchTripAnalysisAdapter,
)
from app.settings import AppSettings, SettingsError

_EVENT_LOGGER = logging.getLogger("app.fortyguard")


def json_event_sink(event: Mapping[str, object]) -> None:
    """Emit one provider event as a JSON log line; sanitized, never credentials."""
    sanitized = sanitize_payload(dict(event))
    _EVENT_LOGGER.info(json.dumps(sanitized, default=str))


def _live_client(settings: AppSettings) -> FortyGuardClient:
    if not settings.fortyguard_api_key:
        raise SettingsError("live execution requires FORTYGUARD_API_KEY to be set")
    transport = LiveFortyGuardTransport(
        settings.fortyguard_base_url,
        timeout_seconds=settings.polling.timeout_seconds,
    )
    return FortyGuardClient(
        transport,
        settings.fortyguard_api_key,
        clock=lambda: datetime.now(timezone.utc),
        event_sink=json_event_sink,
    )


def build_live_heatmap_execution(settings: AppSettings, *, fixture_path: Path) -> HeatmapExecution:
    """Compose the live heatmap execution: transport, client, adapter, cache."""
    adapter = LiveHeatmapAdapter(_live_client(settings), polling=settings.polling)
    return HeatmapExecution(
        fixture_path=fixture_path,
        live_loader=adapter.load,
        cache=CacheService(),
    )


def build_live_env_params_execution(
    settings: AppSettings, *, fixture_path: Path
) -> EnvParamsExecution:
    """Compose the live environmental-parameters execution."""
    adapter = LiveEnvParamsAdapter(_live_client(settings), polling=settings.polling)
    return EnvParamsExecution(fixture_path=fixture_path, live_loader=adapter.load)


def create_production_app(
    settings: AppSettings | None = None,
    *,
    fixture_path: Path | None = None,
    env_params_fixture_path: Path | None = None,
    frontend_dist: Path | None = None,
    trip_adapter: TripAnalysisAdapter | None = None,
) -> FastAPI:
    """Create the production app; misconfigured live mode fails fast at startup."""
    from app.settings import load_settings

    resolved = settings if settings is not None else load_settings()
    root = Path(__file__).resolve().parents[1]
    heatmap_fixture = fixture_path if fixture_path is not None else root / "fixtures" / "heatmap-historical.json"
    env_fixture = (
        env_params_fixture_path
        if env_params_fixture_path is not None
        else heatmap_fixture.parent / "env-params.json"
    )
    dist = frontend_dist if frontend_dist is not None else root / "frontend" / "dist"
    execution: HeatmapExecution | None = None
    env_params_execution: EnvParamsExecution | None = None
    if resolved.allow_live:
        execution = build_live_heatmap_execution(resolved, fixture_path=heatmap_fixture)
        env_params_execution = build_live_env_params_execution(resolved, fixture_path=env_fixture)
    if trip_adapter is None:
        trip_adapter = ModeDispatchTripAnalysisAdapter(
            FixtureTripAnalysisAdapter(heatmap_fixture.parent / "trip-analysis.json"),
            LiveTripAnalysisAdapter(
                lambda request: {"unavailable": "live trip adapter is not configured"}
            ),
        )
    return create_app(
        heatmap_fixture,
        execution=execution,
        env_params_execution=env_params_execution,
        allow_live=resolved.allow_live,
        frontend_dist=dist,
        trip_adapter=trip_adapter,
    )
