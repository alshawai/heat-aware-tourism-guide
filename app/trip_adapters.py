"""Fixture and live adapters for the shared trip-analysis contract."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Mapping

from app.contracts import (
    BestTimeResult,
    Confidence,
    EnrichmentState,
    ExecutionMode,
    HeatMetricName,
    HeatStatus,
    HotelRankingResult,
    HourlyEntry,
    Metric,
    MetricLabel,
    Provenance,
    RankedHotel,
    ResultState,
    RouteComparisonResult,
    RouteOption,
    TripAnalysisRequest,
    TripAnalysisResponse,
    UnavailableResult,
)


class FixtureTripAnalysisAdapter:
    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    def analyze(self, request: TripAnalysisRequest) -> TripAnalysisResponse:
        with self.fixture_path.open(encoding="utf-8") as fixture:
            payload = json.load(fixture)
        if not isinstance(payload, Mapping):
            raise ValueError("trip fixture must contain an object")
        return normalize_trip_analysis(payload, request, ExecutionMode.FIXTURE)


class LiveTripAnalysisAdapter:
    def __init__(
        self, loader: Callable[[TripAnalysisRequest], Mapping[str, object]]
    ) -> None:
        self.loader = loader

    def analyze(self, request: TripAnalysisRequest) -> TripAnalysisResponse:
        return normalize_trip_analysis(self.loader(request), request, ExecutionMode.LIVE)


def normalize_trip_analysis(
    payload: Mapping[str, object],
    request: TripAnalysisRequest,
    execution_mode: ExecutionMode,
) -> TripAnalysisResponse:
    unavailable = payload.get("unavailable")
    if unavailable is not None:
        if not isinstance(unavailable, str) or not unavailable:
            raise ValueError("unavailable must be a non-empty string")
        return TripAnalysisResponse(
            request_identity=_request_identity(request),
            mode=request.mode,
            execution_mode=execution_mode,
            state=ResultState.UNAVAILABLE,
            unavailable=UnavailableResult(unavailable, recoverable=True),
        )

    best_payload = _mapping(payload.get("best_time"), "best_time")
    hotel_payload = _mapping(payload.get("hotels"), "hotels")
    route_payload = _mapping(payload.get("routes"), "routes")
    best_provenance = _provenance(best_payload, execution_mode)
    hotel_provenance = _provenance(hotel_payload, execution_mode)
    route_provenance = _provenance(route_payload, execution_mode)

    metric_name = HeatMetricName(best_payload["metric_name"])
    metric_label = (
        MetricLabel.NOAA_HEAT_INDEX
        if metric_name is HeatMetricName.HEAT_INDEX_CELSIUS
        else MetricLabel.PROVIDER_TCM
    )
    hourly_payload = best_payload.get("hourly")
    if not isinstance(hourly_payload, list):
        raise ValueError("best_time.hourly must be a list")
    hourly = tuple(
        HourlyEntry(
            hour=_integer(_mapping(entry, "hourly entry")["hour"], "hour"),
            metric=Metric(
                value=_number(_mapping(entry, "hourly entry")["value"], "hourly value"),
                unit=str(best_payload["unit"]),
                label=metric_label,
                is_actual_heat_index=metric_name is HeatMetricName.HEAT_INDEX_CELSIUS,
            ),
        )
        for entry in hourly_payload
    )

    ranked_payload = hotel_payload.get("ranked")
    if not isinstance(ranked_payload, list):
        raise ValueError("hotels.ranked must be a list")
    ranked = tuple(
        RankedHotel(
            identity=str(_mapping(item, "ranked hotel")["identity"]),
            components=_number_dict(_mapping(item, "ranked hotel")["components"], "components"),
            score=_number(_mapping(item, "ranked hotel")["score"], "score"),
            percentile=_number(_mapping(item, "ranked hotel")["percentile"], "percentile"),
            tie_group=_integer(_mapping(item, "ranked hotel")["tie_group"], "tie_group"),
        )
        for item in ranked_payload
    )

    alternatives_payload = route_payload.get("alternatives")
    if not isinstance(alternatives_payload, list):
        raise ValueError("routes.alternatives must be a list")
    recommended_id = str(route_payload["recommended_id"])
    confidence = Confidence(route_payload["confidence"])
    heat_status = HeatStatus(route_payload["heat_status"])
    route_metric = HeatMetricName(route_payload["heat_metric"])
    alternatives = tuple(
        _route_option(item, recommended_id, route_metric, heat_status, confidence)
        for item in alternatives_payload
    )
    fallback_reason = route_payload.get("fallback_reason")
    response = TripAnalysisResponse(
        request_identity=_request_identity(request),
        mode=request.mode,
        execution_mode=execution_mode,
        state=ResultState.DEGRADED if fallback_reason else ResultState.SUCCESS,
        best_time=BestTimeResult(
            hourly=hourly,
            recommendation_hour=_integer(best_payload["recommendation_hour"], "recommendation_hour"),
            recommendation_reason=str(best_payload["recommendation_reason"]),
            metric_label=metric_label,
            provenance=best_provenance,
        ),
        hotels=HotelRankingResult(
            ranked=ranked,
            weights=_number_dict(hotel_payload["weights"], "weights"),
            usable_count=_integer(hotel_payload["usable_count"], "usable_count"),
            discovered_count=_integer(hotel_payload["discovered_count"], "discovered_count"),
            provenance=hotel_provenance,
            enrichment=EnrichmentState(hotel_payload.get("enrichment", "not_requested")),
        ),
        routes=RouteComparisonResult(
            alternatives=alternatives,
            recommended_id=recommended_id,
            reason=str(route_payload["reason"]),
            heat_status=heat_status,
            corridor_heat_value=_number(route_payload["corridor_heat_value"], "corridor_heat_value"),
            heat_metric=route_metric,
            coverage=_number(route_payload["coverage"], "coverage"),
            confidence=confidence,
            comparison_scope="returned alternatives",
            provenance=route_provenance,
            fallback_reason=str(fallback_reason) if fallback_reason else None,
        ),
    )
    return response


def _route_option(
    value: object,
    recommended_id: str,
    metric: HeatMetricName,
    status: HeatStatus,
    confidence: Confidence,
) -> RouteOption:
    item = _mapping(value, "route alternative")
    identity = str(item["identity"])
    shade = item.get("modeled_shade_percent")
    return RouteOption(
        identity=identity,
        distance_m=_number(item["distance_m"], "distance_m"),
        duration_s=_number(item["duration_s"], "duration_s"),
        heat_value=_number(item["heat_value"], "heat_value"),
        heat_metric=metric,
        heat_status=status,
        modeled_shade_percent=_number(shade, "modeled_shade_percent") if shade is not None else None,
        shade_confidence=confidence if shade is not None else None,
        building_coverage=_number(item["building_coverage"], "building_coverage"),
        recommended=identity == recommended_id,
        recommendation_reason=str(item["recommendation_reason"]) if item.get("recommendation_reason") else None,
        shade_model_label="modeled shade estimate based on OSM building data" if shade is not None else None,
    )


def _provenance(
    section: Mapping[str, object], execution_mode: ExecutionMode
) -> Provenance:
    raw = _mapping(section.get("provenance"), "provenance")
    return Provenance(
        source=execution_mode.value,
        data_date=str(raw["data_date"]),
        confidence=Confidence(raw["confidence"]),
        coverage=_number(raw["coverage"], "coverage") if raw.get("coverage") is not None else None,
        retrieved_at=str(raw["retrieved_at"]),
        transformation_version=str(raw["transformation_version"]),
        provider=str(raw["provider"]),
        activity_id=str(raw["activity_id"]) if raw.get("activity_id") else None,
        response_status=str(raw["response_status"]),
        request_configuration=dict(_mapping(raw["request_configuration"], "request_configuration")),
        fresh=_boolean(raw["fresh"], "fresh"),
        note=str(raw["note"]) if raw.get("note") else None,
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _number_dict(value: object, field: str) -> dict[str, float]:
    mapping = _mapping(value, field)
    return {str(key): _number(item, f"{field}.{key}") for key, item in mapping.items()}


def _request_identity(request: TripAnalysisRequest) -> str:
    return f"{request.mode.value}:{request.date}:{request.hour}"
