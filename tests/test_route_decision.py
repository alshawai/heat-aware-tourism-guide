"""Heat-gated route decision behavior for issue #18 phase 5."""

from app.domain.contracts import (
    Confidence,
    Provenance,
    RouteDecisionState,
    RouteHeatSource,
    RouteSetState,
)
from app.domain.route_decision import RouteDecisionInput, decide_route_comparison
from app.domain.route_heat import RouteHeatEvidence
from app.domain.route_shade import RouteShadeEvidence, ShadeConfidence
from app.domain.routing import RouteGeometry, RouteSet, ReturnedRoute


def _routes() -> RouteSet:
    return RouteSet(
        (
            ReturnedRoute(
                "route-1", 900.0, 700.0, RouteGeometry(((-98.49, 29.42), (-98.48, 29.43)))
            ),
            ReturnedRoute(
                "route-2", 1200.0, 900.0, RouteGeometry(((-98.49, 29.42), (-98.479, 29.429)))
            ),
        ),
        "fossgis-routed-foot",
    )


def _provenance(source: str = "provider") -> Provenance:
    return Provenance(
        source=source,
        data_date="2026-08-23",
        confidence=Confidence.SUFFICIENT,
        retrieved_at="2026-08-23T16:00:00+00:00",
        transformation_version="route-v1",
        provider="test",
        response_status="ok",
        request_configuration={"request": "test"},
        fresh=True,
    )


def _evidence(*values: float | None, coverage: float = 0.8) -> tuple[RouteHeatEvidence, ...]:
    return tuple(
        RouteHeatEvidence(
            route.identity, value, coverage, value is not None, 1 if value is not None else 0
        )
        for route, value in zip(_routes().routes, values, strict=True)
    )


def _shade(percent: float, coverage: float, *, sufficient: bool = True) -> RouteShadeEvidence:
    return RouteShadeEvidence(
        modeled_shade_percent=percent,
        building_coverage=coverage,
        confidence=(ShadeConfidence.SUFFICIENT if sufficient else ShadeConfidence.INSUFFICIENT),
        explicit_area_fraction=coverage,
        inferred_levels_area_fraction=0.0,
        unknown_area_fraction=1.0 - coverage,
        explicit_count=1,
        inferred_levels_count=0,
        unknown_count=0 if coverage == 1 else 1,
        dropped_geometry_count=0,
    )


def test_mild_heat_recommends_only_the_shortest_returned_route() -> None:
    result = decide_route_comparison(
        RouteDecisionInput(_routes(), landmark_tcm_celsius=32.0),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=None,
    )
    assert result.decision_state is RouteDecisionState.MILD_SHORTEST_RECOMMENDED
    assert result.recommended_id == "route-1"
    assert all(route.heat_source is RouteHeatSource.LANDMARK_REUSE for route in result.alternatives)


def test_elevated_heat_exposes_lowest_heat_as_evidence_without_recommending_it() -> None:
    result = decide_route_comparison(
        RouteDecisionInput(
            _routes(), landmark_tcm_celsius=None, heat_evidence=_evidence(32.0, 39.0)
        ),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=_provenance(),
    )
    assert result.decision_state is RouteDecisionState.SHADE_REQUIRED
    assert result.recommended_id is None
    assert result.lowest_heat_route_id == "route-1"
    assert not any(route.recommended for route in result.alternatives)
    assert all(
        route.heat_source is RouteHeatSource.SHARED_CORRIDOR for route in result.alternatives
    )


def test_cautious_policy_can_gate_a_route_that_standard_policy_would_allow() -> None:
    evidence = _evidence(34.0, 34.0)
    standard = decide_route_comparison(
        RouteDecisionInput(_routes(), None, evidence),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=_provenance(),
    )
    cautious = decide_route_comparison(
        RouteDecisionInput(_routes(), None, evidence),
        cautious=True,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=_provenance(),
    )
    assert standard.decision_state is RouteDecisionState.MILD_SHORTEST_RECOMMENDED
    assert cautious.decision_state is RouteDecisionState.SHADE_REQUIRED


def test_heat_unavailable_preserves_routes_without_landmark_substitution() -> None:
    result = decide_route_comparison(
        RouteDecisionInput(_routes(), landmark_tcm_celsius=31.0, shared_heat_unavailable=True),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=None,
    )
    assert result.decision_state is RouteDecisionState.HEAT_UNAVAILABLE
    assert result.recommended_id is None
    assert all(route.heat_value is None for route in result.alternatives)


def test_no_suitable_route_is_explicit_when_any_route_lacks_sufficient_evidence() -> None:
    result = decide_route_comparison(
        RouteDecisionInput(_routes(), None, _evidence(35.0, None)),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=_provenance(),
    )
    assert result.decision_state is RouteDecisionState.NO_SUITABLE_RETURNED_ROUTE
    assert result.recommended_id is None
    assert result.fallback_reason is not None


def test_single_returned_route_is_usable_with_limited_comparison_state() -> None:
    route_set = RouteSet((_routes().routes[0],), "fossgis-routed-foot")
    result = decide_route_comparison(
        RouteDecisionInput(route_set, landmark_tcm_celsius=32.0),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=None,
    )
    assert result.route_set_state is RouteSetState.SINGLE_ROUTE
    assert result.recommended_id == "route-1"


def test_sufficient_shade_recommends_shadiest_with_distance_tie_break() -> None:
    result = decide_route_comparison(
        RouteDecisionInput(
            _routes(),
            None,
            _evidence(39.0, 38.0),
            shade_evidence={
                "route-1": _shade(60.0, 0.8),
                "route-2": _shade(60.0, 0.9),
            },
        ),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=_provenance(),
    )

    assert result.decision_state is RouteDecisionState.SHADE_SHADIEST_RECOMMENDED
    assert result.recommended_id == "route-1"
    assert result.alternatives[0].recommendation_reason == (
        "highest modeled shade among returned routes"
    )
    assert all(
        route.shade_confidence is ShadeConfidence.SUFFICIENT for route in result.alternatives
    )


def test_any_weak_shade_evidence_preserves_metrics_without_recommendation() -> None:
    result = decide_route_comparison(
        RouteDecisionInput(
            _routes(),
            None,
            _evidence(39.0, 38.0),
            shade_evidence={
                "route-1": _shade(70.0, 0.8),
                "route-2": _shade(45.0, 0.69, sufficient=False),
            },
        ),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=_provenance(),
    )

    assert result.decision_state is RouteDecisionState.INSUFFICIENT_SHADE_COMPARISON_REQUIRED
    assert result.recommended_id is None
    assert [route.modeled_shade_percent for route in result.alternatives] == [70.0, 45.0]
    assert [route.shade_confidence for route in result.alternatives] == [
        ShadeConfidence.SUFFICIENT,
        ShadeConfidence.INSUFFICIENT,
    ]


def test_nighttime_recommends_coolest_then_distance_and_marks_shade_not_applicable() -> None:
    result = decide_route_comparison(
        RouteDecisionInput(_routes(), None, _evidence(39.0, 39.0), nighttime=True),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=_provenance(),
    )

    assert result.decision_state is RouteDecisionState.NIGHTTIME_COOLEST_RECOMMENDED
    assert result.recommended_id == "route-1"
    assert [route.modeled_shade_percent for route in result.alternatives] == [0.0, 0.0]
    assert all(
        route.shade_confidence is ShadeConfidence.NOT_APPLICABLE for route in result.alternatives
    )


def test_single_elevated_route_with_sufficient_shade_uses_only_route_state() -> None:
    route_set = RouteSet((_routes().routes[0],), "fossgis-routed-foot")
    result = decide_route_comparison(
        RouteDecisionInput(
            route_set,
            landmark_tcm_celsius=39.0,
            shade_evidence={"route-1": _shade(35.0, 0.7)},
        ),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=None,
    )

    assert result.decision_state is RouteDecisionState.SHADE_ONLY_ROUTE_RECOMMENDED
    assert result.recommended_id == "route-1"


def test_zero_returned_routes_is_explicit() -> None:
    result = decide_route_comparison(
        RouteDecisionInput(None, None),
        cautious=False,
        provenance=_provenance(),
        routing_provenance=_provenance(),
        heat_provenance=None,
    )
    assert result.decision_state is RouteDecisionState.NO_SUITABLE_RETURNED_ROUTE
    assert result.alternatives == ()
