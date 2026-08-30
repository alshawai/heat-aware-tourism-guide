"""Explicit, non-load-bearing enrichment orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Any, Callable, Mapping

from app.domain.contracts import Coordinates, EnrichmentState
from app.domain.enrichment import (
    EnrichmentAdapter,
    EnrichmentContext,
    EnrichmentKind,
    EnrichmentPayload,
    EnrichmentProvenance,
    EnrichmentResponse,
    EnrichmentUsage,
)
from app.domain.ledger import BudgetExceededError, CreditLedger
from app.domain.ledger import UsageRecord
from app.domain.provenance import CacheKey
from app.services.cache import CacheService


LIMITATIONS = {
    EnrichmentKind.ENVIRONMENT: (
        "caller-supplied temperature anchor; not a real 24-hour forecast",
    ),
    EnrichmentKind.SATELLITE_CANOPY: (
        "contextual canopy enrichment; not a route shade measurement",
    ),
    EnrichmentKind.STREET_VIEW: (
        "street-view segmentation is not exact-time route shade evidence",
    ),
}


class EnrichmentService:
    def __init__(
        self,
        *,
        ledger: CreditLedger,
        adapters: Mapping[EnrichmentKind, EnrichmentAdapter] | None = None,
        estimates: Mapping[str, int] | None = None,
        clock: Callable[[], datetime] | None = None,
        live: bool = False,
        cache: CacheService | None = None,
        cache_ttls: Mapping[EnrichmentKind, timedelta] | None = None,
        adapter_manages_budget: bool = False,
    ) -> None:
        self.ledger = ledger
        self.adapters = dict(adapters or {})
        self.estimates = dict(estimates or {})
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.live = live
        self.cache = cache
        self.cache_ttls = dict(
            cache_ttls
            or {
                EnrichmentKind.ENVIRONMENT: timedelta(hours=24),
                EnrichmentKind.SATELLITE_CANOPY: timedelta(days=7),
                EnrichmentKind.STREET_VIEW: timedelta(hours=24),
            }
        )
        self.adapter_manages_budget = adapter_manages_budget

    def run(
        self,
        *,
        kind: EnrichmentKind,
        target_id: str,
        coordinates: Coordinates | None = None,
        route_geometry: tuple[tuple[float, float], ...] | None = None,
        request: Mapping[str, Any] | None = None,
        base_result: Mapping[str, Any] | None = None,
    ) -> EnrichmentResponse:
        estimate = self.estimates.get(kind.value)
        request_payload = dict(request or {})
        cache_payload = {
            "target_id": target_id,
            **{key: value for key, value in request_payload.items() if key != "refresh"},
        }
        cache_key = (
            CacheKey.create(
                f"/enrichment/{kind.value}",
                "enrichment-v1",
                cache_payload,
                "fortyguard-enrichment-v1",
            )
            if self.cache is not None
            else None
        )
        if self.cache is not None and cache_key is not None and not request_payload.get("refresh"):
            cached = self.cache.get_if_fresh(cache_key, now=self.clock(), ttl=self.cache_ttls[kind])
            if cached is not None:
                return EnrichmentResponse(
                    kind=kind,
                    target_id=target_id,
                    state=EnrichmentState.AVAILABLE,
                    base_result=base_result or {},
                    usage=EnrichmentUsage(estimated_credits=estimate),
                    provenance=EnrichmentProvenance(
                        source="cache",
                        retrieved_at=cached.provenance.retrieved_at.isoformat(),
                        fresh=True,
                        schema_version="enrichment-v1",
                        provider_config_version="fortyguard-enrichment-v1",
                        response_status="cached",
                    ),
                    limitations=LIMITATIONS[kind],
                    payload=cached.payload,
                )
            if self.cache.has_stale(cache_key, now=self.clock(), ttl=self.cache_ttls[kind]):
                return EnrichmentResponse(
                    kind=kind,
                    target_id=target_id,
                    state=EnrichmentState.UNAVAILABLE,
                    reason="stale_cache_requires_refresh",
                    base_result=base_result or {},
                    usage=EnrichmentUsage(estimated_credits=estimate),
                    limitations=LIMITATIONS[kind],
                )
        common = dict(
            kind=kind,
            target_id=target_id,
            base_result=base_result or {},
            limitations=LIMITATIONS[kind],
        )
        adapter = self.adapters.get(kind)
        if adapter is None or estimate is None:
            return EnrichmentResponse(
                **common, state=EnrichmentState.UNAVAILABLE, reason="configuration_missing"
            )
        reservation = None
        if self.live and not self.adapter_manages_budget:
            try:
                reservation = self.ledger.authorize_enrichment(now=self.clock())
            except BudgetExceededError:
                return EnrichmentResponse(
                    **common, state=EnrichmentState.UNAVAILABLE, reason="budget_exhausted"
                )
        try:
            adapter_request = dict(request or {})
            if kind is EnrichmentKind.ENVIRONMENT:
                adapter_request["temperature_anchor_celsius"] = adapter_request.get(
                    "temperature_anchor_celsius"
                )
            payload = adapter.enrich(
                EnrichmentContext(target_id, kind, coordinates, route_geometry), adapter_request
            )
            adapter_output = payload
            if isinstance(adapter_output, EnrichmentPayload):
                payload = adapter_output.payload
            if not isinstance(payload, Mapping) or not payload:
                raise ValueError("provider payload is unusable")
        except Exception as error:
            # A provider adapter owns activity recording when it submits through
            # FortyGuard. This reservation is only safe to release before submit.
            if reservation is not None:
                self.ledger.release_call(reservation)
            reason = (
                "fixture_data_unavailable"
                if str(error) == "fixture data unavailable"
                else "provider_payload_unusable"
                if isinstance(error, ValueError)
                else "provider_failure"
            )
            return EnrichmentResponse(**common, state=EnrichmentState.UNAVAILABLE, reason=reason)
        activity_id = (
            adapter_output.activity_id if isinstance(adapter_output, EnrichmentPayload) else None
        )
        if reservation is not None and activity_id is None:
            self.ledger.record(
                UsageRecord(
                    activity_id=f"enrichment-{uuid4().hex}",
                    endpoint=f"/enrichment/{kind.value}",
                    credits_used=None,
                    completed_at=self.clock(),
                    status="completed",
                    scope="enrichment",
                ),
                reservation=reservation,
            )
        elif reservation is not None:
            self.ledger.release_call(reservation)
        if self.cache is not None and cache_key is not None:
            self.cache.put(
                f"/enrichment/{kind.value}",
                "enrichment-v1",
                cache_payload,
                payload,
                retrieved_at=self.clock(),
                data_date=self.clock().date().isoformat(),
                provider_config_version="fortyguard-enrichment-v1",
            )
        return EnrichmentResponse(
            **common,
            state=EnrichmentState.AVAILABLE,
            provenance=EnrichmentProvenance(
                source=(
                    adapter_output.source
                    if isinstance(adapter_output, EnrichmentPayload)
                    else ("provider" if self.live else "fixture")
                ),
                retrieved_at=self.clock().isoformat(),
                fresh=True,
                schema_version="enrichment-v1",
                provider_config_version="fortyguard-enrichment-v1",
                response_status=(
                    adapter_output.response_status
                    if isinstance(adapter_output, EnrichmentPayload)
                    else "completed"
                ),
                activity_id=activity_id,
            ),
            usage=EnrichmentUsage(
                estimated_credits=estimate,
                completed_calls=1 if self.live else 0,
                budget_remaining=(
                    self.ledger.remaining_enrichment(now=self.clock()) if self.live else 0
                ),
            ),
            payload=(
                {**payload, "temperature_anchor_celsius": request.get("temperature_anchor_celsius")}
                if kind is EnrichmentKind.ENVIRONMENT and request is not None
                else payload
            ),
        )


class FixtureEnrichmentAdapter:
    """Replay one sanitized normalized fixture without touching provider clients."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = dict(payload)

    def enrich(self, context: EnrichmentContext, request: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = dict(self._payload)
        if payload.get("fixture_data_unavailable") is True:
            raise ValueError("fixture data unavailable")
        if context.kind is EnrichmentKind.ENVIRONMENT:
            anchor = request.get("temperature_anchor_celsius")
            if anchor is None:
                raise ValueError("temperature anchor is required")
            payload["temperature_anchor_celsius"] = anchor
            payload["warning"] = LIMITATIONS[EnrichmentKind.ENVIRONMENT][0]
        return payload
