"""Fixture and live adapters for the shared trip-analysis contract."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Mapping

from app.domain.contracts import (
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
    OptionalEnrichment,
    TripAnalysisRequest,
    TripAnalysisResponse,
    UnavailableResult,
)
from app.services.sidecars import load_acquisition_record


class FixtureTripAnalysisAdapter:
    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    def analyze(
        self,
        request: TripAnalysisRequest,
        execution_mode: ExecutionMode = ExecutionMode.FIXTURE,
    ) -> TripAnalysisResponse:
        if execution_mode is not ExecutionMode.FIXTURE:
            raise ValueError("fixture adapter only supports fixture execution")
        with self.fixture_path.open(encoding="utf-8") as fixture:
            payload = json.load(fixture)
        if not isinstance(payload, Mapping):
            raise ValueError("trip fixture must contain an object")
        if payload.get("unavailable") is not None:
            return normalize_trip_analysis(payload, request, ExecutionMode.FIXTURE)
        scenario = _fixture_scenario(self.fixture_path, payload)
        if scenario is None or not _fixture_matches(scenario, request):
            return TripAnalysisResponse(
                request_identity=_request_identity(request),
                mode=request.mode,
                execution_mode=ExecutionMode.FIXTURE,
                state=ResultState.UNAVAILABLE,
                unavailable=UnavailableResult(
                    "no matching fixture for the requested trip", recoverable=True
                ),
            )
        return normalize_trip_analysis(payload, request, ExecutionMode.FIXTURE)


def _fixture_scenario(
    fixture_path: Path, payload: Mapping[str, object]
) -> Mapping[str, object] | None:
    """The authoritative match identity: acquisition sidecar, else the embedded block."""
    record = load_acquisition_record(fixture_path)
    if record is not None:
        if not record.replayable:
            return None
        return record.request_configuration or None
    embedded = payload.get("scenario")
    return embedded if isinstance(embedded, Mapping) else None


class LiveTripAnalysisAdapter:
    def __init__(
        self, loader: Callable[[TripAnalysisRequest], Mapping[str, object]]
    ) -> None:
        self.loader = loader

    def analyze(
        self,
        request: TripAnalysisRequest,
        execution_mode: ExecutionMode = ExecutionMode.LIVE,
    ) -> TripAnalysisResponse:
        if execution_mode is not ExecutionMode.LIVE:
            raise ValueError("live adapter only supports live execution")
        payload = self.loader(request)
        if not isinstance(payload, Mapping):
            raise ValueError("live trip analysis must return an object")
        return normalize_trip_analysis(payload, request, execution_mode)


class ModeDispatchTripAnalysisAdapter:
    """Selects the adapter owned by the requested execution mode."""

    def __init__(
        self,
        fixture: FixtureTripAnalysisAdapter,
        live: LiveTripAnalysisAdapter,
    ) -> None:
        self.fixture = fixture
        self.live = live

    def analyze(
        self, request: TripAnalysisRequest, execution_mode: ExecutionMode
    ) -> TripAnalysisResponse:
        if execution_mode not in (ExecutionMode.FIXTURE, ExecutionMode.LIVE):
            raise ValueError("unknown execution mode")
        adapter = self.fixture if execution_mode is ExecutionMode.FIXTURE else self.live
        return adapter.analyze(request, execution_mode)


def normalize_trip_analysis(
    payload: Mapping[str, object],
    request: TripAnalysisRequest,
    execution_mode: ExecutionMode,
) -> TripAnalysisResponse:
    unavailable = payload.get("unavailable")
    if unavailable is not None:
        if any(
            payload.get(field) is not None
            for field in ("best_time", "hotels", "routes", "degraded_reasons")
        ):
            raise ValueError("unavailable payload must not include result data")
        if not isinstance(unavailable, str) or not unavailable:
            raise ValueError("unavailable must be a non-empty string")
        return TripAnalysisResponse(
            request_identity=_request_identity(request),
            mode=request.mode,
            execution_mode=execution_mode,
            state=ResultState.UNAVAILABLE,
            unavailable=UnavailableResult(unavailable, recoverable=True),
        )

    degraded_reasons = _optional_string_dict(payload.get("degraded_reasons"), "degraded_reasons")
    if set(degraded_reasons) - {"best_time", "hotels", "routes"}:
        raise ValueError("degraded_reasons contains an unknown section")
    best_value = payload.get("best_time")
    hotel_value = payload.get("hotels")
    route_value = payload.get("routes")
    _require_section_reason("best_time", best_value, degraded_reasons)
    _require_section_reason("hotels", hotel_value, degraded_reasons)
    _require_section_reason("routes", route_value, degraded_reasons)

    best_time = _best_time(_mapping(best_value, "best_time"), execution_mode, request.date) if best_value is not None else None
    hotels = _hotels(_mapping(hotel_value, "hotels"), execution_mode, request.date) if hotel_value is not None else None
    routes = _routes(_mapping(route_value, "routes"), execution_mode, request.date) if route_value is not None else None
    expected_reasons = {
        name
        for name, value in (
            ("best_time", best_time),
            ("hotels", hotels),
            ("routes", routes),
        )
        if value is None
    }
    if routes is not None and routes.confidence is Confidence.INSUFFICIENT:
        expected_reasons.add("routes")
    if set(degraded_reasons) != expected_reasons:
        raise ValueError("degraded reasons must match unavailable or limited sections")

    return TripAnalysisResponse(
        request_identity=_request_identity(request),
        mode=request.mode,
        execution_mode=execution_mode,
        state=ResultState.DEGRADED if degraded_reasons else ResultState.SUCCESS,
        best_time=best_time,
        hotels=hotels,
        routes=routes,
        degraded_reasons=degraded_reasons or None,
    )


def _best_time(
    best_payload: Mapping[str, object], execution_mode: ExecutionMode, request_date: str
) -> BestTimeResult:
    best_provenance = _provenance(best_payload, execution_mode)
    if best_provenance.data_date != request_date:
        raise ValueError("best-time provenance date does not match request")

    metric_name = HeatMetricName(_string(best_payload["metric_name"], "metric_name"))
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
                unit=_string(best_payload["unit"], "unit"),
                label=metric_label,
                is_actual_heat_index=metric_name is HeatMetricName.HEAT_INDEX_CELSIUS,
            ),
        )
        for entry in hourly_payload
    )

    return BestTimeResult(
        hourly=hourly,
        recommendation_hour=_integer(best_payload["recommendation_hour"], "recommendation_hour"),
        recommendation_reason=_string(best_payload["recommendation_reason"], "recommendation_reason"),
        metric_label=metric_label,
        provenance=best_provenance,
        hourly_coverage=_number(best_payload["hourly_coverage"], "hourly_coverage"),
    )


def _hotels(
    hotel_payload: Mapping[str, object], execution_mode: ExecutionMode, request_date: str
) -> HotelRankingResult:
    hotel_provenance = _provenance(hotel_payload, execution_mode)
    if hotel_provenance.data_date != request_date:
        raise ValueError("hotel provenance date does not match request")
    ranked_payload = hotel_payload.get("ranked")
    if not isinstance(ranked_payload, list):
        raise ValueError("hotels.ranked must be a list")
    ranked = tuple(
        RankedHotel(
            identity=_string(_mapping(item, "ranked hotel")["identity"], "hotel identity"),
            components=_number_dict(_mapping(item, "ranked hotel")["components"], "components"),
            score=_number(_mapping(item, "ranked hotel")["score"], "score"),
            percentile=_number(_mapping(item, "ranked hotel")["percentile"], "percentile"),
            tie_group=_integer(_mapping(item, "ranked hotel")["tie_group"], "tie_group"),
        )
        for item in ranked_payload
    )

    enrichment_state = EnrichmentState(
        _string(hotel_payload.get("enrichment", "not_requested"), "enrichment")
    )
    enrichment_reason = (
        _string(hotel_payload["enrichment_reason"], "enrichment_reason")
        if hotel_payload.get("enrichment_reason") is not None
        else None
    )
    return HotelRankingResult(
        ranked=ranked,
        weights=_number_dict(hotel_payload["weights"], "weights"),
        usable_count=_integer(hotel_payload["usable_count"], "usable_count"),
        discovered_count=_integer(hotel_payload["discovered_count"], "discovered_count"),
        provenance=hotel_provenance,
        enrichment=OptionalEnrichment(enrichment_state, enrichment_reason),
        component_units=_string_dict(hotel_payload["component_units"], "component_units"),
    )


def _routes(
    route_payload: Mapping[str, object], execution_mode: ExecutionMode, request_date: str
) -> RouteComparisonResult:
    route_provenance = _provenance(route_payload, execution_mode)
    if route_provenance.data_date != request_date:
        raise ValueError("route provenance date does not match request")
    alternatives_payload = route_payload.get("alternatives")
    if not isinstance(alternatives_payload, list):
        raise ValueError("routes.alternatives must be a list")
    recommended_id = _string(route_payload["recommended_id"], "recommended_id")
    confidence = Confidence(_string(route_payload["confidence"], "confidence"))
    heat_status = HeatStatus(_string(route_payload["heat_status"], "heat_status"))
    route_metric = HeatMetricName(_string(route_payload["heat_metric"], "heat_metric"))
    route_unit = _string(route_payload["heat_unit"], "heat_unit")
    alternatives = tuple(
        _route_option(item, recommended_id, route_metric, route_unit, heat_status, confidence)
        for item in alternatives_payload
    )
    fallback_reason = route_payload.get("fallback_reason")
    return RouteComparisonResult(
        alternatives=alternatives,
        recommended_id=recommended_id,
        reason=_string(route_payload["reason"], "reason"),
        heat_status=heat_status,
        corridor_heat_value=_number(route_payload["corridor_heat_value"], "corridor_heat_value"),
        heat_metric=route_metric,
        heat_unit=route_unit,
        coverage=_number(route_payload["coverage"], "coverage"),
        confidence=confidence,
        comparison_scope="returned alternatives",
        provenance=route_provenance,
        fallback_reason=_string(fallback_reason, "fallback_reason") if fallback_reason is not None else None,
    )


def _route_option(
    value: object,
    recommended_id: str,
    metric: HeatMetricName,
    unit: str,
    status: HeatStatus,
    confidence: Confidence,
) -> RouteOption:
    item = _mapping(value, "route alternative")
    identity = _string(item["identity"], "route identity")
    shade = item.get("modeled_shade_percent")
    return RouteOption(
        identity=identity,
        distance_m=_number(item["distance_m"], "distance_m"),
        duration_s=_number(item["duration_s"], "duration_s"),
        heat_value=_number(item["heat_value"], "heat_value"),
        heat_unit=unit,
        heat_metric=metric,
        heat_status=status,
        modeled_shade_percent=_number(shade, "modeled_shade_percent") if shade is not None else None,
        shade_confidence=confidence if shade is not None else None,
        building_coverage=_number(item["building_coverage"], "building_coverage"),
        recommended=identity == recommended_id,
        recommendation_reason=_string(item["recommendation_reason"], "recommendation_reason") if item.get("recommendation_reason") is not None else None,
        shade_model_label="modeled shade estimate based on OSM building data" if shade is not None else None,
    )


def _provenance(
    section: Mapping[str, object], execution_mode: ExecutionMode
) -> Provenance:
    raw = _mapping(section.get("provenance"), "provenance")
    return Provenance(
        source=execution_mode.value,
        data_date=_string(raw["data_date"], "data_date"),
        confidence=Confidence(raw["confidence"]),
        coverage=_number(raw["coverage"], "coverage") if raw.get("coverage") is not None else None,
        retrieved_at=_string(raw["retrieved_at"], "retrieved_at"),
        transformation_version=_string(raw["transformation_version"], "transformation_version"),
        provider=_string(raw["provider"], "provider"),
        activity_id=_string(raw["activity_id"], "activity_id") if raw.get("activity_id") is not None else None,
        response_status=_string(raw["response_status"], "response_status"),
        request_configuration=dict(_mapping(raw["request_configuration"], "request_configuration")),
        fresh=_boolean(raw["fresh"], "fresh"),
        note=_string(raw["note"], "note") if raw.get("note") is not None else None,
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _require_section_reason(
    name: str, value: object, reasons: dict[str, str]
) -> None:
    if value is None and name not in reasons:
        raise ValueError(f"missing {name} without degraded reason")


def _optional_string_dict(value: object, field: str) -> dict[str, str]:
    if value is None:
        return {}
    mapping = _mapping(value, field)
    return {str(key): _string(item, f"{field}.{key}") for key, item in mapping.items()}


def _string_dict(value: object, field: str) -> dict[str, str]:
    mapping = _mapping(value, field)
    return {str(key): _string(item, f"{field}.{key}") for key, item in mapping.items()}


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


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


def _fixture_matches(
    scenario: Mapping[str, object], request: TripAnalysisRequest
) -> bool:
    origin = _mapping(scenario.get("origin"), "scenario origin")
    destination = _mapping(scenario.get("destination"), "scenario destination")
    return (
        _string(scenario.get("landmark_name"), "scenario landmark_name")
        == request.landmark_name
        and _string(scenario.get("district_name"), "scenario district_name")
        == request.district_name
        and _string(scenario.get("date"), "scenario date") == request.date
        and math.isclose(_number(origin.get("latitude"), "origin latitude"), request.origin.latitude)
        and math.isclose(_number(origin.get("longitude"), "origin longitude"), request.origin.longitude)
        and math.isclose(
            _number(destination.get("latitude"), "destination latitude"),
            request.destination.latitude,
        )
        and math.isclose(
            _number(destination.get("longitude"), "destination longitude"),
            request.destination.longitude,
        )
    )
