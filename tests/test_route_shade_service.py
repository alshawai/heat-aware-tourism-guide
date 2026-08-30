"""Per-route shade coverage, height-quality fractions, and confidence thresholds."""

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.domain.contracts import Confidence, Provenance, RouteDecisionState
from app.domain.route_decision import RouteDecisionInput, decide_route_comparison
from app.domain.route_heat import RouteHeatEvidence
from app.domain.route_shade import RouteShadeEvidence, ShadeConfidence, solar_position
from app.domain.routing import ReturnedRoute, RouteGeometry, RouteSet
from app.services.building_execution import BuildingExecution
from app.services.route_shade import RouteShadeService

ENDPOINT = "https://overpass.example/api/interpreter"
INSTANT = datetime(2026, 8, 29, 10, 30, tzinfo=ZoneInfo("America/Chicago"))
SOLAR = solar_position(INSTANT, 29.4250, -98.4860)

# Mid-morning here the sun sits east-southeast, so shadows fall roughly 30 m west
# of a 30 m building. Both routes run north-south; buildings sit just east of one.
ROUTE_LON = -98.4860
FAR_ROUTE_LON = -98.4600
BUILDING_WEST = ROUTE_LON + 0.00015
BUILDING_EAST = ROUTE_LON + 0.00040

NEAR_ROUTE = RouteGeometry(((ROUTE_LON, 29.4230), (ROUTE_LON, 29.4270)))
FAR_ROUTE = RouteGeometry(((FAR_ROUTE_LON, 29.4230), (FAR_ROUTE_LON, 29.4270)))


def _routes(*geometries: RouteGeometry) -> RouteSet:
    return RouteSet(
        tuple(
            ReturnedRoute(f"route-{index}", 900.0 + index, 700.0 + index, geometry)
            for index, geometry in enumerate(geometries or (NEAR_ROUTE,), start=1)
        ),
        "fossgis-routed-foot",
    )


def _ring(west: float, south: float, east: float, north: float) -> list[dict[str, float]]:
    corners = [(west, south), (east, south), (east, north), (west, north), (west, south)]
    return [{"lat": latitude, "lon": longitude} for longitude, latitude in corners]


def _building(identity: int, south: float, span: float, **tags: str) -> dict[str, Any]:
    """One building just east of the near route, `span` degrees of latitude tall."""
    return {
        "type": "way",
        "id": identity,
        "tags": tags,
        "geometry": _ring(BUILDING_WEST, south, BUILDING_EAST, south + span),
    }


def _payload(*elements: Any) -> dict[str, Any]:
    return {
        "version": 0.6,
        "osm3s": {"timestamp_osm_base": "2026-08-24T18:03:11Z"},
        "elements": list(elements),
    }


def _all_evidence(
    payload: dict[str, Any], *, routes: RouteSet | None = None, **overrides: Any
) -> dict[str, RouteShadeEvidence]:
    service = RouteShadeService(
        BuildingExecution(
            live_loader=lambda aoi: payload,
            endpoint=ENDPOINT,
            search_distance_m=250.0,
            clock=lambda: datetime(2026, 8, 30, 9, tzinfo=timezone.utc),
        ),
        **overrides,
    )
    return dict(service.load(routes or _routes(), SOLAR, INSTANT).evidence)


def _evidence(payload: dict[str, Any], **overrides: Any) -> RouteShadeEvidence:
    return _all_evidence(payload, **overrides)["route-1"]


def test_area_fractions_split_explicit_inferred_and_unknown_by_area() -> None:
    payload = _payload(
        _building(1, 29.4235, 0.0004, building="office", height="30"),
        _building(2, 29.4242, 0.0004, building="yes", **{"building:levels": "9"}),
        _building(3, 29.4249, 0.0004, building="yes"),
    )

    evidence = _evidence(payload)

    assert evidence.explicit_area_fraction == pytest.approx(1 / 3, abs=1e-3)
    assert evidence.inferred_levels_area_fraction == pytest.approx(1 / 3, abs=1e-3)
    assert evidence.unknown_area_fraction == pytest.approx(1 / 3, abs=1e-3)
    assert evidence.building_coverage == pytest.approx(2 / 3, abs=1e-3)
    counts = (evidence.explicit_count, evidence.inferred_levels_count, evidence.unknown_count)
    assert counts == (1, 1, 1)
    # Two thirds of the known-height area falls short of the 70% minimum.
    assert evidence.confidence is ShadeConfidence.INSUFFICIENT
    # The unknown-height building shades nothing, but it still occupies its area.
    assert 0 < evidence.modeled_shade_percent < 100


def test_zero_relevant_building_area_is_insufficient_with_no_modeled_shade() -> None:
    # The only building stands beside the far route, kilometres from this corridor.
    payload = _payload(
        {
            "type": "way",
            "id": 10,
            "tags": {"building": "yes", "height": "30"},
            "geometry": _ring(FAR_ROUTE_LON + 0.00015, 29.4235, FAR_ROUTE_LON + 0.0004, 29.4239),
        }
    )

    evidence = _evidence(payload)

    assert evidence.modeled_shade_percent == 0.0
    assert evidence.building_coverage == 0.0
    assert evidence.explicit_area_fraction == 0.0
    assert evidence.unknown_area_fraction == 0.0
    assert (evidence.explicit_count, evidence.unknown_count) == (0, 0)
    assert evidence.confidence is ShadeConfidence.INSUFFICIENT


def test_malformed_geometry_forces_insufficient_confidence_despite_full_coverage() -> None:
    payload = _payload(
        _building(11, 29.4235, 0.0004, building="office", height="30"),
        # Three points that never close: a real building whose geometry is unusable.
        {
            "type": "way",
            "id": 12,
            "tags": {"building": "yes", "height": "24"},
            "geometry": _ring(BUILDING_WEST, 29.4245, BUILDING_EAST, 29.4249)[:3],
        },
    )

    evidence = _evidence(payload)

    assert evidence.building_coverage == pytest.approx(1.0)
    assert evidence.dropped_geometry_count == 1
    # Known heights alone cannot carry confidence while geometry is missing.
    assert evidence.confidence is ShadeConfidence.INSUFFICIENT


def test_coverage_at_the_minimum_is_sufficient_and_a_hair_below_it_is_not() -> None:
    # Equal-longitude rectangles: projected area follows their latitude heights, 7:3.
    payload = _payload(
        _building(21, 29.4235, 0.0007, building="office", height="30"),
        _building(22, 29.4245, 0.0003, building="yes"),
    )

    measured = _evidence(payload).building_coverage

    assert measured == pytest.approx(0.70, abs=1e-3)
    assert _evidence(payload, minimum_building_coverage=measured).confidence is (
        ShadeConfidence.SUFFICIENT
    )
    assert _evidence(payload, minimum_building_coverage=measured + 1e-9).confidence is (
        ShadeConfidence.INSUFFICIENT
    )


def test_relation_courtyards_and_building_parts_reach_route_evidence() -> None:
    def _relation(*members: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "relation",
            "id": 31,
            "tags": {"type": "multipolygon", "building": "hotel", "height": "40"},
            "members": list(members),
        }

    def _member(geometry: list[dict[str, float]], role: str) -> dict[str, Any]:
        return {"type": "way", "ref": 1, "role": role, "geometry": geometry}

    outer = _member(_ring(BUILDING_WEST, 29.4235, BUILDING_EAST + 0.0006, 29.4245), "outer")
    courtyard = _member(
        _ring(BUILDING_WEST + 0.0002, 29.4237, BUILDING_EAST + 0.0004, 29.4243), "inner"
    )
    parent = _building(32, 29.4255, 0.0004, building="yes", **{"building:levels": "9"})
    part = _building(33, 29.4256, 0.0002, height="60", **{"building:part": "yes"})

    evidence = _evidence(_payload(_relation(outer, courtyard), parent, part))

    # The relation and the part carry explicit heights; the parent way infers its own.
    assert (evidence.explicit_count, evidence.inferred_levels_count) == (2, 1)
    assert evidence.unknown_count == 0
    assert evidence.building_coverage == pytest.approx(1.0)
    assert evidence.dropped_geometry_count == 0
    solid = _evidence(_payload(_relation(outer), parent, part))
    # A courtyard is open sky: it can never add shade over the solid footprint.
    assert 0 < evidence.modeled_shade_percent <= solid.modeled_shade_percent


def test_each_route_gets_the_evidence_of_its_own_corridor() -> None:
    payload = _payload(_building(41, 29.4235, 0.0020, building="office", height="30"))

    evidence = _all_evidence(payload, routes=_routes(NEAR_ROUTE, FAR_ROUTE))

    assert evidence["route-1"].confidence is ShadeConfidence.SUFFICIENT
    assert evidence["route-1"].modeled_shade_percent > 0
    assert evidence["route-2"].confidence is ShadeConfidence.INSUFFICIENT
    assert evidence["route-2"].modeled_shade_percent == 0.0


def test_one_route_without_shade_evidence_blocks_any_recommendation() -> None:
    payload = _payload(_building(51, 29.4235, 0.0020, building="office", height="30"))
    routes = _routes(NEAR_ROUTE, FAR_ROUTE)
    provenance = Provenance(
        source="provider",
        data_date="2026-08-29",
        confidence=Confidence.SUFFICIENT,
        retrieved_at="2026-08-29T15:30:00+00:00",
        transformation_version="route-v1",
        provider="test",
        response_status="completed",
        request_configuration={},
        fresh=True,
    )

    result = decide_route_comparison(
        RouteDecisionInput(
            routes,
            None,
            tuple(RouteHeatEvidence(route.identity, 39.0, 0.8, True, 1) for route in routes.routes),
            shade_evidence=_all_evidence(payload, routes=routes),
        ),
        cautious=False,
        provenance=provenance,
        routing_provenance=provenance,
        heat_provenance=provenance,
    )

    assert result.decision_state is RouteDecisionState.INSUFFICIENT_SHADE_COMPARISON_REQUIRED
    assert result.recommended_id is None
    assert all(not route.recommended for route in result.alternatives)
