"""Public route-domain and trip-contract behavior for issue #18 phase 1."""

from dataclasses import replace

import pytest

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
from app.domain.routing import RouteGeometry, RouteRequest, ReturnedRoute, RouteSet
from app.domain.contracts import Coordinates


def _provenance(provider: str) -> Provenance:
    return Provenance(
        source="provider",
        data_date="2026-08-23",
        confidence=Confidence.SUFFICIENT,
        retrieved_at="2026-08-23T12:00:00+00:00",
        transformation_version="route-contract-v1",
        provider=provider,
        response_status="completed",
        request_configuration={},
        fresh=True,
    )


def _geometry(offset: float = 0.0) -> RouteGeometry:
    return RouteGeometry(
        coordinates=(
            (-98.4864 + offset, 29.4246),
            (-98.4858 + offset, 29.4258),
        )
    )


def _option(
    identity: str,
    distance_m: float,
    *,
    heat_value: float | None = 31.0,
    recommended: bool = False,
) -> RouteOption:
    return RouteOption(
        identity=identity,
        distance_m=distance_m,
        duration_s=distance_m / 1.25,
        heat_value=heat_value,
        heat_unit="C",
        heat_metric=HeatMetricName.TCM,
        heat_status=(HeatStatus.NOT_ELEVATED if heat_value is not None else None),
        modeled_shade_percent=None,
        shade_confidence=None,
        building_coverage=0.0,
        recommended=recommended,
        recommendation_reason="shortest returned route under mild heat"
        if recommended
        else None,
        shade_model_label=None,
        geometry=_geometry().coordinates,
        heat_coverage=1.0 if heat_value is not None else None,
        heat_source=(RouteHeatSource.LANDMARK_REUSE if heat_value is not None else None),
    )


def _comparison(
    alternatives: tuple[RouteOption, ...],
    *,
    route_set_state: RouteSetState,
    decision_state: RouteDecisionState,
    recommended_id: str | None,
) -> RouteComparisonResult:
    values = [route.heat_value for route in alternatives if route.heat_value is not None]
    return RouteComparisonResult(
        alternatives=alternatives,
        recommended_id=recommended_id,
        reason="route heat decision",
        heat_status=(HeatStatus.NOT_ELEVATED if values else None),
        corridor_heat_value=max(values) if values else None,
        heat_metric=HeatMetricName.TCM,
        heat_unit="C",
        coverage=min((route.heat_coverage or 0.0) for route in alternatives)
        if alternatives
        else 0.0,
        confidence=Confidence.SUFFICIENT if values else Confidence.INSUFFICIENT,
        comparison_scope="returned alternatives",
        provenance=_provenance("osrm_and_fortyguard"),
        fallback_reason=None if values else "route heat unavailable",
        route_set_state=route_set_state,
        decision_state=decision_state,
        lowest_heat_route_id=(min(alternatives, key=lambda route: route.heat_value or 0).identity)
        if values
        else None,
        routing_provenance=_provenance("osrm"),
        heat_provenance=_provenance("fortyguard") if values else None,
    )


def test_route_request_and_returned_routes_keep_full_geometry() -> None:
    request = RouteRequest(
        origin=Coordinates(29.4246, -98.4864),
        destination=Coordinates(29.4258, -98.4858),
        profile="foot",
        alternatives=True,
        overview="full",
        geometries="geojson",
        steps=False,
        provider_instance="fossgis-routed-foot",
        request_version="osrm-route-v1",
    )
    routes = RouteSet(
        routes=(ReturnedRoute("route-1", 132.0, 105.0, _geometry()),),
        provider_instance=request.provider_instance,
    )

    assert routes.routes[0].geometry.geojson == {
        "type": "LineString",
        "coordinates": [[-98.4864, 29.4246], [-98.4858, 29.4258]],
    }
    assert routes.shortest.identity == "route-1"
    assert routes.any_longer_than(1500.0) is False


def test_route_geometry_rejects_invalid_or_repeated_wgs84_points() -> None:
    with pytest.raises(ValueError, match="distinct"):
        RouteGeometry(((-98.4864, 29.4246), (-98.4864, 29.4246)))
    with pytest.raises(ValueError, match="WGS84"):
        RouteGeometry(((-181.0, 29.4246), (-98.4858, 29.4258)))


def test_mild_heat_requires_the_shortest_returned_route_recommendation() -> None:
    short = _option("short", 100.0, recommended=True)
    long = _option("long", 150.0)
    result = _comparison(
        (short, long),
        route_set_state=RouteSetState.ALTERNATIVES_RETURNED,
        decision_state=RouteDecisionState.MILD_SHORTEST_RECOMMENDED,
        recommended_id="short",
    )
    assert result.recommended_id == "short"

    with pytest.raises(ValueError, match="shortest"):
        _comparison(
            (replace(short, recommended=False, recommendation_reason=None), replace(long, recommended=True, recommendation_reason="wrong")),
            route_set_state=RouteSetState.ALTERNATIVES_RETURNED,
            decision_state=RouteDecisionState.MILD_SHORTEST_RECOMMENDED,
            recommended_id="long",
        )


def test_elevated_heat_records_lowest_heat_evidence_without_recommendation() -> None:
    warmer = replace(
        _option("warmer", 100.0, heat_value=38.0),
        heat_status=HeatStatus.ELEVATED,
    )
    cooler = replace(
        _option("cooler", 125.0, heat_value=36.0),
        heat_status=HeatStatus.ELEVATED,
    )
    result = _comparison(
        (warmer, cooler),
        route_set_state=RouteSetState.ALTERNATIVES_RETURNED,
        decision_state=RouteDecisionState.SHADE_REQUIRED,
        recommended_id=None,
    )

    assert result.lowest_heat_route_id == "cooler"
    assert result.recommended_id is None
    assert not any(route.recommended for route in result.alternatives)


def test_single_route_state_is_usable_but_cannot_claim_alternatives() -> None:
    only = _option("only", 100.0, recommended=True)
    result = _comparison(
        (only,),
        route_set_state=RouteSetState.SINGLE_ROUTE,
        decision_state=RouteDecisionState.MILD_SHORTEST_RECOMMENDED,
        recommended_id="only",
    )
    assert result.route_set_state is RouteSetState.SINGLE_ROUTE

    with pytest.raises(ValueError, match="single route"):
        _comparison(
            (only, replace(only, identity="other", recommended=False, recommendation_reason=None)),
            route_set_state=RouteSetState.SINGLE_ROUTE,
            decision_state=RouteDecisionState.MILD_SHORTEST_RECOMMENDED,
            recommended_id="only",
        )


def test_heat_unavailable_routes_carry_no_heat_or_recommendation() -> None:
    route = _option("route-1", 1800.0, heat_value=None)
    result = _comparison(
        (route,),
        route_set_state=RouteSetState.SINGLE_ROUTE,
        decision_state=RouteDecisionState.HEAT_UNAVAILABLE,
        recommended_id=None,
    )
    assert result.heat_provenance is None
    assert result.alternatives[0].heat_interpretation is None

    with pytest.raises(ValueError, match="heat unavailable"):
        _comparison(
            (replace(route, heat_value=35.0),),
            route_set_state=RouteSetState.SINGLE_ROUTE,
            decision_state=RouteDecisionState.HEAT_UNAVAILABLE,
            recommended_id=None,
        )
