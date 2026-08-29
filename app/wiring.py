"""Composition of the live FortyGuard stack behind the FastAPI service.

The server owns credentials, submission, bounded polling, error classification,
sanitized activity metadata, and provider-specific behavior (ADR 0001). This
module is the only place that assembles transport, client, adapter, cache,
ledger, and execution from application settings.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
from dataclasses import replace
from threading import Lock
from typing import Callable, Mapping, Sequence

from fastapi import FastAPI
from shapely.geometry.base import BaseGeometry

from app.api import create_app
from app.domain.contracts import ExecutionMode, TripAnalysisAdapter
from app.domain.hotel_heat_score import ComponentEvidence
from app.domain.hotels import BoundingBox, DiscoveryState, HotelDiscoveryResult
from app.domain.ledger import CreditLedger
from app.domain.provenance import CacheKey
from app.domain.security import sanitize_payload
from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.contracts import (
    AnalyticType,
    HeatmapRequest,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.errors import ProviderError
from app.integrations.fortyguard.live import (
    LiveAreaHeatmapAdapter,
    LiveEnvParamsAdapter,
    LiveFortyGuardTransport,
    LiveHeatmapAdapter,
)
from app.integrations.overpass.client import OverpassClient
from app.integrations.overpass.errors import OverpassError
from app.integrations.overpass.transport import HttpOverpassTransport
from app.services.cache import CacheService
from app.services.hotel_discovery import HotelDiscoveryService
from app.services.hotel_heat_score import HotelHeatAnalysisService
from app.services.hotel_heat_score import build_fixture_hotel_heat_analysis_service
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
    """Load the persistent call ledger, or an in-memory one (ADR 0004 §5).

    Recording is unconditional whenever live is enabled; enforcement applies
    only when ``FORTYGUARD_CALL_BUDGET`` is set, against the all-time call
    count, and is checked before each provider call.
    """
    if settings.ledger_path is None:
        return CreditLedger(settings.call_budget)
    return JsonlLedgerStore(settings.ledger_path).load(budget=settings.call_budget)


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


def build_hotel_discovery_service(
    settings: AppSettings, *, cache: CacheService | None = None
) -> HotelDiscoveryService:
    """Compose bounded OSM hotel discovery for the configured district."""
    overpass = settings.overpass
    transport = HttpOverpassTransport(
        overpass.endpoint,
        user_agent=overpass.user_agent,
        timeout_seconds=overpass.timeout_seconds,
    )
    client = OverpassClient(
        transport,
        max_attempts=overpass.max_attempts,
        retry_delay_seconds=overpass.retry_delay_seconds,
    )
    return HotelDiscoveryService(
        client,
        cache if cache is not None else CacheService(),
        provider_endpoint=overpass.endpoint,
        district_aoi=overpass.district_aoi,
        clock=lambda: datetime.now(timezone.utc),
    )


def build_live_hotel_heat_analysis_service(
    settings: AppSettings,
    *,
    client: FortyGuardClient,
    cache: CacheService | None = None,
    fixture_path: Path | None = None,
) -> HotelHeatAnalysisService:
    """Compose four shared district analyses behind the hotel ranking boundary."""
    discovery = build_hotel_discovery_service(settings, cache=cache)
    district = settings.overpass.district_aoi
    area = settings.area
    adapter = LiveAreaHeatmapAdapter(
        client,
        polling=settings.polling,
        buffer_m=area.buffer_m,
        max_vertices=area.max_vertices,
        use_bounding_box=area.use_bounding_box,
    )
    route = _bbox_route(district)
    shared_tcm: dict[str, ComponentEvidence] = {}
    shared_tcm_lock = Lock()
    fixture_service = (
        build_fixture_hotel_heat_analysis_service(fixture_path, district_aoi=district)
        if fixture_path is not None
        else None
    )

    def load(component: str) -> ComponentEvidence | None:
        analytic = (
            AnalyticType.TCM
            if component in {"night", "day"}
            else (AnalyticType.EXCEEDANCE if component == "hot_hours" else AnalyticType.PERSISTENCE)
        )
        if analytic is AnalyticType.TCM:
            with shared_tcm_lock:
                cached_tcm = shared_tcm.get("evidence")
            if cached_tcm is not None:
                return replace(cached_tcm, component=component)
        try:
            payload = adapter.load(
                route,
                analytic_type=analytic,
                start_date=date.today(),
                forecast=True,
                threshold_celsius=35.0 if analytic is not AnalyticType.TCM else None,
                direction="above" if analytic is not AnalyticType.TCM else None,
                granularity=area.granularity,
            )
        except (ConnectionError, OSError, ProviderError, TimeoutError, ValueError):
            if cache is not None:
                midpoint = route[len(route) // 2]
                request_date = date.today()
                request = HeatmapRequest(
                    analytic,
                    midpoint[0],
                    midpoint[1],
                    request_date,
                    True,
                    35.0 if analytic is not AnalyticType.TCM else None,
                    "above" if analytic is not AnalyticType.TCM else None,
                    area.granularity,
                )
                cache_payload = {
                    "analytic_type": analytic.value,
                    "latitude": midpoint[0],
                    "longitude": midpoint[1],
                    "start_date": request_date.isoformat(),
                    "forecast": True,
                    "threshold_celsius": request.threshold_celsius,
                    "direction": request.direction,
                    "granularity": area.granularity,
                }
                cached = cache.get(
                    CacheKey.create("/v1/heatmap", "v1", cache_payload, "fortyguard-config-v1")
                )
                if cached is not None:
                    replayed = normalize_heatmap_response(
                        cached.payload,
                        request=request,
                        retrieved_at=cached.provenance.retrieved_at,
                        activity_id=cached.provenance.activity_id,
                        source="cache",
                        data_date=cached.provenance.data_date,
                        stale=True,
                    )
                    evidence = ComponentEvidence(
                        component,
                        tuple(replayed._spatial_tiles()),
                        "C" if analytic is AnalyticType.TCM else "hours",
                        request.threshold_celsius,
                        "cache:fortyguard",
                        float(area.granularity),
                        caveats=("replayed cached evidence; stale",),
                        provenance_details={
                            "source": "cache",
                            "retrieved_at": cached.provenance.retrieved_at.isoformat(),
                            "data_date": cached.provenance.data_date,
                            "stale": True,
                            "forecast": cached.provenance.forecast,
                            "activity_id": cached.provenance.activity_id,
                            "transformations": [],
                        },
                        correlation_key=(
                            "shared-date-tcm" if component in {"night", "day"} else None
                        ),
                    )
                    return evidence
            if fixture_service is None:
                return None
            fixture_evidence = fixture_service.load_component(component)
            if fixture_evidence is None:
                return None
            details = dict(fixture_evidence.provenance_details or {})
            details["stale"] = True
            replayed_evidence = replace(
                fixture_evidence,
                provenance="fixture:canonical-district-hotel-analysis",
                caveats=fixture_evidence.caveats + ("replayed matching fixture evidence; stale",),
                provenance_details=details,
            )
            return replayed_evidence
        request_date = date.today()
        midpoint = route[len(route) // 2]
        result = normalize_heatmap_response(
            payload.payload,
            request=HeatmapRequest(
                analytic,
                midpoint[0],
                midpoint[1],
                request_date,
                True,
                35.0 if analytic is not AnalyticType.TCM else None,
                "above" if analytic is not AnalyticType.TCM else None,
                area.granularity,
            ),
            retrieved_at=datetime.now(timezone.utc),
            activity_id=payload.activity_id,
            source="provider",
            data_date=request_date.isoformat(),
            transformations=payload.transformations,
        )
        if cache is not None:
            cache.put(
                "/v1/heatmap",
                "v1",
                {
                    "analytic_type": analytic.value,
                    "latitude": midpoint[0],
                    "longitude": midpoint[1],
                    "start_date": request_date.isoformat(),
                    "forecast": True,
                    "threshold_celsius": 35.0 if analytic is not AnalyticType.TCM else None,
                    "direction": "above" if analytic is not AnalyticType.TCM else None,
                    "granularity": area.granularity,
                },
                payload.payload,
                retrieved_at=result.provenance.retrieved_at,
                data_date=result.provenance.data_date,
                activity_id=result.provenance.activity_id,
                forecast=True,
                provider_config_version="fortyguard-config-v1",
            )
        units = "C" if analytic is AnalyticType.TCM else "hours"
        caveats = (
            (
                "date-level TCM value; night window 00:00-05:00 is not a verified interval maximum; "
                "night and day use the same date-level basis",
            )
            if component == "night"
            else (
                "date-level TCM value; day window 10:00-17:00 is not a verified interval maximum; "
                "night and day use the same date-level basis",
            )
            if component == "day"
            else ()
        )
        coverage = result.polygon_lookup(_bbox_geometry(district)).coverage
        evidence = ComponentEvidence(
            component,
            tuple(result._spatial_tiles()),
            units,
            35.0 if analytic is not AnalyticType.TCM else None,
            "provider:fortyguard",
            float(area.granularity),
            coverage=coverage,
            caveats=caveats,
            provenance_details={
                "source": result.provenance.source,
                "retrieved_at": result.provenance.retrieved_at.isoformat(),
                "data_date": result.provenance.data_date,
                "stale": result.provenance.stale,
                "forecast": result.provenance.forecast,
                "activity_id": result.provenance.activity_id,
                "transformations": [
                    {"name": item.name, "version": item.version}
                    for item in result.provenance.transformations
                ],
            },
            correlation_key="shared-date-tcm" if analytic is AnalyticType.TCM else None,
        )
        if analytic is AnalyticType.TCM:
            with shared_tcm_lock:
                shared_tcm["evidence"] = evidence
        return evidence

    return HotelHeatAnalysisService(
        lambda: _live_discovery_with_fixture(
            discovery.discover, fixture_service.discover if fixture_service is not None else None
        ),
        load,
        aoi=_bbox_geometry(district),
        supported_modes=frozenset({ExecutionMode.LIVE}),
        district_name="Downtown San Antonio",
    )


def _live_discovery_with_fixture(
    live: Callable[[], HotelDiscoveryResult], fallback: Callable[[], HotelDiscoveryResult] | None
) -> HotelDiscoveryResult:
    try:
        result = live()
        if result.state is not DiscoveryState.UNAVAILABLE:
            return result
    except (ConnectionError, OSError, OverpassError, ValueError):
        if fallback is None:
            raise
    if fallback is None:
        return result
    replayed = fallback()
    return replace(replayed, source="fixture", stale=True)


def _bbox_route(bbox: BoundingBox) -> tuple[tuple[float, float], ...]:
    return (
        (bbox.south, bbox.west),
        (bbox.south, bbox.east),
        (bbox.north, bbox.east),
        (bbox.north, bbox.west),
        (bbox.south, bbox.west),
    )


def _bbox_geometry(bbox: BoundingBox) -> BaseGeometry:
    from shapely.geometry import box

    return box(bbox.west, bbox.south, bbox.east, bbox.north)


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
    hotel_heat_analysis_service: HotelHeatAnalysisService | None = None,
) -> FastAPI:
    """Create the production app; misconfigured live mode fails fast at startup."""
    from app.settings import load_settings

    resolved = settings if settings is not None else load_settings()
    root = Path(__file__).resolve().parents[1]
    heatmap_fixture = (
        fixture_path if fixture_path is not None else root / "fixtures" / "heatmap-historical.json"
    )
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
    if hotel_heat_analysis_service is None:
        if resolved.allow_live:
            hotel_heat_analysis_service = build_live_hotel_heat_analysis_service(
                resolved,
                client=client,
                cache=cache,
                fixture_path=heatmap_fixture.parent / "hotel-heat-analysis.json",
            )
        else:
            hotel_heat_analysis_service = build_fixture_hotel_heat_analysis_service(
                heatmap_fixture.parent / "hotel-heat-analysis.json",
                district_aoi=resolved.overpass.district_aoi,
            )
    return create_app(
        heatmap_fixture,
        execution=execution,
        env_params_execution=env_params_execution,
        allow_live=resolved.allow_live,
        frontend_dist=dist,
        trip_adapter=trip_adapter,
        hotel_heat_analysis_service=hotel_heat_analysis_service,
        district_aoi=resolved.overpass.district_aoi,
    )
