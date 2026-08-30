"""Heat-gated route recommendation decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence, cast

from app.domain.contracts import (
    Confidence,
    HeatMetricName,
    HeatStatus,
    Provenance,
    RouteComparisonResult,
    RouteDecisionState,
    RouteHeatSource,
    RouteOption,
    RouteSetState,
)
from app.domain.route_shade import RouteShadeEvidence, ShadeConfidence
from app.domain.heat_policy import classify_heat
from app.domain.route_heat import RouteHeatEvidence
from app.domain.routing import ReturnedRoute, RouteSet


@dataclass(frozen=True)
class RouteDecisionInput:
    """Normalized route and heat evidence needed for product decisioning."""

    route_set: RouteSet | None
    landmark_tcm_celsius: float | None
    heat_evidence: tuple[RouteHeatEvidence, ...] | None = None
    shared_heat_unavailable: bool = False
    nighttime: bool = False
    shade_evidence: Mapping[str, RouteShadeEvidence] | None = None


def decide_route_comparison(
    decision: RouteDecisionInput,
    *,
    cautious: bool,
    provenance: Provenance,
    routing_provenance: Provenance,
    heat_provenance: Provenance | None,
) -> RouteComparisonResult:
    """Apply the route heat gate without fabricating routes or recommendations."""
    routes = () if decision.route_set is None else decision.route_set.routes
    if not routes:
        return _empty_result(
            decision,
            provenance=provenance,
            routing_provenance=routing_provenance,
            heat_provenance=heat_provenance,
            reason="OSRM returned no suitable pedestrian route",
        )

    route_set_state = (
        RouteSetState.SINGLE_ROUTE if len(routes) == 1 else RouteSetState.ALTERNATIVES_RETURNED
    )
    if decision.shared_heat_unavailable:
        options = _options(routes, values=[None] * len(routes), cautious=cautious)
        return _result(
            options,
            route_set_state=route_set_state,
            decision_state=RouteDecisionState.HEAT_UNAVAILABLE,
            reason="shared route heat is unavailable; returned routes are preserved without a recommendation",
            confidence=Confidence.INSUFFICIENT,
            provenance=provenance,
            routing_provenance=routing_provenance,
            heat_provenance=None,
            heat_status=None,
            corridor_heat_value=None,
            fallback_reason="shared corridor heat activity was unavailable",
            cautious=cautious,
        )

    values: list[float | None] = []
    coverages: list[float | None] = []
    if decision.heat_evidence is None:
        heat_provenance = heat_provenance or provenance
        values.extend([decision.landmark_tcm_celsius] * len(routes))
        coverages.extend([1.0] * len(routes))
        source = RouteHeatSource.LANDMARK_REUSE
    else:
        by_id = {item.route_id: item for item in decision.heat_evidence}
        values = []
        coverages = []
        for route in routes:
            evidence = by_id.get(route.identity)
            values.append(evidence.maximum_tcm_celsius if evidence is not None else None)
            coverages.append(evidence.coverage if evidence is not None else None)
        source = RouteHeatSource.SHARED_CORRIDOR

    if any(value is None for value in values):
        options = _options(
            routes, values=values, cautious=cautious, source=source, coverages=coverages
        )
        return _result(
            options,
            route_set_state=route_set_state,
            decision_state=RouteDecisionState.NO_SUITABLE_RETURNED_ROUTE,
            reason="no returned route has sufficient comparable heat evidence",
            confidence=Confidence.INSUFFICIENT,
            provenance=provenance,
            routing_provenance=routing_provenance,
            heat_provenance=heat_provenance,
            heat_status=None,
            corridor_heat_value=None,
            fallback_reason="route heat coverage was insufficient",
            cautious=cautious,
        )

    numeric_values = [cast(float, value) for value in values]
    interpretations = [
        classify_heat(value, metric=HeatMetricName.TCM, cautious=cautious)
        for value in numeric_values
    ]
    elevated = any(item.action_required for item in interpretations)
    lowest = routes[numeric_values.index(min(numeric_values))].identity
    if elevated:
        if decision.nighttime:
            heat_by_id = dict(
                zip((route.identity for route in routes), numeric_values, strict=True)
            )
            coolest = min(
                routes,
                key=lambda route: (
                    heat_by_id[route.identity],
                    route.distance_m,
                    route.identity,
                ),
            )
            nighttime_evidence = {
                route.identity: RouteShadeEvidence(
                    modeled_shade_percent=0.0,
                    building_coverage=0.0,
                    confidence=ShadeConfidence.NOT_APPLICABLE,
                    explicit_area_fraction=0.0,
                    inferred_levels_area_fraction=0.0,
                    unknown_area_fraction=0.0,
                    explicit_count=0,
                    inferred_levels_count=0,
                    unknown_count=0,
                    dropped_geometry_count=0,
                )
                for route in routes
            }
            options = _options(
                routes,
                values=numeric_values,
                cautious=cautious,
                source=source,
                coverages=coverages,
                recommended_id=coolest.identity,
                recommendation_reason="coolest returned route at night",
                shade_evidence=nighttime_evidence,
            )
            return _result(
                options,
                route_set_state=route_set_state,
                decision_state=RouteDecisionState.NIGHTTIME_COOLEST_RECOMMENDED,
                reason="sun is below the horizon; the coolest returned route is recommended",
                confidence=Confidence.SUFFICIENT,
                provenance=provenance,
                routing_provenance=routing_provenance,
                heat_provenance=heat_provenance,
                heat_status=HeatStatus.ELEVATED,
                corridor_heat_value=max(numeric_values),
                lowest_heat_route_id=lowest,
                cautious=cautious,
                recommended_id=coolest.identity,
            )
        shade_evidence = decision.shade_evidence
        if shade_evidence is not None:
            valid = all(
                route.identity in shade_evidence
                and shade_evidence[route.identity].confidence is ShadeConfidence.SUFFICIENT
                for route in routes
            )
            if valid:
                best = min(
                    routes,
                    key=lambda route: (
                        -shade_evidence[route.identity].modeled_shade_percent,
                        route.distance_m,
                        route.identity,
                    ),
                )
                options = _options(
                    routes,
                    values=numeric_values,
                    cautious=cautious,
                    source=source,
                    coverages=coverages,
                    recommended_id=best.identity,
                    recommendation_reason=(
                        "only returned route with sufficient modeled shade evidence"
                        if len(routes) == 1
                        else "highest modeled shade among returned routes"
                    ),
                    shade_evidence=shade_evidence,
                )
                state = (
                    RouteDecisionState.SHADE_ONLY_ROUTE_RECOMMENDED
                    if len(routes) == 1
                    else RouteDecisionState.SHADE_SHADIEST_RECOMMENDED
                )
                return _result(
                    options,
                    route_set_state=route_set_state,
                    decision_state=state,
                    reason="highest modeled OSM building shade among returned routes is recommended",
                    confidence=Confidence.SUFFICIENT,
                    provenance=provenance,
                    routing_provenance=routing_provenance,
                    heat_provenance=heat_provenance,
                    heat_status=HeatStatus.ELEVATED,
                    corridor_heat_value=max(numeric_values),
                    lowest_heat_route_id=lowest,
                    cautious=cautious,
                    recommended_id=best.identity,
                )
            options = _options(
                routes,
                values=numeric_values,
                cautious=cautious,
                source=source,
                coverages=coverages,
                shade_evidence=shade_evidence,
            )
            return _result(
                options,
                route_set_state=route_set_state,
                decision_state=RouteDecisionState.INSUFFICIENT_SHADE_COMPARISON_REQUIRED,
                reason="daytime building-shade evidence is insufficient; compare returned route trade-offs",
                confidence=Confidence.INSUFFICIENT,
                provenance=provenance,
                routing_provenance=routing_provenance,
                heat_provenance=heat_provenance,
                heat_status=HeatStatus.ELEVATED,
                corridor_heat_value=max(numeric_values),
                fallback_reason="building-height coverage or solar evidence was insufficient",
                lowest_heat_route_id=lowest,
                cautious=cautious,
            )
        options = _options(
            routes,
            values=numeric_values,
            cautious=cautious,
            source=source,
            coverages=coverages,
        )
        return _result(
            options,
            route_set_state=route_set_state,
            decision_state=RouteDecisionState.SHADE_REQUIRED,
            reason="at least one returned route requires heat mitigation; shade analysis is required",
            confidence=Confidence.SUFFICIENT,
            provenance=provenance,
            routing_provenance=routing_provenance,
            heat_provenance=heat_provenance,
            heat_status=HeatStatus.ELEVATED,
            corridor_heat_value=max(numeric_values),
            lowest_heat_route_id=lowest,
            cautious=cautious,
        )

    shortest = min(routes, key=lambda route: route.distance_m)
    options = _options(
        routes,
        values=numeric_values,
        cautious=cautious,
        source=source,
        coverages=coverages,
        recommended_id=shortest.identity,
    )
    return _result(
        options,
        route_set_state=route_set_state,
        decision_state=RouteDecisionState.MILD_SHORTEST_RECOMMENDED,
        reason="heat is mild across the comparable returned routes; the shortest route is recommended",
        confidence=Confidence.SUFFICIENT,
        provenance=provenance,
        routing_provenance=routing_provenance,
        heat_provenance=heat_provenance,
        heat_status=HeatStatus.NOT_ELEVATED,
        corridor_heat_value=max(numeric_values),
        lowest_heat_route_id=lowest,
        cautious=cautious,
        recommended_id=shortest.identity,
    )


def _options(
    routes: Sequence[ReturnedRoute],
    *,
    values: Sequence[float | None],
    cautious: bool,
    source: RouteHeatSource | None = None,
    coverages: Sequence[float | None] | None = None,
    recommended_id: str | None = None,
    recommendation_reason: str = "shortest returned route under mild heat",
    shade_evidence: Mapping[str, RouteShadeEvidence] | None = None,
) -> tuple[RouteOption, ...]:
    result: list[RouteOption] = []
    for index, (route, value) in enumerate(zip(routes, values, strict=True)):
        # RouteSet guarantees ReturnedRoute values; keeping this boundary typed
        # avoids leaking provider models into the decision contract.
        route_identity = route.identity
        interpretation = (
            classify_heat(value, metric=HeatMetricName.TCM, cautious=cautious)
            if value is not None
            else None
        )
        shade = (shade_evidence or {}).get(route_identity)
        result.append(
            RouteOption(
                identity=route_identity,
                distance_m=route.distance_m,
                duration_s=route.duration_s,
                heat_value=value,
                heat_unit="C",
                heat_metric=HeatMetricName.TCM,
                heat_status=(
                    HeatStatus.ELEVATED
                    if interpretation and interpretation.action_required
                    else HeatStatus.NOT_ELEVATED
                )
                if interpretation
                else None,
                modeled_shade_percent=shade.modeled_shade_percent if shade else None,
                shade_confidence=shade.confidence if shade else None,
                building_coverage=shade.building_coverage if shade else 0.0,
                recommended=route_identity == recommended_id,
                recommendation_reason=(
                    recommendation_reason if route_identity == recommended_id else None
                ),
                shade_model_label=(
                    "modeled OSM building-shade estimate, not measured real-world shade"
                    if shade
                    else None
                ),
                heat_interpretation=interpretation,
                geometry=route.geometry.coordinates,
                heat_coverage=coverages[index] if coverages is not None else None,
                heat_source=source,
                building_explicit_fraction=shade.explicit_area_fraction if shade else 0.0,
                building_inferred_levels_fraction=(
                    shade.inferred_levels_area_fraction if shade else 0.0
                ),
                building_unknown_fraction=shade.unknown_area_fraction if shade else 0.0,
                building_explicit_count=shade.explicit_count if shade else 0,
                building_inferred_levels_count=shade.inferred_levels_count if shade else 0,
                building_unknown_count=shade.unknown_count if shade else 0,
                dropped_building_geometry_count=(shade.dropped_geometry_count if shade else 0),
                shade_limitations=shade.limitations if shade else (),
            )
        )
    return tuple(result)


def _result(
    options: tuple[RouteOption, ...],
    *,
    route_set_state: RouteSetState,
    decision_state: RouteDecisionState,
    reason: str,
    confidence: Confidence,
    provenance: Provenance,
    routing_provenance: Provenance,
    heat_provenance: Provenance | None,
    heat_status: HeatStatus | None,
    corridor_heat_value: float | None,
    fallback_reason: str | None = None,
    lowest_heat_route_id: str | None = None,
    recommended_id: str | None = None,
    cautious: bool = False,
) -> RouteComparisonResult:
    coverage = min(
        (item.heat_coverage for item in options if item.heat_coverage is not None),
        default=1.0,
    )
    return RouteComparisonResult(
        alternatives=options,
        recommended_id=recommended_id,
        reason=reason,
        heat_status=heat_status,
        corridor_heat_value=corridor_heat_value,
        heat_metric=HeatMetricName.TCM,
        heat_unit="C",
        coverage=coverage,
        confidence=confidence,
        comparison_scope="returned alternatives",
        provenance=provenance,
        fallback_reason=fallback_reason,
        heat_interpretation=(
            classify_heat(
                corridor_heat_value,
                metric=HeatMetricName.TCM,
                cautious=cautious,
            )
            if corridor_heat_value is not None
            else None
        ),
        route_set_state=route_set_state,
        decision_state=decision_state,
        lowest_heat_route_id=lowest_heat_route_id,
        routing_provenance=routing_provenance,
        heat_provenance=heat_provenance,
    )


def _empty_result(
    decision: RouteDecisionInput,
    *,
    provenance: Provenance,
    routing_provenance: Provenance,
    heat_provenance: Provenance | None,
    reason: str,
) -> RouteComparisonResult:
    return _result(
        (),
        route_set_state=RouteSetState.NO_SUITABLE_RETURNED_ROUTE,
        decision_state=RouteDecisionState.NO_SUITABLE_RETURNED_ROUTE,
        reason=reason,
        confidence=Confidence.INSUFFICIENT,
        provenance=provenance,
        routing_provenance=routing_provenance,
        heat_provenance=heat_provenance,
        heat_status=None,
        corridor_heat_value=None,
        fallback_reason="OSRM returned no valid routes",
    )
