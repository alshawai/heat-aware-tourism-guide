"""Composition of the live FortyGuard stack behind the FastAPI service.

The server owns credentials, submission, bounded polling, error classification,
sanitized activity metadata, and provider-specific behavior (ADR 0001). This
module is the only place that assembles transport, client, adapter, cache,
ledger, and execution from application settings.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Mapping, Sequence

from fastapi import FastAPI

from app.api import create_app
from app.domain.contracts import TripAnalysisAdapter
from app.domain.ledger import CreditLedger
from app.domain.security import sanitize_payload
from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.live import (
    LiveEnvParamsAdapter,
    LiveFortyGuardTransport,
    LiveHeatmapAdapter,
)
from app.services.cache import CacheService
from app.services.execution import EnvParamsExecution, HeatmapExecution
from app.services.ledger_store import JsonlLedgerStore
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


def build_ledger(settings: AppSettings) -> CreditLedger:
    """Load the persistent cost ledger, or an in-memory one (ADR 0004).

    Recording is unconditional whenever live is enabled; enforcement applies
    only when ``FORTYGUARD_CREDIT_BUDGET`` is set, against the all-time total.
    """
    if settings.ledger_path is None:
        return CreditLedger(settings.credit_budget)
    return JsonlLedgerStore(settings.ledger_path).load(budget=settings.credit_budget)


def build_live_client(
    settings: AppSettings, *, ledger: CreditLedger | None = None
) -> FortyGuardClient:
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
        ledger=ledger,
    )


def build_live_heatmap_execution(
    settings: AppSettings,
    *,
    fixture_path: Path,
    client: FortyGuardClient | None = None,
    cache: CacheService | None = None,
    additional_fixtures: Sequence[Path] = (),
) -> HeatmapExecution:
    """Compose the live heatmap execution: transport, client, adapter, cache."""
    adapter = LiveHeatmapAdapter(client or build_live_client(settings), polling=settings.polling)
    return HeatmapExecution(
        fixture_path=fixture_path,
        live_loader=adapter.load,
        cache=cache if cache is not None else CacheService(),
        additional_fixtures=additional_fixtures,
    )


def build_live_env_params_execution(
    settings: AppSettings,
    *,
    fixture_path: Path,
    client: FortyGuardClient | None = None,
    cache: CacheService | None = None,
    additional_fixtures: Sequence[Path] = (),
) -> EnvParamsExecution:
    """Compose the live environmental-parameters execution."""
    adapter = LiveEnvParamsAdapter(client or build_live_client(settings), polling=settings.polling)
    return EnvParamsExecution(
        fixture_path=fixture_path,
        live_loader=adapter.load,
        cache=cache,
        additional_fixtures=additional_fixtures,
    )


def _fixture_candidates(primary: Path, pattern: str) -> list[Path]:
    """Committed fixtures of one kind: the fixture directory plus acquisitions.

    Acquisition sidecars are excluded — they are identity metadata, not payloads.
    """
    def payloads(paths: list[Path]) -> list[Path]:
        return [path for path in paths if not path.name.endswith(".acquisition.json")]

    candidates = payloads(sorted(primary.parent.glob(pattern)))
    acquired = primary.parent / "acquired"
    if acquired.is_dir():
        candidates.extend(payloads(sorted(acquired.glob(pattern))))
    return candidates


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
        ledger = build_ledger(resolved)
        client = build_live_client(resolved, ledger=ledger)
        cache = CacheService()
        execution = build_live_heatmap_execution(
            resolved,
            fixture_path=heatmap_fixture,
            client=client,
            cache=cache,
            additional_fixtures=_fixture_candidates(heatmap_fixture, "heatmap-*.json"),
        )
        env_params_execution = build_live_env_params_execution(
            resolved,
            fixture_path=env_fixture,
            client=client,
            cache=cache,
            additional_fixtures=_fixture_candidates(env_fixture, "env-params*.json"),
        )
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
