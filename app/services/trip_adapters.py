"""Fixture and live adapters for the shared trip-analysis contract."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from collections.abc import Sequence
from typing import Callable, Mapping

from app.domain.contracts import (
    BestTimeResult,
    Confidence,
    Coordinates,
    EnrichmentState,
    EnvironmentSeriesEntry,
    EnvironmentSeriesResult,
    ExecutionMode,
    HeatMetricName,
    HeatStatus,
    HotelRankingResult,
    HourlyEntry,
    Metric,
    MetricLabel,
    OptionalEnrichment,
    Provenance,
    RankedHotel,
    ResultState,
    RouteComparisonResult,
    RouteDecisionState,
    RouteOption,
    RouteSetState,
    TripAnalysisAdapter,
    TemporalEvidenceState,
    TripAnalysisRequest,
    TripAnalysisResponse,
    TripMode,
    UnavailableResult,
)
from app.domain.route_shade import ShadeConfidence
from app.domain.environment import select_anchor_celsius
from app.domain.best_time import HourlyConcernProfile, assess_hour, select_best_time
from app.domain.heat_policy import classify_heat
from app.integrations.fortyguard.contracts import (
    AnalyticType,
    EnvParamsRequest,
    HeatmapRequest,
    HeatmapResult,
)
from app.services.execution import (
    EnvParamsExecution,
    EnvParamsOutcome,
    HeatmapExecution,
    UnavailableError,
)
from app.services.route_analysis import RouteAnalysisService
from app.services.routing import RouteUnavailable
from app.services.sidecars import load_acquisition_record
from app.services.trip_contract_v2 import SCHEMA_VERSION, decode_trip_analysis_v2


FRAMING_THRESHOLD_CELSIUS = 35.0
FRAMING_DIRECTION = "above"


class FixtureTripAnalysisAdapter:
    def __init__(self, fixture_path: Path | Sequence[Path]) -> None:
        self.fixture_paths = (
            (fixture_path,) if isinstance(fixture_path, Path) else tuple(fixture_path)
        )
        if not self.fixture_paths:
            raise ValueError("at least one trip fixture path is required")
        if any(not isinstance(path, Path) for path in self.fixture_paths):
            raise ValueError("trip fixture paths must be Path values")
        self.fixture_path = self.fixture_paths[0]
        self._fixtures = tuple(self._load_fixture(path) for path in self.fixture_paths)

    @staticmethod
    def _load_fixture(
        fixture_path: Path,
    ) -> tuple[Path, Mapping[str, object], Mapping[str, object], str]:
        with fixture_path.open(encoding="utf-8") as fixture:
            payload = json.load(fixture)
        if not isinstance(payload, Mapping):
            raise ValueError(f"trip fixture {fixture_path} must contain an object")
        record = load_acquisition_record(fixture_path)
        if record is None:
            raise ValueError(f"trip fixture {fixture_path} requires an acquisition sidecar")
        if record.status not in {"ok", "unavailable"}:
            raise ValueError(
                f"trip fixture sidecar for {fixture_path} has unsupported status {record.status!r}"
            )
        if not record.request_configuration:
            raise ValueError(f"trip fixture sidecar for {fixture_path} requires request identity")
        schema_version = payload.get("schema_version", record.schema_version)
        if schema_version != record.schema_version:
            raise ValueError(f"trip fixture {fixture_path} schema does not match its sidecar")
        fixture_request = _request_from_fixture_identity(record.request_configuration)
        if schema_version != SCHEMA_VERSION:
            raise ValueError(f"trip fixture {fixture_path} must use {SCHEMA_VERSION}")
        if set(payload) != {
            "schema_version",
            "state",
            "best_time",
            "hotels",
            "routes",
            "unavailable",
            "degraded_reasons",
        }:
            raise ValueError(f"trip fixture {fixture_path} has an invalid v2 envelope")
        decode_trip_analysis_v2(payload, fixture_request, ExecutionMode.FIXTURE)
        return fixture_path, payload, record.request_configuration, schema_version

    def analyze(
        self,
        request: TripAnalysisRequest,
        execution_mode: ExecutionMode = ExecutionMode.FIXTURE,
    ) -> TripAnalysisResponse:
        if execution_mode is not ExecutionMode.FIXTURE:
            raise ValueError("fixture adapter only supports fixture execution")
        matches = [fixture for fixture in self._fixtures if _fixture_matches(fixture[2], request)]
        if len(matches) > 1:
            duplicate_paths = ", ".join(str(fixture[0]) for fixture in matches)
            raise ValueError(f"duplicate matching trip fixtures: {duplicate_paths}")
        if not matches:
            return TripAnalysisResponse(
                request_identity=_request_identity(request),
                mode=request.mode,
                execution_mode=ExecutionMode.FIXTURE,
                state=ResultState.UNAVAILABLE,
                unavailable=UnavailableResult(
                    (
                        "no matching fixture for the requested exploratory trip"
                        if request.mode is TripMode.EXPLORATORY
                        else "no matching fixture for the requested trip"
                    ),
                    recoverable=True,
                    code="scenario_unavailable",
                    action="edit_setup_or_use_live_data",
                ),
            )
        _, payload, _, schema_version = matches[0]
        return decode_trip_analysis_v2(payload, request, ExecutionMode.FIXTURE)


class LiveTripAnalysisAdapter:
    def __init__(self, loader: Callable[[TripAnalysisRequest], Mapping[str, object]]) -> None:
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
        if payload.get("schema_version") == SCHEMA_VERSION:
            return decode_trip_analysis_v2(payload, request, execution_mode)
        return normalize_trip_analysis(payload, request, execution_mode)


class TemporalTripAnalysisAdapter:
    """Build the best-time decision from one reusable landmark series."""

    def __init__(
        self,
        heatmap_execution: HeatmapExecution,
        env_params_execution: EnvParamsExecution,
        route_analysis: RouteAnalysisService | None = None,
    ) -> None:
        self.heatmap_execution = heatmap_execution
        self.env_params_execution = env_params_execution
        self.route_analysis = route_analysis

    def analyze(
        self,
        request: TripAnalysisRequest,
        execution_mode: ExecutionMode = ExecutionMode.LIVE,
    ) -> TripAnalysisResponse:
        if execution_mode is not ExecutionMode.LIVE:
            raise ValueError("temporal trip adapter only supports live execution")
        analysis_date = date.fromisoformat(request.date)
        heatmap_request = HeatmapRequest(
            analytic_type=AnalyticType.TCM,
            latitude=request.destination.latitude,
            longitude=request.destination.longitude,
            start_date=analysis_date,
            forecast=analysis_date >= date.today(),
            start_hour=request.start_hour,
            end_hour=request.end_hour,
        )
        try:
            heatmap = self.heatmap_execution.run(heatmap_request, live=True)
            anchor = select_anchor_celsius(heatmap.tiles, request.window)
        except (UnavailableError, ValueError) as error:
            return _unavailable_response(request, execution_mode, str(error))

        environment: EnvironmentSeriesResult | None = None
        environment_failure: str | None = None
        try:
            env_request = EnvParamsRequest(
                latitude=heatmap_request.latitude,
                longitude=heatmap_request.longitude,
                start_date=analysis_date,
                temperature_anchor_celsius=anchor,
                start_hour=request.start_hour,
                end_hour=request.end_hour,
            )
            outcome = self.env_params_execution.run(env_request, live=True)
            environment = _environment_result(request, anchor, heatmap, outcome)
        except (UnavailableError, ValueError) as error:
            environment_failure = str(error)

        exceedance_hours = self._framing_value(heatmap_request, AnalyticType.EXCEEDANCE)
        persistence_hours = self._framing_value(heatmap_request, AnalyticType.PERSISTENCE)
        try:
            best_time = _best_time_result(
                request,
                heatmap,
                environment,
                environment_failure=environment_failure,
                exceedance_hours=exceedance_hours,
                persistence_hours=persistence_hours,
            )
        except ValueError as error:
            return _unavailable_response(request, execution_mode, str(error))
        routes: RouteComparisonResult | None = None
        route_reason: str | None = None
        if self.route_analysis is None:
            route_reason = "route comparison is not configured on the temporal live path"
        else:
            try:
                routes = self.route_analysis.analyze(request, best_time)
            except RouteUnavailable as error:
                route_reason = str(error)
            else:
                route_reason = _route_degradation_reason(routes)

        degraded_reasons = {"hotels": "hotel ranking is not implemented on the temporal live path"}
        if route_reason is not None:
            degraded_reasons["routes"] = route_reason
        return TripAnalysisResponse(
            request_identity=_request_identity(request),
            mode=request.mode,
            execution_mode=execution_mode,
            state=ResultState.DEGRADED,
            best_time=best_time,
            routes=routes,
            degraded_reasons=degraded_reasons,
        )

    def _framing_value(
        self, tcm_request: HeatmapRequest, analytic_type: AnalyticType
    ) -> float | None:
        request = HeatmapRequest(
            analytic_type=analytic_type,
            latitude=tcm_request.latitude,
            longitude=tcm_request.longitude,
            start_date=tcm_request.start_date,
            forecast=tcm_request.forecast,
            threshold_celsius=FRAMING_THRESHOLD_CELSIUS,
            direction=FRAMING_DIRECTION,
            start_hour=tcm_request.start_hour,
            end_hour=tcm_request.end_hour,
        )
        try:
            result = self.heatmap_execution.run(request, live=True)
        except (UnavailableError, ValueError):
            return None
        return max((tile.metric_value for tile in result.tiles), default=None)


def _route_degradation_reason(routes: RouteComparisonResult) -> str | None:
    if routes.decision_state is RouteDecisionState.SHADE_REQUIRED:
        return "route heat is elevated; shade analysis is required before recommendation"
    if routes.decision_state is RouteDecisionState.INSUFFICIENT_SHADE_COMPARISON_REQUIRED:
        return "modeled building-shade evidence is insufficient for a recommendation"
    if routes.decision_state is RouteDecisionState.HEAT_UNAVAILABLE:
        return "shared corridor heat is unavailable"
    if routes.decision_state is RouteDecisionState.NO_SUITABLE_RETURNED_ROUTE:
        return "no returned route has sufficient evidence for recommendation"
    if routes.route_set_state is RouteSetState.SINGLE_ROUTE:
        return "only one pedestrian route was returned; comparison is limited"
    return None


def _best_time_result(
    request: TripAnalysisRequest,
    heatmap: HeatmapResult,
    environment: EnvironmentSeriesResult | None,
    *,
    environment_failure: str | None,
    exceedance_hours: float | None,
    persistence_hours: float | None,
) -> BestTimeResult:
    tcm_by_hour = {
        hour: max(
            tile.value_celsius
            for tile in heatmap.tiles
            if tile.valid_time.hour == hour and tile.value_celsius is not None
        )
        for hour in request.window.hours
        if any(
            tile.valid_time.hour == hour and tile.value_celsius is not None
            for tile in heatmap.tiles
        )
    }
    if not tcm_by_hour:
        raise ValueError("no TCM values are available in the traveler window")
    parameters_by_hour = (
        {entry.valid_time.hour: entry.parameters for entry in environment.entries}
        if environment is not None
        else {}
    )
    profiles = tuple(
        assess_hour(
            hour,
            tcm_celsius=tcm,
            parameters=parameters_by_hour.get(hour, {}),
        )
        for hour, tcm in sorted(tcm_by_hour.items())
    )
    decision = select_best_time(profiles, cautious=request.cautious)
    hourly = tuple(
        HourlyEntry(
            hour=profile.hour,
            metric=Metric(
                value=profile.primary_thermal_value,
                unit="C",
                label=(
                    MetricLabel.NOAA_HEAT_INDEX
                    if profile.primary_thermal_metric is HeatMetricName.HEAT_INDEX_CELSIUS
                    else MetricLabel.PROVIDER_TCM
                ),
                is_actual_heat_index=(
                    profile.primary_thermal_metric is HeatMetricName.HEAT_INDEX_CELSIUS
                ),
            ),
        )
        for profile in profiles
    )
    provenance = (
        environment.provenance
        if environment is not None
        else _heatmap_product_provenance(request, heatmap)
    )
    provenance = _best_time_provenance(
        provenance,
        profiles,
        heatmap=heatmap,
        exceedance_hours=exceedance_hours,
        persistence_hours=persistence_hours,
    )
    reason = decision.reason
    if environment_failure is not None:
        reason = f"TCM-only fallback because environmental parameters are unavailable; {reason}"
    selected_times = tuple(
        {tile.valid_time for tile in heatmap.tiles if tile.valid_time.hour == decision.hour}
    )
    recommendation_time: datetime | None = None
    recommendation_timezone: str | None = None
    temporal_evidence = TemporalEvidenceState.UNAVAILABLE
    if len(selected_times) == 1:
        candidate = selected_times[0]
        requested_zone = environment.timezone if environment is not None else "America/Chicago"
        try:
            zone = ZoneInfo(requested_zone)
        except (ZoneInfoNotFoundError, ValueError):
            requested_zone = "America/Chicago"
            zone = ZoneInfo(requested_zone)
        local = candidate.astimezone(zone)
        if (
            local.date() == date.fromisoformat(request.date)
            and local.hour == decision.hour
            and candidate.utcoffset() == local.utcoffset()
        ):
            recommendation_time = candidate
            recommendation_timezone = requested_zone
            temporal_evidence = TemporalEvidenceState.EXACT
        else:
            temporal_evidence = TemporalEvidenceState.INCONSISTENT
    elif len(selected_times) > 1:
        temporal_evidence = TemporalEvidenceState.INCONSISTENT
    selected_label = next(entry.metric.label for entry in hourly if entry.hour == decision.hour)
    return BestTimeResult(
        hourly=hourly,
        recommendation_hour=decision.hour,
        recommendation_reason=reason,
        metric_label=selected_label,
        provenance=provenance,
        hourly_coverage=len(hourly) / 24,
        heat_interpretation=classify_heat(
            decision.profile.primary_thermal_value,
            metric=decision.profile.primary_thermal_metric,
            cautious=request.cautious,
        ),
        environmental_concerns=profiles,
        recommended_hour_tcm_celsius=tcm_by_hour[decision.hour],
        exceedance_hours=exceedance_hours,
        persistence_hours=persistence_hours,
        framing_threshold_celsius=FRAMING_THRESHOLD_CELSIUS,
        framing_direction=FRAMING_DIRECTION,
        recommendation_time=recommendation_time,
        recommendation_timezone=recommendation_timezone,
        temporal_evidence=temporal_evidence,
    )


def _best_time_provenance(
    provenance: Provenance,
    profiles: tuple[HourlyConcernProfile, ...],
    *,
    heatmap: HeatmapResult,
    exceedance_hours: float | None,
    persistence_hours: float | None,
) -> Provenance:
    configuration = dict(provenance.request_configuration)
    configuration.update(
        {
            "framing_threshold_celsius": FRAMING_THRESHOLD_CELSIUS,
            "framing_direction": FRAMING_DIRECTION,
            "exceedance_available": exceedance_hours is not None,
            "persistence_available": persistence_hours is not None,
            "environment_parameter_count": len(profiles[0].concerns),
            "reported_parameter_observations": sum(
                len(profile.concerns) - profile.not_reported_count for profile in profiles
            ),
            "not_reported_parameter_observations": sum(
                profile.not_reported_count for profile in profiles
            ),
            "tcm_source": heatmap.provenance.source,
            "environment_source": provenance.source,
        }
    )
    return Provenance(
        source=(
            heatmap.provenance.source
            if heatmap.provenance.source != "provider"
            else provenance.source
        ),
        data_date=provenance.data_date,
        confidence=provenance.confidence,
        retrieved_at=provenance.retrieved_at,
        transformation_version="best-time-decision-v1",
        provider=provenance.provider,
        response_status=provenance.response_status,
        request_configuration=configuration,
        fresh=provenance.fresh and not heatmap.provenance.stale,
        coverage=provenance.coverage,
        note=provenance.note,
        activity_id=provenance.activity_id,
    )


def _heatmap_product_provenance(request: TripAnalysisRequest, heatmap: HeatmapResult) -> Provenance:
    provider_provenance = heatmap.provenance
    retrieved_at = provider_provenance.retrieved_at
    if not isinstance(retrieved_at, datetime):
        raise ValueError("heatmap provenance retrieval time is incomplete")
    return Provenance(
        source=provider_provenance.source,
        data_date=provider_provenance.data_date,
        confidence=Confidence.SUFFICIENT,
        retrieved_at=retrieved_at.isoformat(),
        transformation_version="best-time-decision-v1",
        provider="fortyguard",
        response_status="completed",
        request_configuration={
            "latitude": request.destination.latitude,
            "longitude": request.destination.longitude,
            "start_date": request.date,
            "start_hour": request.start_hour,
            "end_hour": request.end_hour,
            "anchor_policy": "maximum_in_window_temperature_celsius",
            "forecast": provider_provenance.forecast,
            "heatmap_transformations": [
                {"name": transformation.name, "version": transformation.version}
                for transformation in provider_provenance.transformations
            ],
        },
        fresh=not provider_provenance.stale,
        activity_id=provider_provenance.activity_id,
    )


def _environment_result(
    request: TripAnalysisRequest,
    anchor: float,
    heatmap: HeatmapResult,
    outcome: EnvParamsOutcome,
) -> EnvironmentSeriesResult:
    if outcome.retrieved_at is None or outcome.data_date is None:
        raise ValueError("environmental-parameters provenance is incomplete")
    entries = tuple(
        EnvironmentSeriesEntry(
            valid_time=entry.valid_time,
            heat_index_celsius=entry.heat_index_celsius,
            humidity_percent=entry.humidity_percent,
            parameters=dict(entry.parameters),
        )
        for entry in outcome.result.entries
        if request.window.contains_hour(entry.valid_time.hour)
    )
    provenance = Provenance(
        source=outcome.source,
        data_date=outcome.data_date,
        confidence=Confidence.SUFFICIENT,
        retrieved_at=outcome.retrieved_at.isoformat(),
        transformation_version="trip-environment-series-v1",
        provider="fortyguard",
        response_status="completed",
        request_configuration={
            "latitude": request.destination.latitude,
            "longitude": request.destination.longitude,
            "start_date": request.date,
            "start_hour": request.start_hour,
            "end_hour": request.end_hour,
            "temperature_anchor_celsius": anchor,
            "anchor_policy": "maximum_in_window_temperature_celsius",
            "heatmap_source": heatmap.provenance.source,
            "heatmap_activity_id": heatmap.provenance.activity_id,
            "forecast": heatmap.provenance.forecast,
            "heatmap_transformations": [
                {"name": transformation.name, "version": transformation.version}
                for transformation in heatmap.provenance.transformations
            ],
            "environment_transformations": [
                {"name": transformation.name, "version": transformation.version}
                for transformation in outcome.transformations
            ],
        },
        fresh=not heatmap.provenance.stale and not outcome.stale,
        activity_id=outcome.activity_id,
    )
    return EnvironmentSeriesResult(
        entries=entries,
        timezone=outcome.result.timezone,
        temperature_anchor_celsius=anchor,
        warning="fixed temperature anchor; not a real 24-hour forecast",
        provenance=provenance,
    )


def _unavailable_response(
    request: TripAnalysisRequest,
    execution_mode: ExecutionMode,
    reason: str,
    *,
    code: str = "provider_data_missing",
    recoverable: bool = True,
    action: str | None = "retry_or_edit_setup",
) -> TripAnalysisResponse:
    return TripAnalysisResponse(
        request_identity=_request_identity(request),
        mode=request.mode,
        execution_mode=execution_mode,
        state=ResultState.UNAVAILABLE,
        unavailable=UnavailableResult(reason, recoverable, code, action),
    )


class ModeDispatchTripAnalysisAdapter:
    """Selects the adapter owned by the requested execution mode."""

    def __init__(
        self,
        fixture: FixtureTripAnalysisAdapter,
        live: TripAnalysisAdapter,
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

    best_time = (
        _best_time(
            _mapping(best_value, "best_time"), execution_mode, request.date, request.cautious
        )
        if best_value is not None
        else None
    )
    hotels = (
        _hotels(_mapping(hotel_value, "hotels"), execution_mode, request.date)
        if hotel_value is not None
        else None
    )
    routes = (
        _routes(_mapping(route_value, "routes"), execution_mode, request.date, request.cautious)
        if route_value is not None
        else None
    )
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
    best_payload: Mapping[str, object],
    execution_mode: ExecutionMode,
    request_date: str,
    cautious: bool,
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
    hourly_items = tuple(_mapping(entry, "hourly entry") for entry in hourly_payload)
    hourly = tuple(
        HourlyEntry(
            hour=_integer(entry["hour"], "hour"),
            metric=Metric(
                value=_number(entry["value"], "hourly value"),
                unit=_string(best_payload["unit"], "unit"),
                label=metric_label,
                is_actual_heat_index=metric_name is HeatMetricName.HEAT_INDEX_CELSIUS,
            ),
        )
        for entry in hourly_items
    )
    heat_index_by_hour = {
        _integer(entry["hour"], "hour"): (
            _number(entry["value"], "hourly value")
            if metric_name is HeatMetricName.HEAT_INDEX_CELSIUS
            else _optional_number(entry.get("heat_index_celsius"), "heat_index_celsius")
        )
        for entry in hourly_items
    }
    recommendation_hour = _integer(best_payload["recommendation_hour"], "recommendation_hour")
    recommendation_value = next(
        (entry.metric.value for entry in hourly if entry.hour == recommendation_hour), None
    )
    if cautious:
        recommendation_hour = _cautious_hour(hourly, metric_name, heat_index_by_hour)
        recommendation_value = next(
            entry.metric.value for entry in hourly if entry.hour == recommendation_hour
        )
    selected_heat_index = heat_index_by_hour[recommendation_hour]
    interpretation_metric = (
        HeatMetricName.HEAT_INDEX_CELSIUS if selected_heat_index is not None else metric_name
    )
    interpretation_value = (
        selected_heat_index if selected_heat_index is not None else recommendation_value
    )
    interpretation = classify_heat(
        interpretation_value,
        metric=interpretation_metric,
        cautious=cautious,
        noaa_heat_index_available=selected_heat_index is not None,
    )
    temporal_evidence = TemporalEvidenceState(
        _string(best_payload.get("temporal_evidence", "unavailable"), "temporal_evidence")
    )
    recommendation_time = (
        datetime.fromisoformat(_string(best_payload["recommendation_time"], "recommendation_time"))
        if best_payload.get("recommendation_time") is not None
        else None
    )
    recommendation_timezone = (
        _string(best_payload["recommendation_timezone"], "recommendation_timezone")
        if best_payload.get("recommendation_timezone") is not None
        else None
    )
    recommendation_reason = _string(best_payload["recommendation_reason"], "recommendation_reason")
    if cautious:
        recommendation_reason = (
            "more cautious guidance selected the coolest period below the earlier action threshold"
            if not interpretation.action_required
            else "more cautious guidance selected the lowest available metric value; all periods meet the earlier action threshold"
        )

    return BestTimeResult(
        hourly=hourly,
        recommendation_hour=recommendation_hour,
        recommendation_reason=recommendation_reason,
        metric_label=metric_label,
        provenance=best_provenance,
        hourly_coverage=_number(best_payload["hourly_coverage"], "hourly_coverage"),
        heat_interpretation=interpretation,
        recommendation_time=recommendation_time,
        recommendation_timezone=recommendation_timezone,
        temporal_evidence=temporal_evidence,
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
        enrichment=OptionalEnrichment(
            enrichment_state,
            code="optional_provider_failure"
            if enrichment_state is EnrichmentState.UNAVAILABLE
            else None,
            reason=enrichment_reason,
        ),
        component_units=_string_dict(hotel_payload["component_units"], "component_units"),
    )


def _routes(
    route_payload: Mapping[str, object],
    execution_mode: ExecutionMode,
    request_date: str,
    cautious: bool,
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
    route_values = tuple(
        _number(_mapping(item, "route alternative")["heat_value"], "heat_value")
        for item in alternatives_payload
    )
    original_recommended_id = recommended_id
    if cautious and confidence is Confidence.SUFFICIENT:
        recommended_id = _cautious_route_id(
            alternatives_payload, route_metric, route_values, recommended_id
        )
    recommendation_reason = _string(route_payload["reason"], "reason")
    cautious_selected_route = cautious and recommended_id != original_recommended_id
    if cautious_selected_route:
        recommendation_reason = "cautious guidance selected the least-hot returned route"
    alternatives = tuple(
        _route_option(
            item,
            recommended_id,
            route_metric,
            route_unit,
            heat_status,
            confidence,
            cautious,
            cautious_selected_route,
        )
        for item in alternatives_payload
    )
    fallback_reason = route_payload.get("fallback_reason")
    return RouteComparisonResult(
        alternatives=alternatives,
        recommended_id=recommended_id,
        reason=recommendation_reason,
        heat_status=heat_status,
        corridor_heat_value=_number(route_payload["corridor_heat_value"], "corridor_heat_value"),
        heat_metric=route_metric,
        heat_unit=route_unit,
        coverage=_number(route_payload["coverage"], "coverage"),
        confidence=confidence,
        comparison_scope="returned alternatives",
        provenance=route_provenance,
        fallback_reason=_string(fallback_reason, "fallback_reason")
        if fallback_reason is not None
        else None,
        heat_interpretation=classify_heat(
            _number(route_payload["corridor_heat_value"], "corridor_heat_value"),
            metric=route_metric,
            cautious=cautious,
        ),
    )


def _route_option(
    value: object,
    recommended_id: str,
    metric: HeatMetricName,
    unit: str,
    status: HeatStatus,
    confidence: Confidence,
    cautious: bool,
    cautious_selected_route: bool,
) -> RouteOption:
    item = _mapping(value, "route alternative")
    identity = _string(item["identity"], "route identity")
    shade = item.get("modeled_shade_percent")
    geometry = _route_geometry(item.get("geometry"))
    return RouteOption(
        identity=identity,
        distance_m=_number(item["distance_m"], "distance_m"),
        duration_s=_number(item["duration_s"], "duration_s"),
        heat_value=_number(item["heat_value"], "heat_value"),
        heat_unit=unit,
        heat_metric=metric,
        heat_status=status,
        modeled_shade_percent=_number(shade, "modeled_shade_percent")
        if shade is not None
        else None,
        shade_confidence=(
            ShadeConfidence.SUFFICIENT
            if shade is not None and confidence is Confidence.SUFFICIENT
            else ShadeConfidence.INSUFFICIENT
            if shade is not None
            else None
        ),
        building_coverage=_number(item["building_coverage"], "building_coverage"),
        recommended=identity == recommended_id,
        recommendation_reason=_route_recommendation_reason(
            item,
            recommended=identity == recommended_id,
            confidence=confidence,
            cautious_selected_route=cautious_selected_route,
        ),
        shade_model_label="modeled shade estimate based on OSM building data"
        if shade is not None
        else None,
        heat_interpretation=classify_heat(
            _number(item["heat_value"], "heat_value"),
            metric=metric,
            cautious=cautious,
        ),
        geometry=geometry,
    )


def _route_recommendation_reason(
    item: Mapping[str, object],
    *,
    recommended: bool,
    confidence: Confidence,
    cautious_selected_route: bool,
) -> str | None:
    if recommended and confidence is Confidence.INSUFFICIENT:
        return "shortest-route fallback because route comparison confidence is insufficient"
    if recommended and cautious_selected_route:
        return "cautious guidance selected this returned route"
    reason = item.get("recommendation_reason")
    return _string(reason, "recommendation_reason") if reason is not None else None


def _cautious_route_id(
    alternatives: list[object],
    metric: HeatMetricName,
    values: tuple[float, ...],
    original_recommended_id: str,
) -> str:
    """Choose the least-hot returned route when cautious guidance is requested."""
    if not alternatives:
        raise ValueError("routes.alternatives must not be empty")
    ranked = min(
        enumerate(alternatives),
        key=lambda candidate: (
            classify_heat(values[candidate[0]], metric=metric, cautious=True).action_required,
            values[candidate[0]],
            _string(_mapping(candidate[1], "route alternative")["identity"], "route identity")
            != original_recommended_id,
            _number(_mapping(candidate[1], "route alternative")["distance_m"], "distance_m"),
        ),
    )
    return _string(_mapping(ranked[1], "route alternative")["identity"], "route identity")


def _cautious_hour(
    hourly: tuple[HourlyEntry, ...],
    metric: HeatMetricName,
    heat_index_by_hour: dict[int, float | None],
) -> int:
    """Prefer a period below the cautious action threshold, then the coolest one."""
    return min(
        hourly,
        key=lambda entry: _hour_policy_sort_key(entry, metric, heat_index_by_hour),
    ).hour


def _hour_policy_sort_key(
    entry: HourlyEntry,
    metric: HeatMetricName,
    heat_index_by_hour: dict[int, float | None],
) -> tuple[bool, float, int]:
    heat_index = heat_index_by_hour[entry.hour]
    selected_value = heat_index if heat_index is not None else entry.metric.value
    selected_metric = HeatMetricName.HEAT_INDEX_CELSIUS if heat_index is not None else metric
    interpretation = classify_heat(selected_value, metric=selected_metric, cautious=True)
    return interpretation.action_required, selected_value, entry.hour


def _provenance(section: Mapping[str, object], execution_mode: ExecutionMode) -> Provenance:
    raw = _mapping(section.get("provenance"), "provenance")
    return Provenance(
        source=execution_mode.value,
        data_date=_string(raw["data_date"], "data_date"),
        confidence=Confidence(raw["confidence"]),
        coverage=_number(raw["coverage"], "coverage") if raw.get("coverage") is not None else None,
        retrieved_at=_string(raw["retrieved_at"], "retrieved_at"),
        transformation_version=_string(raw["transformation_version"], "transformation_version"),
        provider=_string(raw["provider"], "provider"),
        activity_id=_string(raw["activity_id"], "activity_id")
        if raw.get("activity_id") is not None
        else None,
        response_status=_string(raw["response_status"], "response_status"),
        request_configuration=dict(_mapping(raw["request_configuration"], "request_configuration")),
        fresh=_boolean(raw["fresh"], "fresh"),
        note=_string(raw["note"], "note") if raw.get("note") is not None else None,
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _require_section_reason(name: str, value: object, reasons: dict[str, str]) -> None:
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


def _optional_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    return _number(value, field)


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


def _route_geometry(value: object) -> tuple[tuple[float, float], ...]:
    coordinates = _mapping(value, "route geometry").get("coordinates")
    if not isinstance(coordinates, list):
        raise ValueError("route geometry coordinates must be a list")
    return tuple(
        (
            _number(_mapping(point, "route geometry point").get("longitude"), "longitude")
            if isinstance(point, Mapping)
            else _number(point[0], "longitude"),
            _number(_mapping(point, "route geometry point").get("latitude"), "latitude")
            if isinstance(point, Mapping)
            else _number(point[1], "latitude"),
        )
        for point in coordinates
        if isinstance(point, (list, tuple, Mapping))
    )


def _request_identity(request: TripAnalysisRequest) -> str:
    return f"{request.mode.value}:{request.date}:{request.start_hour}-{request.end_hour}"


def _fixture_matches(scenario: Mapping[str, object], request: TripAnalysisRequest) -> bool:
    origin = _mapping(scenario.get("origin"), "scenario origin")
    destination = _mapping(scenario.get("destination"), "scenario destination")
    return (
        scenario.get("mode", TripMode.CURATED.value) == request.mode.value
        and scenario.get("cautious", False) is request.cautious
        and _string(scenario.get("landmark_name"), "scenario landmark_name")
        == request.landmark_name
        and _string(scenario.get("district_name"), "scenario district_name")
        == request.district_name
        and _string(scenario.get("date"), "scenario date") == request.date
        and _integer(scenario.get("start_hour"), "scenario start_hour") == request.start_hour
        and _integer(scenario.get("end_hour"), "scenario end_hour") == request.end_hour
        and math.isclose(
            _number(origin.get("latitude"), "origin latitude"),
            request.origin.latitude,
            abs_tol=1e-7,
            rel_tol=0,
        )
        and math.isclose(
            _number(origin.get("longitude"), "origin longitude"),
            request.origin.longitude,
            abs_tol=1e-7,
            rel_tol=0,
        )
        and math.isclose(
            _number(destination.get("latitude"), "destination latitude"),
            request.destination.latitude,
            abs_tol=1e-7,
            rel_tol=0,
        )
        and math.isclose(
            _number(destination.get("longitude"), "destination longitude"),
            request.destination.longitude,
            abs_tol=1e-7,
            rel_tol=0,
        )
    )


def _request_from_fixture_identity(scenario: Mapping[str, object]) -> TripAnalysisRequest:
    allowed = {
        "mode",
        "landmark_name",
        "district_name",
        "date",
        "start_hour",
        "end_hour",
        "cautious",
        "origin",
        "destination",
        "generator_version",
        "generator_metadata",
        "hotel_aoi",
        "building_aoi",
        "route_heat_aoi",
    }
    unknown = set(scenario) - allowed
    if unknown:
        raise ValueError(f"trip fixture request identity contains unknown keys: {sorted(unknown)}")
    origin = _mapping(scenario.get("origin"), "scenario origin")
    destination = _mapping(scenario.get("destination"), "scenario destination")
    place_fields = {
        "application_id",
        "name",
        "latitude",
        "longitude",
        "osm_identity",
        "coordinate_meaning",
        "authority",
    }
    if not {"latitude", "longitude"} <= set(origin) or set(origin) - place_fields:
        raise ValueError("trip fixture origin identity has invalid fields")
    if not {"latitude", "longitude"} <= set(destination) or set(destination) - place_fields:
        raise ValueError("trip fixture destination identity has invalid fields")
    return TripAnalysisRequest(
        mode=TripMode(_string(scenario.get("mode"), "scenario mode")),
        origin=Coordinates(
            _number(origin.get("latitude"), "origin latitude"),
            _number(origin.get("longitude"), "origin longitude"),
        ),
        destination=Coordinates(
            _number(destination.get("latitude"), "destination latitude"),
            _number(destination.get("longitude"), "destination longitude"),
        ),
        landmark_name=_string(scenario.get("landmark_name"), "scenario landmark_name"),
        district_name=_string(scenario.get("district_name"), "scenario district_name"),
        date=_string(scenario.get("date"), "scenario date"),
        start_hour=_integer(scenario.get("start_hour"), "scenario start_hour"),
        end_hour=_integer(scenario.get("end_hour"), "scenario end_hour"),
        cautious=_boolean(scenario.get("cautious", False), "scenario cautious"),
    )
