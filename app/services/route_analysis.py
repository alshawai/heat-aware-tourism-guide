"""Trip-level route acquisition, heat evidence, and decision orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime

from shapely.geometry import shape

from app.domain.contracts import (
    BestTimeResult,
    Confidence,
    Provenance,
    RouteComparisonResult,
    TripAnalysisRequest,
)
from app.domain.route_decision import RouteDecisionInput, decide_route_comparison
from app.domain.route_heat import (
    SharedRouteHeatRequest,
    aggregate_shared_route_heat,
    build_shared_route_aoi,
)
from app.domain.routing import RouteRequest
from app.integrations.fortyguard.contracts import (
    AnalyticType,
    HeatmapRequest,
    HeatmapResult,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.errors import ProviderError
from app.integrations.fortyguard.live import LiveHeatmapPayload
from app.services.routing import RouteExecution, RouteOutcome, RouteUnavailable, route_request_payload


class SharedRouteHeatUnavailable(RuntimeError):
    """The shared corridor activity could not provide normalized heat evidence."""


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
            unavailable_provenance = _unavailable_routing_provenance(request, route_request, self.clock)
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
            return decide_route_comparison(
                RouteDecisionInput(
                    route_set=outcome.routes,
                    landmark_tcm_celsius=best_time.recommended_hour_tcm_celsius,
                ),
                cautious=request.cautious,
                provenance=_decision_provenance(routing_provenance, heat_provenance),
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
        return decide_route_comparison(
            RouteDecisionInput(
                route_set=outcome.routes,
                landmark_tcm_celsius=None,
                heat_evidence=evidence,
            ),
            cautious=request.cautious,
            provenance=_decision_provenance(routing_provenance, heat_provenance),
            routing_provenance=routing_provenance,
            heat_provenance=heat_provenance,
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
