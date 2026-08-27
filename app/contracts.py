"""Shared product-shaped request and response contracts for trip analysis.

Both fixture and live adapters target these contracts. The frontend never
receives provider-specific orchestration details; it consumes only the shapes
defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TripMode(str, Enum):
    CURATED = "curated"
    EXPLORATORY = "exploratory"


class ExecutionMode(str, Enum):
    FIXTURE = "fixture"
    LIVE = "live"


class ResultState(str, Enum):
    SUCCESS = "success"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class HeatStatus(str, Enum):
    ELEVATED = "elevated"
    NOT_ELEVATED = "not_elevated"


class Confidence(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"


class MetricLabel(str, Enum):
    PROVIDER_TCM = "provider_tcm"
    NOAA_HEAT_INDEX = "noaa_heat_index"


# ---------------------------------------------------------------------------
# Shared value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.latitude)
            or not math.isfinite(self.longitude)
            or not -90 <= self.latitude <= 90
            or not -180 <= self.longitude <= 180
        ):
            raise ValueError("coordinates must be finite and within valid ranges")


@dataclass(frozen=True)
class Provenance:
    source: str
    data_date: str
    confidence: Confidence
    coverage: float | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("provenance source is required")
        if not self.data_date:
            raise ValueError("provenance data_date is required")
        if self.coverage is not None and not 0 <= self.coverage <= 1:
            raise ValueError("coverage must be between 0 and 1")


@dataclass(frozen=True)
class Metric:
    value: float
    unit: str
    label: MetricLabel
    is_actual_heat_index: bool

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError("metric value must be finite")
        if not self.unit:
            raise ValueError("metric unit is required")


@dataclass(frozen=True)
class HourlyEntry:
    hour: int
    metric: Metric

    def __post_init__(self) -> None:
        if not 0 <= self.hour <= 23:
            raise ValueError("hour must be between 0 and 23")


# ---------------------------------------------------------------------------
# Request contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TripAnalysisRequest:
    """Complete input for a product-level trip analysis."""

    mode: TripMode
    origin: Coordinates
    destination: Coordinates
    landmark_name: str
    district_name: str
    date: str
    hour: int
    cautious: bool

    # Heat context
    heat_metric: str
    heat_value: float
    heat_threshold: float
    corridor_heat_values: tuple[float, ...]
    building_coverage: float

    # Hotel candidates from discovery/ranking
    hotels: tuple[HotelCandidateData, ...]

    # Route candidates from OSRM
    routes: tuple[RouteCandidateData, ...]

    # Shade estimates keyed by route identity
    shade: dict[str, float]

    def __post_init__(self) -> None:
        if not self.landmark_name:
            raise ValueError("landmark_name is required")
        if not self.district_name:
            raise ValueError("district_name is required")
        if not self.date:
            raise ValueError("date is required")
        if not 0 <= self.hour <= 23:
            raise ValueError("hour must be between 0 and 23")
        if not self.heat_metric:
            raise ValueError("heat_metric is required")
        if not math.isfinite(self.heat_value):
            raise ValueError("heat_value must be finite")
        if not math.isfinite(self.heat_threshold):
            raise ValueError("heat_threshold must be finite")
        if not 0 <= self.building_coverage <= 1:
            raise ValueError("building_coverage must be between 0 and 1")
        if not self.hotels:
            raise ValueError("at least one hotel candidate is required")
        if not self.routes:
            raise ValueError("at least one route candidate is required")


@dataclass(frozen=True)
class HotelCandidateData:
    identity: str
    components: dict[str, float]

    def __post_init__(self) -> None:
        required = {"night", "hot_hours", "persistence", "day"}
        if set(self.components) != required:
            raise ValueError(f"hotel components must be exactly {required}")
        for name, value in self.components.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"hotel component {name} must be a finite number")


@dataclass(frozen=True)
class RouteCandidateData:
    identity: str
    distance_m: float
    duration_s: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.distance_m) or self.distance_m <= 0:
            raise ValueError("distance_m must be a positive finite number")
        if not math.isfinite(self.duration_s) or self.duration_s <= 0:
            raise ValueError("duration_s must be a positive finite number")


# ---------------------------------------------------------------------------
# Response sub-shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BestTimeResult:
    """Best-time recommendation with hourly evidence."""

    hourly: tuple[HourlyEntry, ...]
    recommendation_hour: int
    recommendation_reason: str
    metric_label: MetricLabel
    provenance: Provenance

    def __post_init__(self) -> None:
        if not 0 <= self.recommendation_hour <= 23:
            raise ValueError("recommendation_hour must be between 0 and 23")
        if not self.recommendation_reason:
            raise ValueError("recommendation_reason is required")


@dataclass(frozen=True)
class RankedHotel:
    identity: str
    components: dict[str, float]
    score: float
    percentile: float
    tie_group: int

    def __post_init__(self) -> None:
        for name, value in self.components.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"hotel component {name} must be a finite number")
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")


@dataclass(frozen=True)
class HotelRankingResult:
    """Ranked hotel list with weights and component breakdown."""

    ranked: tuple[RankedHotel, ...]
    weights: dict[str, float]
    usable_count: int
    discovered_count: int
    provenance: Provenance

    def __post_init__(self) -> None:
        if abs(sum(self.weights.values()) - 1) > 0.001:
            raise ValueError("weights must sum to 1")
        if self.usable_count < 0 or self.discovered_count < 0:
            raise ValueError("counts must be non-negative")
        if self.usable_count > self.discovered_count:
            raise ValueError("usable_count cannot exceed discovered_count")


@dataclass(frozen=True)
class RouteOption:
    identity: str
    distance_m: float
    duration_s: float
    heat_value: float
    modeled_shade_percent: float | None
    shade_confidence: Confidence | None

    def __post_init__(self) -> None:
        if not math.isfinite(self.distance_m) or self.distance_m <= 0:
            raise ValueError("distance_m must be positive and finite")
        if not math.isfinite(self.duration_s) or self.duration_s <= 0:
            raise ValueError("duration_s must be positive and finite")
        if not math.isfinite(self.heat_value):
            raise ValueError("heat_value must be finite")


@dataclass(frozen=True)
class RouteComparisonResult:
    """Route comparison with recommendation and heat context."""

    alternatives: tuple[RouteOption, ...]
    recommended_id: str
    reason: str
    heat_status: HeatStatus
    corridor_heat_value: float
    heat_metric: str
    coverage: float
    confidence: Confidence
    comparison_scope: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.alternatives:
            raise ValueError("at least one route alternative is required")
        if not self.recommended_id:
            raise ValueError("recommended_id is required")
        if not self.reason:
            raise ValueError("reason is required")
        if not self.comparison_scope:
            raise ValueError("comparison_scope is required")
        if not 0 <= self.coverage <= 1:
            raise ValueError("coverage must be between 0 and 1")
        identities = {route.identity for route in self.alternatives}
        if self.recommended_id not in identities:
            raise ValueError("recommended_id must reference a listed alternative")


@dataclass(frozen=True)
class UnavailableResult:
    """Explicit representation when analysis data is not available."""

    reason: str
    recoverable: bool

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("unavailability reason is required")


# ---------------------------------------------------------------------------
# Top-level response
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TripAnalysisResponse:
    """Complete product-shaped response shared by fixture and live execution."""

    request_identity: str
    mode: TripMode
    execution_mode: ExecutionMode
    state: ResultState

    best_time: BestTimeResult | None = None
    hotels: HotelRankingResult | None = None
    routes: RouteComparisonResult | None = None
    unavailable: UnavailableResult | None = None

    def __post_init__(self) -> None:
        if self.state is ResultState.SUCCESS:
            if self.best_time is None:
                raise ValueError("success state requires best_time")
            if self.hotels is None:
                raise ValueError("success state requires hotels")
            if self.routes is None:
                raise ValueError("success state requires routes")
            if self.unavailable is not None:
                raise ValueError("success state must not include unavailable")
        elif self.state is ResultState.UNAVAILABLE:
            if self.unavailable is None:
                raise ValueError("unavailable state requires unavailable detail")
            if self.best_time is not None or self.hotels is not None or self.routes is not None:
                raise ValueError("unavailable state must not include result data")
        elif self.state is ResultState.DEGRADED:
            if self.best_time is None and self.hotels is None and self.routes is None:
                raise ValueError("degraded state requires at least one partial result")
        elif self.state is ResultState.ERROR:
            if self.unavailable is None:
                raise ValueError("error state requires unavailable detail")
