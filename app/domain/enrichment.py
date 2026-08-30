"""Provider-neutral contracts for optional, non-load-bearing enrichment."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from app.domain.contracts import Coordinates, EnrichmentState


class EnrichmentKind(str, Enum):
    ENVIRONMENT = "environment"
    SATELLITE_CANOPY = "satellite_canopy"
    STREET_VIEW = "street_view"


@dataclass(frozen=True)
class EnrichmentUsage:
    requested_calls: int = 1
    completed_calls: int = 0
    estimated_credits: int | None = None
    actual_credits: int | None = None
    budget_scope: str = "enrichment_daily_utc"
    budget_remaining: int | None = None


@dataclass(frozen=True)
class EnrichmentProvenance:
    source: str
    retrieved_at: str | None
    fresh: bool
    schema_version: str
    provider_config_version: str
    response_status: str
    activity_id: str | None = None
    data_date: str | None = None
    stale: bool = False
    forecast: bool = False
    raw_payload: Mapping[str, Any] | None = None
    transformations: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class EnrichmentResponse:
    kind: EnrichmentKind
    target_id: str
    state: EnrichmentState
    reason: str | None = None
    base_result: Mapping[str, Any] = field(default_factory=dict)
    usage: EnrichmentUsage = field(default_factory=EnrichmentUsage)
    provenance: EnrichmentProvenance | None = None
    limitations: tuple[str, ...] = ()
    payload: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.state is EnrichmentState.UNAVAILABLE and not self.reason:
            raise ValueError("unavailable enrichment requires a reason")
        if self.state is not EnrichmentState.UNAVAILABLE and self.reason is not None:
            raise ValueError("only unavailable enrichment may include a reason")
        if self.state is EnrichmentState.AVAILABLE and self.payload is None:
            raise ValueError("available enrichment requires a payload")


@dataclass(frozen=True)
class EnrichmentRequest:
    """Validated caller intent; provider credentials never cross this boundary."""

    result_set_token: str
    refresh: bool = False
    temperature_anchor_celsius: float | None = None

    def __post_init__(self) -> None:
        if not self.result_set_token:
            raise ValueError("result_set_token is required")
        if not isinstance(self.refresh, bool):
            raise ValueError("refresh must be a boolean")
        if self.temperature_anchor_celsius is not None:
            import math

            if not math.isfinite(self.temperature_anchor_celsius):
                raise ValueError("temperature anchor must be finite")


@dataclass(frozen=True)
class EnrichmentContext:
    target_id: str
    kind: EnrichmentKind
    coordinates: Coordinates | None = None
    route_geometry: tuple[tuple[float, float], ...] | None = None


@dataclass(frozen=True)
class EnrichmentPayload:
    """Normalized adapter output plus the activity facts known by the adapter."""

    payload: Mapping[str, Any]
    activity_id: str | None = None
    source: str = "fixture"
    response_status: str = "completed"
    retrieved_at: str | None = None
    actual_credits: int | None = None


class EnrichmentAdapter(Protocol):
    def enrich(
        self, context: EnrichmentContext, request: Mapping[str, Any]
    ) -> Mapping[str, Any] | EnrichmentPayload: ...
