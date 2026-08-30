"""Trip-level route acquisition, heat evidence, and decision orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import cast

from shapely.geometry import MultiLineString, shape

from app.domain.contracts import (
    BestTimeResult,
    Confidence,
    Provenance,
    RouteComparisonResult,
    RouteDecisionState,
    TemporalEvidenceState,
    TripAnalysisRequest,
)
from app.domain.provenance import Transformation
from app.domain.route_decision import RouteDecisionInput, decide_route_comparison
from app.domain.route_heat import (
    SharedRouteHeatRequest,
    aggregate_shared_route_heat,
    build_shared_route_aoi,
)
from app.domain.route_shade import (
    SOLAR_MODEL_IDENTITY,
    RouteShadeEvidence,
    SolarPosition,
    solar_position,
)
from app.domain.routing import RouteRequest, RouteSet
from app.integrations.fortyguard.contracts import (
    AnalyticType,
    HeatmapRequest,
    HeatmapResult,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.errors import ProviderError
from app.integrations.fortyguard.live import LiveHeatmapPayload
from app.services.route_shade import RouteShadeOutcome
from app.services.routing import (
    RouteExecution,
    RouteOutcome,
    RouteUnavailable,
    route_request_payload,
)


class SharedRouteHeatUnavailable(RuntimeError):
    """The shared corridor activity could not provide normalized heat evidence."""


ShadeEvidence = Mapping[str, RouteShadeEvidence]
ShadeEvidenceLoader = Callable[[RouteSet, SolarPosition, datetime], RouteShadeOutcome]
SolarLocator = Callable[[datetime, float, float], SolarPosition]

BUILDING_TRANSFORMATION_VERSION = "route-shade-building-normalization-v1"
"""Overpass building normalization: geometry parsing, height classification, part merging."""

SOLAR_TRANSFORMATIONS: tuple[Transformation, ...] = (
    Transformation(name="local_instant_to_utc", version=1),
    Transformation(name="apparent_solar_position", version=1),
)
"""The named steps between the local recommendation time and the modeled sun position."""


class RouteAnalysisService:
    """Own one OSRM execution and the selected route-heat branch."""

    def __init__(
        self,
        route_execution: RouteExecution,
        *,
        profile: str,
        alternatives: bool,
        overview: str,
        geometries: str,
        steps: bool,
        provider_instance: str,
        request_version: str,
        representative_distance_m: float,
        minimum_heat_coverage: float,
        corridor_buffer_m: float,
        corridor_granularity: int,
        shared_heat_loader: Callable[
            [SharedRouteHeatRequest], Mapping[str, object] | LiveHeatmapPayload
        ]
        | None = None,
        shade_evidence_loader: ShadeEvidenceLoader | None = None,
        solar_locator: SolarLocator = solar_position,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self.route_execution = route_execution
        self.profile = profile
        self.alternatives = alternatives
        self.overview = overview
        self.geometries = geometries
        self.steps = steps
        self.provider_instance = provider_instance
        self.request_version = request_version
        self.representative_distance_m = representative_distance_m
        self.minimum_heat_coverage = minimum_heat_coverage
        self.corridor_buffer_m = corridor_buffer_m
        self.corridor_granularity = corridor_granularity
        self.shared_heat_loader = shared_heat_loader
        self.shade_evidence_loader = shade_evidence_loader
        self.solar_locator = solar_locator
        self.clock = clock

    def analyze(
        self,
        request: TripAnalysisRequest,
        best_time: BestTimeResult,
    ) -> RouteComparisonResult:
        route_request = RouteRequest(
            origin=request.origin,
            destination=request.destination,
            profile=self.profile,
            alternatives=self.alternatives,
            overview=self.overview,
            geometries=self.geometries,
            steps=self.steps,
            provider_instance=self.provider_instance,
            request_version=self.request_version,
        )
        try:
            outcome = self.route_execution.run(route_request, live=True)
        except RouteUnavailable:
            unavailable_provenance = _unavailable_routing_provenance(
                request, route_request, self.clock
            )
            return decide_route_comparison(
                RouteDecisionInput(route_set=None, landmark_tcm_celsius=None),
                cautious=request.cautious,
                provenance=unavailable_provenance,
                routing_provenance=unavailable_provenance,
                heat_provenance=None,
            )
        routing_provenance = _routing_provenance(outcome, route_request)

        if not outcome.routes.any_longer_than(self.representative_distance_m):
            heat_provenance = _landmark_heat_provenance(best_time.provenance)
            return self._decide(
                RouteDecisionInput(
                    route_set=outcome.routes,
                    landmark_tcm_celsius=best_time.recommended_hour_tcm_celsius,
                ),
                request=request,
                best_time=best_time,
                routing_provenance=routing_provenance,
                heat_provenance=heat_provenance,
            )

        try:
            heatmap = self._load_shared_heat(request, best_time, outcome)
        except SharedRouteHeatUnavailable:
            return decide_route_comparison(
                RouteDecisionInput(
                    route_set=outcome.routes,
                    landmark_tcm_celsius=None,
                    shared_heat_unavailable=True,
                ),
                cautious=request.cautious,
                provenance=_decision_provenance(routing_provenance, None),
                routing_provenance=routing_provenance,
                heat_provenance=None,
            )

        try:
            evidence = aggregate_shared_route_heat(
                outcome.routes,
                heatmap,
                buffer_m=self.corridor_buffer_m,
                minimum_coverage=self.minimum_heat_coverage,
                selected_hour=best_time.recommendation_hour,
            )
        except ValueError:
            return decide_route_comparison(
                RouteDecisionInput(
                    route_set=outcome.routes,
                    landmark_tcm_celsius=None,
                    shared_heat_unavailable=True,
                ),
                cautious=request.cautious,
                provenance=_decision_provenance(routing_provenance, None),
                routing_provenance=routing_provenance,
                heat_provenance=None,
            )
        heat_provenance = _shared_heat_provenance(heatmap)
        return self._decide(
            RouteDecisionInput(
                route_set=outcome.routes,
                landmark_tcm_celsius=None,
                heat_evidence=evidence,
            ),
            request=request,
            best_time=best_time,
            routing_provenance=routing_provenance,
            heat_provenance=heat_provenance,
        )

    def _decide(
        self,
        decision: RouteDecisionInput,
        *,
        request: TripAnalysisRequest,
        best_time: BestTimeResult,
        routing_provenance: Provenance,
        heat_provenance: Provenance,
    ) -> RouteComparisonResult:
        provenance = _decision_provenance(routing_provenance, heat_provenance)
        preliminary = decide_route_comparison(
            decision,
            cautious=request.cautious,
            provenance=provenance,
            routing_provenance=routing_provenance,
            heat_provenance=heat_provenance,
        )
        if (
            preliminary.decision_state is not RouteDecisionState.SHADE_REQUIRED
            or self.shade_evidence_loader is None
            or decision.route_set is None
        ):
            return preliminary
        if (
            best_time.temporal_evidence is not TemporalEvidenceState.EXACT
            or best_time.recommendation_time is None
        ):
            return decide_route_comparison(
                RouteDecisionInput(
                    decision.route_set,
                    decision.landmark_tcm_celsius,
                    decision.heat_evidence,
                    shade_evidence={},
                ),
                cautious=request.cautious,
                provenance=provenance,
                routing_provenance=routing_provenance,
                heat_provenance=heat_provenance,
            )

        instant = best_time.recommendation_time
        route_geometry = MultiLineString(
            [route.geometry.coordinates for route in decision.route_set.routes]
        )
        centroid = route_geometry.centroid
        solar = self.solar_locator(instant, centroid.y, centroid.x)
        solar_provenance = _solar_provenance(
            solar, instant, centroid.y, centroid.x, clock=self.clock
        )
        if solar.elevation_degrees <= 0:
            return decide_route_comparison(
                RouteDecisionInput(
                    decision.route_set,
                    decision.landmark_tcm_celsius,
                    decision.heat_evidence,
                    nighttime=True,
                ),
                cautious=request.cautious,
                provenance=provenance,
                routing_provenance=routing_provenance,
                heat_provenance=heat_provenance,
                solar_provenance=solar_provenance,
            )

        try:
            shade = self.shade_evidence_loader(decision.route_set, solar, instant)
        except (ConnectionError, OSError, RuntimeError, TimeoutError, ValueError):
            shade = None
        return decide_route_comparison(
            RouteDecisionInput(
                decision.route_set,
                decision.landmark_tcm_celsius,
                decision.heat_evidence,
                shade_evidence={} if shade is None else shade.evidence,
            ),
            cautious=request.cautious,
            provenance=provenance,
            routing_provenance=routing_provenance,
            heat_provenance=heat_provenance,
            building_provenance=(
                None if shade is None else _building_provenance(shade, clock=self.clock)
            ),
            solar_provenance=solar_provenance,
        )

    def _load_shared_heat(
        self,
        request: TripAnalysisRequest,
        best_time: BestTimeResult,
        route_outcome: RouteOutcome,
    ) -> HeatmapResult:
        if self.shared_heat_loader is None:
            raise SharedRouteHeatUnavailable("shared route heat execution is not configured")
        analysis_date = date.fromisoformat(request.date)
        shared_request = SharedRouteHeatRequest(
            geometry=build_shared_route_aoi(route_outcome.routes, buffer_m=self.corridor_buffer_m),
            start_date=analysis_date,
            hour=best_time.recommendation_hour,
            forecast=analysis_date >= date.today(),
            granularity=self.corridor_granularity,
            buffer_m=self.corridor_buffer_m,
            provider_instance="fortyguard",
            request_version="shared-route-heat-v1",
        )
        try:
            loaded = self.shared_heat_loader(shared_request)
            payload = loaded.payload if isinstance(loaded, LiveHeatmapPayload) else loaded
            activity_id = loaded.activity_id if isinstance(loaded, LiveHeatmapPayload) else None
            activity = loaded.activity if isinstance(loaded, LiveHeatmapPayload) else None
            transformations = (
                loaded.transformations if isinstance(loaded, LiveHeatmapPayload) else ()
            )
            centroid = shape(dict(shared_request.geometry)).centroid
            normalization_request = HeatmapRequest(
                analytic_type=AnalyticType.TCM,
                latitude=centroid.y,
                longitude=centroid.x,
                start_date=shared_request.start_date,
                forecast=shared_request.forecast,
                granularity=shared_request.granularity,
                start_hour=shared_request.hour,
                end_hour=shared_request.hour + 1,
            )
            return normalize_heatmap_response(
                payload,
                request=normalization_request,
                retrieved_at=self.clock(),
                activity_id=activity_id,
                activity=activity,
                source="provider",
                data_date=shared_request.start_date.isoformat(),
                transformations=transformations,
            )
        except (ConnectionError, OSError, ProviderError, TimeoutError, ValueError) as error:
            raise SharedRouteHeatUnavailable("shared route heat activity is unavailable") from error


def _unavailable_routing_provenance(
    request: TripAnalysisRequest,
    route_request: RouteRequest,
    clock: Callable[[], datetime],
) -> Provenance:
    return Provenance(
        source="unavailable",
        data_date=request.date,
        confidence=Confidence.INSUFFICIENT,
        retrieved_at=clock().isoformat(),
        transformation_version="osrm-route-normalization-v1",
        provider="osrm",
        response_status="unavailable",
        request_configuration=route_request_payload(route_request),
        fresh=False,
        note="no provider, cache, or fixture supplied a normalized route set",
    )


def _routing_provenance(outcome: RouteOutcome, request: RouteRequest) -> Provenance:
    return Provenance(
        source=outcome.source,
        data_date=outcome.data_date,
        confidence=Confidence.SUFFICIENT,
        retrieved_at=outcome.retrieved_at.isoformat(),
        transformation_version="osrm-route-normalization-v1",
        provider="osrm",
        response_status="completed",
        request_configuration=route_request_payload(request),
        fresh=not outcome.stale,
    )


def _landmark_heat_provenance(provenance: Provenance) -> Provenance:
    configuration = dict(provenance.request_configuration)
    configuration["route_heat_source"] = "landmark_reuse"
    return Provenance(
        source=provenance.source,
        data_date=provenance.data_date,
        confidence=provenance.confidence,
        retrieved_at=provenance.retrieved_at,
        transformation_version="route-landmark-heat-reuse-v1",
        provider=provenance.provider,
        response_status=provenance.response_status,
        request_configuration=configuration,
        fresh=provenance.fresh,
        coverage=1.0,
        note=provenance.note,
        activity_id=provenance.activity_id,
    )


def _shared_heat_provenance(heatmap: HeatmapResult) -> Provenance:
    provider = heatmap.provenance
    return Provenance(
        source=provider.source,
        data_date=provider.data_date,
        confidence=Confidence.SUFFICIENT,
        retrieved_at=provider.retrieved_at.isoformat(),
        transformation_version="shared-route-heat-v1",
        provider="fortyguard",
        response_status="completed",
        request_configuration={
            "forecast": provider.forecast,
            "transformations": [
                {"name": item.name, "version": item.version} for item in provider.transformations
            ],
        },
        fresh=not provider.stale,
        activity_id=provider.activity_id,
    )


def _building_provenance(shade: RouteShadeOutcome, *, clock: Callable[[], datetime]) -> Provenance:
    """Where the shared OSM building geometry came from, under the identity requested."""
    coverage = min(
        (item.building_coverage for item in shade.evidence.values()),
        default=0.0,
    )
    configuration: dict[str, object] = dict(shade.request_identity)
    configuration["metres_per_level"] = shade.metres_per_level
    configuration["minimum_building_coverage"] = shade.minimum_building_coverage
    configuration["dropped_geometry_count"] = shade.dropped_geometry_count
    if shade.building is None:
        return Provenance(
            source="unavailable",
            data_date=clock().date().isoformat(),
            confidence=Confidence.INSUFFICIENT,
            retrieved_at=clock().isoformat(),
            transformation_version=BUILDING_TRANSFORMATION_VERSION,
            provider="overpass",
            response_status="unavailable",
            request_configuration=configuration,
            fresh=False,
            coverage=coverage,
            note=shade.unavailable_reason,
        )
    building = shade.building
    replayed_without_retrieval_time = building.retrieved_at is None
    return Provenance(
        source=building.source,
        data_date=building.data_date,
        confidence=Confidence.SUFFICIENT,
        retrieved_at=(
            clock() if building.retrieved_at is None else building.retrieved_at
        ).isoformat(),
        transformation_version=BUILDING_TRANSFORMATION_VERSION,
        provider="overpass",
        response_status="completed",
        request_configuration=configuration,
        fresh=not building.stale,
        coverage=coverage,
        note=(
            "replay time; the committed fixture records no provider retrieval time"
            if replayed_without_retrieval_time
            else building.reason
        ),
    )


def _solar_provenance(
    solar: SolarPosition,
    instant: datetime,
    latitude: float,
    longitude: float,
    *,
    clock: Callable[[], datetime],
) -> Provenance:
    """The exact instant, place, and model behind one solar position (ADR 0007)."""
    return Provenance(
        source="computed",
        data_date=instant.date().isoformat(),
        confidence=Confidence.SUFFICIENT,
        retrieved_at=clock().isoformat(),
        transformation_version="route-solar-position-v1",
        provider="astral",
        response_status="completed",
        request_configuration={
            "instant": instant.isoformat(),
            "timezone": _timezone_name(instant),
            "utc_offset_seconds": int(cast(timedelta, instant.utcoffset()).total_seconds()),
            "latitude": latitude,
            "longitude": longitude,
            "azimuth_degrees": solar.azimuth_degrees,
            "elevation_degrees": solar.elevation_degrees,
            "model_version": SOLAR_MODEL_IDENTITY,
            "transformations": [
                {"name": item.name, "version": item.version} for item in SOLAR_TRANSFORMATIONS
            ],
        },
        fresh=True,
    )


def _timezone_name(instant: datetime) -> str:
    """The named zone the instant carries, never a guess derived from its offset."""
    key = getattr(instant.tzinfo, "key", None)
    if isinstance(key, str) and key:
        return key
    return instant.tzname() or instant.strftime("%z")


def _decision_provenance(routing: Provenance, heat: Provenance | None) -> Provenance:
    return Provenance(
        source=heat.source if heat is not None else routing.source,
        data_date=heat.data_date if heat is not None else routing.data_date,
        confidence=heat.confidence if heat is not None else Confidence.INSUFFICIENT,
        retrieved_at=heat.retrieved_at if heat is not None else routing.retrieved_at,
        transformation_version="route-heat-gate-v1",
        provider="heat-aware-tourism-guide",
        response_status="completed" if heat is not None else "degraded",
        request_configuration={
            "routing_source": routing.source,
            "heat_source": heat.source if heat is not None else None,
        },
        fresh=routing.fresh and (heat.fresh if heat is not None else True),
    )
