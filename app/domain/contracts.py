"""Shared product-shaped request and response contracts for trip analysis.

Both fixture and live adapters target these contracts. The frontend never
receives provider-specific orchestration details; it consumes only the shapes
defined here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from datetime import date as calendar_date, datetime
from typing import Protocol


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


class HeatMetricName(str, Enum):
    TCM = "tcm"
    HEAT_INDEX_CELSIUS = "heat_index_celsius"


class EnrichmentState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_REQUESTED = "not_requested"


@dataclass(frozen=True)
class OptionalEnrichment:
    state: EnrichmentState
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, EnrichmentState):
            raise ValueError("enrichment state must be an EnrichmentState value")
        if self.state is EnrichmentState.UNAVAILABLE and not self.reason:
            raise ValueError("unavailable enrichment requires a reason")
        if self.state is not EnrichmentState.UNAVAILABLE and self.reason is not None:
            raise ValueError("only unavailable enrichment may include a reason")


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
    retrieved_at: str
    transformation_version: str
    provider: str
    response_status: str
    request_configuration: dict[str, object]
    fresh: bool
    coverage: float | None = None
    note: str | None = None
    activity_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.confidence, Confidence):
            raise ValueError("provenance confidence must be a Confidence value")
        if not self.source:
            raise ValueError("provenance source is required")
        if not self.data_date:
            raise ValueError("provenance data_date is required")
        try:
            calendar_date.fromisoformat(self.data_date)
            datetime.fromisoformat(self.retrieved_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("provenance dates must be ISO formatted") from error
        if self.coverage is not None and not 0 <= self.coverage <= 1:
            raise ValueError("coverage must be between 0 and 1")
        if not self.transformation_version:
            raise ValueError("provenance transformation_version is required")
        if not isinstance(self.fresh, bool):
            raise ValueError("provenance fresh must be a boolean")
        if not self.retrieved_at or not self.provider or not self.response_status:
            raise ValueError("provenance retrieval, provider, and response status are required")


@dataclass(frozen=True)
class Metric:
    value: float
    unit: str
    label: MetricLabel
    is_actual_heat_index: bool

    def __post_init__(self) -> None:
        if not isinstance(self.label, MetricLabel):
            raise ValueError("metric label must be a MetricLabel value")
        if not isinstance(self.is_actual_heat_index, bool):
            raise ValueError("is_actual_heat_index must be a boolean")
        if not math.isfinite(self.value):
            raise ValueError("metric value must be finite")
        if not self.unit:
            raise ValueError("metric unit is required")
        if (
            self.label in (MetricLabel.PROVIDER_TCM, MetricLabel.NOAA_HEAT_INDEX)
            and self.unit != "C"
        ):
            raise ValueError("temperature metrics must use C")
        if self.label is MetricLabel.NOAA_HEAT_INDEX and not self.is_actual_heat_index:
            raise ValueError("NOAA Heat Index label requires an actual heat index")
        if self.label is MetricLabel.PROVIDER_TCM and self.is_actual_heat_index:
            raise ValueError("provider TCM must not be marked as actual heat index")


@dataclass(frozen=True)
class HourlyEntry:
    hour: int
    metric: Metric

    def __post_init__(self) -> None:
        if (
            isinstance(self.hour, bool)
            or not isinstance(self.hour, int)
            or not 0 <= self.hour <= 23
        ):
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

    def __post_init__(self) -> None:
        if not isinstance(self.mode, TripMode):
            raise ValueError("unknown trip mode")
        if not self.landmark_name:
            raise ValueError("landmark_name is required")
        if not self.district_name:
            raise ValueError("district_name is required")
        if not self.date:
            raise ValueError("date is required")
        try:
            calendar_date.fromisoformat(self.date)
        except ValueError as error:
            raise ValueError("date must be an ISO date") from error
        if (
            isinstance(self.hour, bool)
            or not isinstance(self.hour, int)
            or not 0 <= self.hour <= 23
        ):
            raise ValueError("hour must be between 0 and 23")
        if not isinstance(self.cautious, bool):
            raise ValueError("cautious must be a boolean")
        if self.mode not in (TripMode.CURATED, TripMode.EXPLORATORY):
            raise ValueError("unknown trip mode")


@dataclass(frozen=True)
class TripAnalysisInputs:
    """Adapter-owned normalized inputs; not part of the frontend request."""

    heat_metric: HeatMetricName
    heat_value: float
    heat_threshold: float
    corridor_heat_values: tuple[float, ...]
    building_coverage: float
    hotels: tuple[HotelCandidateData, ...]
    routes: tuple[RouteCandidateData, ...]
    shade: dict[str, float]

    def __post_init__(self) -> None:
        if not self.hotels or not self.routes:
            raise ValueError("trip analysis requires hotel and route inputs")
        if not isinstance(self.heat_metric, HeatMetricName):
            raise ValueError("heat_metric must be tcm or heat_index_celsius")
        if not math.isfinite(self.heat_value):
            raise ValueError("heat_value must be finite")
        if not math.isfinite(self.heat_threshold):
            raise ValueError("heat_threshold must be finite")
        if any(not math.isfinite(value) for value in self.corridor_heat_values):
            raise ValueError("corridor heat values must be finite")
        if not 0 <= self.building_coverage <= 1:
            raise ValueError("building_coverage must be between 0 and 1")


@dataclass(frozen=True)
class HotelCandidateData:
    identity: str
    components: dict[str, float]

    def __post_init__(self) -> None:
        if not self.identity:
            raise ValueError("hotel identity is required")
        required = {"night", "hot_hours", "persistence", "day"}
        if set(self.components) != required:
            raise ValueError(f"hotel components must be exactly {required}")
        for name, value in self.components.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"hotel component {name} must be a finite number")


@dataclass(frozen=True)
class RouteCandidateData:
    identity: str
    distance_m: float
    duration_s: float

    def __post_init__(self) -> None:
        if not self.identity:
            raise ValueError("route identity is required")
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
    hourly_coverage: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.metric_label, MetricLabel):
            raise ValueError("metric_label must be a MetricLabel value")
        if not 0 <= self.recommendation_hour <= 23:
            raise ValueError("recommendation_hour must be between 0 and 23")
        if not self.recommendation_reason:
            raise ValueError("recommendation_reason is required")
        if not self.hourly:
            raise ValueError("hourly evidence is required")
        if self.recommendation_hour not in {entry.hour for entry in self.hourly}:
            raise ValueError("recommendation_hour must have hourly evidence")
        hours = [entry.hour for entry in self.hourly]
        if len(set(hours)) != len(hours):
            raise ValueError("hourly evidence must not contain duplicate hours")
        if not 0 < self.hourly_coverage <= 1:
            raise ValueError("hourly_coverage must be between 0 and 1")
        if self.hourly_coverage != len(hours) / 24:
            raise ValueError("hourly_coverage must match available hourly evidence")
        if any(entry.metric.label is not self.metric_label for entry in self.hourly):
            raise ValueError("hourly metric labels must match best-time metric label")
        recommendation = next(
            entry.metric.value for entry in self.hourly if entry.hour == self.recommendation_hour
        )
        if recommendation != min(entry.metric.value for entry in self.hourly):
            raise ValueError("recommendation_hour must be a coolest available hour")


@dataclass(frozen=True)
class RankedHotel:
    identity: str
    components: dict[str, float]
    score: float
    percentile: float
    tie_group: int

    def __post_init__(self) -> None:
        if not self.identity:
            raise ValueError("hotel identity is required")
        for name, value in self.components.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"hotel component {name} must be a finite number")
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")
        if not math.isfinite(self.percentile) or not 0 <= self.percentile <= 100:
            raise ValueError("percentile must be between 0 and 100")
        if (
            isinstance(self.tie_group, bool)
            or not isinstance(self.tie_group, int)
            or self.tie_group < 0
        ):
            raise ValueError("tie_group must be non-negative")


@dataclass(frozen=True)
class HotelRankingResult:
    """Ranked hotel list with weights and component breakdown."""

    ranked: tuple[RankedHotel, ...]
    weights: dict[str, float]
    usable_count: int
    discovered_count: int
    provenance: Provenance
    enrichment: OptionalEnrichment = OptionalEnrichment(EnrichmentState.NOT_REQUESTED)
    component_units: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.enrichment, OptionalEnrichment):
            raise ValueError("enrichment must be an OptionalEnrichment value")
        required = {"night", "hot_hours", "persistence", "day"}
        if set(self.weights) != required:
            raise ValueError(f"weights must be exactly {required}")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in self.weights.values()
        ):
            raise ValueError("weights must be finite and non-negative")
        if abs(sum(self.weights.values()) - 1) > 0.001:
            raise ValueError("weights must sum to 1")
        if self.usable_count < 0 or self.discovered_count < 0:
            raise ValueError("counts must be non-negative")
        if self.usable_count > self.discovered_count:
            raise ValueError("usable_count cannot exceed discovered_count")
        if self.usable_count != len(self.ranked):
            raise ValueError("usable_count must match ranked hotel count")
        if not self.ranked:
            raise ValueError("hotel ranking must not be empty")
        if self.component_units is None or set(self.component_units) != required:
            raise ValueError("component_units must define every hotel component")
        expected_units = {"night": "C", "hot_hours": "hours", "persistence": "hours", "day": "C"}
        if self.component_units != expected_units:
            raise ValueError("hotel component units must match their metric definitions")
        expected_scores = {
            hotel.identity: sum(hotel.components[name] * self.weights[name] for name in required)
            for hotel in self.ranked
        }
        if any(
            not math.isclose(hotel.score, expected_scores[hotel.identity]) for hotel in self.ranked
        ):
            raise ValueError("hotel score must equal weighted component values")
        distinct_scores = sorted({hotel.score for hotel in self.ranked})
        for hotel in self.ranked:
            expected_tie = distinct_scores.index(hotel.score)
            expected_percentile = 100 * (1 - expected_tie / max(1, len(distinct_scores) - 1))
            if hotel.tie_group != expected_tie or not math.isclose(
                hotel.percentile, expected_percentile
            ):
                raise ValueError("hotel percentile and tie group must match ranking")
        for left in self.ranked:
            for right in self.ranked:
                same_score = math.isclose(left.score, right.score)
                same_tie = left.tie_group == right.tie_group
                if same_score != same_tie:
                    raise ValueError("hotel ties must match equal scores")
                if same_tie and left.percentile != right.percentile:
                    raise ValueError("tied hotels must share a percentile")
        if any(
            current.score > following.score or current.percentile < following.percentile
            for current, following in zip(self.ranked, self.ranked[1:])
        ):
            raise ValueError("ranked hotels must be ordered by score and percentile")
        if len({hotel.identity for hotel in self.ranked}) != len(self.ranked):
            raise ValueError("ranked hotel identities must be unique")


@dataclass(frozen=True)
class RouteOption:
    identity: str
    distance_m: float
    duration_s: float
    heat_value: float
    heat_unit: str
    heat_metric: HeatMetricName
    heat_status: HeatStatus
    modeled_shade_percent: float | None
    shade_confidence: Confidence | None
    building_coverage: float
    recommended: bool
    recommendation_reason: str | None
    shade_model_label: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.heat_metric, HeatMetricName):
            raise ValueError("heat_metric must be a HeatMetricName value")
        if not isinstance(self.heat_status, HeatStatus):
            raise ValueError("heat_status must be a HeatStatus value")
        if self.shade_confidence is not None and not isinstance(self.shade_confidence, Confidence):
            raise ValueError("shade_confidence must be a Confidence value")
        if not isinstance(self.recommended, bool):
            raise ValueError("recommended must be a boolean")
        if not self.identity:
            raise ValueError("route identity is required")
        if not math.isfinite(self.distance_m) or self.distance_m <= 0:
            raise ValueError("distance_m must be positive and finite")
        if not math.isfinite(self.duration_s) or self.duration_s <= 0:
            raise ValueError("duration_s must be positive and finite")
        if not math.isfinite(self.heat_value):
            raise ValueError("heat_value must be finite")
        if not self.heat_unit:
            raise ValueError("heat_unit is required")
        if (
            self.heat_metric in (HeatMetricName.TCM, HeatMetricName.HEAT_INDEX_CELSIUS)
            and self.heat_unit != "C"
        ):
            raise ValueError("temperature route metrics must use C")
        if not 0 <= self.building_coverage <= 1:
            raise ValueError("building_coverage must be between 0 and 1")
        if self.modeled_shade_percent is not None and (
            not math.isfinite(self.modeled_shade_percent)
            or not 0 <= self.modeled_shade_percent <= 100
        ):
            raise ValueError("modeled_shade_percent must be between 0 and 100")
        if self.modeled_shade_percent is None and (
            self.shade_confidence is not None or self.shade_model_label is not None
        ):
            raise ValueError("shade metadata requires a modeled shade value")
        if self.modeled_shade_percent is not None and not self.shade_model_label:
            raise ValueError("modeled shade requires a model label")


@dataclass(frozen=True)
class RouteComparisonResult:
    """Route comparison with recommendation and heat context."""

    alternatives: tuple[RouteOption, ...]
    recommended_id: str
    reason: str
    heat_status: HeatStatus
    corridor_heat_value: float
    heat_metric: HeatMetricName
    heat_unit: str
    coverage: float
    confidence: Confidence
    comparison_scope: str
    provenance: Provenance
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.heat_metric, HeatMetricName):
            raise ValueError("heat_metric must be a HeatMetricName value")
        if not isinstance(self.heat_status, HeatStatus):
            raise ValueError("heat_status must be a HeatStatus value")
        if not isinstance(self.confidence, Confidence):
            raise ValueError("confidence must be a Confidence value")
        if not self.heat_unit:
            raise ValueError("heat_unit is required")
        if (
            self.heat_metric in (HeatMetricName.TCM, HeatMetricName.HEAT_INDEX_CELSIUS)
            and self.heat_unit != "C"
        ):
            raise ValueError("temperature comparison metrics must use C")
        if not math.isfinite(self.corridor_heat_value):
            raise ValueError("corridor_heat_value must be finite")
        if not self.alternatives:
            raise ValueError("at least one route alternative is required")
        if not self.recommended_id:
            raise ValueError("recommended_id is required")
        if not self.reason:
            raise ValueError("reason is required")
        if not self.comparison_scope:
            raise ValueError("comparison_scope is required")
        if self.confidence is Confidence.INSUFFICIENT and not self.fallback_reason:
            raise ValueError("insufficient confidence requires fallback_reason")
        if self.confidence is Confidence.SUFFICIENT and self.fallback_reason is not None:
            raise ValueError("sufficient confidence must not include fallback_reason")
        if not 0 <= self.coverage <= 1:
            raise ValueError("coverage must be between 0 and 1")
        identities = {route.identity for route in self.alternatives}
        if self.recommended_id not in identities:
            raise ValueError("recommended_id must reference a listed alternative")
        recommended = [route for route in self.alternatives if route.recommended]
        if len(recommended) != 1 or recommended[0].identity != self.recommended_id:
            raise ValueError("exactly one recommended route must match recommended_id")
        if recommended[0].recommendation_reason is None:
            raise ValueError("recommended route requires recommendation_reason")
        if self.confidence is Confidence.INSUFFICIENT:
            shortest = min(self.alternatives, key=lambda route: route.distance_m)
            if recommended[0].identity != shortest.identity:
                raise ValueError("insufficient confidence must recommend the shortest route")


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
    degraded_reasons: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, TripMode):
            raise ValueError("mode must be a TripMode value")
        if not isinstance(self.execution_mode, ExecutionMode):
            raise ValueError("execution_mode must be an ExecutionMode value")
        if not isinstance(self.state, ResultState):
            raise ValueError("state must be a ResultState value")
        if self.state is ResultState.SUCCESS:
            if not isinstance(self.best_time, BestTimeResult):
                raise ValueError("success state requires a BestTimeResult")
            if not isinstance(self.hotels, HotelRankingResult):
                raise ValueError("success state requires a HotelRankingResult")
            if not isinstance(self.routes, RouteComparisonResult):
                raise ValueError("success state requires a RouteComparisonResult")
            if self.best_time is None:
                raise ValueError("success state requires best_time")
            if self.hotels is None:
                raise ValueError("success state requires hotels")
            if self.routes is None:
                raise ValueError("success state requires routes")
            if self.unavailable is not None:
                raise ValueError("success state must not include unavailable")
            if self.degraded_reasons is not None:
                raise ValueError("success state must not include degraded_reasons")
        elif self.state is ResultState.UNAVAILABLE:
            if not isinstance(self.unavailable, UnavailableResult):
                raise ValueError("unavailable state requires unavailable detail")
            if self.best_time is not None or self.hotels is not None or self.routes is not None:
                raise ValueError("unavailable state must not include result data")
            if self.degraded_reasons is not None:
                raise ValueError("unavailable state must not include degraded_reasons")
        elif self.state is ResultState.DEGRADED:
            if self.best_time is None and self.hotels is None and self.routes is None:
                raise ValueError("degraded state requires at least one partial result")
            if not self.degraded_reasons:
                raise ValueError("degraded state requires degraded_reasons")
            if self.unavailable is not None:
                raise ValueError("degraded state must not include unavailable")
            if self.best_time is not None and not isinstance(self.best_time, BestTimeResult):
                raise ValueError("degraded best_time must be a BestTimeResult")
            if self.hotels is not None and not isinstance(self.hotels, HotelRankingResult):
                raise ValueError("degraded hotels must be a HotelRankingResult")
            if self.routes is not None and not isinstance(self.routes, RouteComparisonResult):
                raise ValueError("degraded routes must be a RouteComparisonResult")
            if set(self.degraded_reasons) - {"best_time", "hotels", "routes"}:
                raise ValueError("degraded_reasons contains an unknown section")
            missing = {
                name
                for name, value in (
                    ("best_time", self.best_time),
                    ("hotels", self.hotels),
                    ("routes", self.routes),
                )
                if value is None
            }
            allowed_present = {
                "routes"
                if self.routes is not None and self.routes.confidence is Confidence.INSUFFICIENT
                else ""
            }
            if set(self.degraded_reasons) != missing | (allowed_present - {""}):
                raise ValueError("degraded reasons must match missing sections")
        elif self.state is ResultState.ERROR:
            if not isinstance(self.unavailable, UnavailableResult):
                raise ValueError("error state requires unavailable detail")
            if self.best_time is not None or self.hotels is not None or self.routes is not None:
                raise ValueError("error state must not include result data")
            if self.degraded_reasons is not None:
                raise ValueError("error state must not include degraded_reasons")


class TripAnalysisAdapter(Protocol):
    """Fixture and live implementations share this provider-neutral boundary."""

    def analyze(
        self, request: TripAnalysisRequest, execution_mode: ExecutionMode
    ) -> TripAnalysisResponse: ...
