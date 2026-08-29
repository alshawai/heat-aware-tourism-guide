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
