from app.domain.trip import (
    HotelCandidate,
    HotelRanker,
    RouteCandidate,
    RouteComparator,
)
import pytest
from app.integrations.fortyguard.contracts import AnalyticType, AreaHeatmapRequest


def test_hotel_ranker_exposes_components_percentiles_and_ties() -> None:
    ranked = HotelRanker().rank(
        [
            HotelCandidate("a", {"night": 30, "hot_hours": 5, "persistence": 2, "day": 32}),
            HotelCandidate("b", {"night": 30, "hot_hours": 5, "persistence": 2, "day": 32}),
            HotelCandidate("c", {"night": 35, "hot_hours": 9, "persistence": 5, "day": 38}),
        ]
    )
    assert [hotel.identity for hotel in ranked] == ["a", "b", "c"]
    assert ranked[0].tie_group == ranked[1].tie_group
    assert ranked[0].percentile == ranked[1].percentile
    assert ranked[0].components["night"] == 30


def test_hotel_ranker_rejects_invalid_weights_and_components() -> None:
    candidate = HotelCandidate(
        "a", {"night": 30, "hot_hours": 5, "persistence": 2, "day": float("nan")}
    )
    with pytest.raises(ValueError, match="components"):
        HotelRanker().rank([candidate])
    with pytest.raises(ValueError, match="weights"):
        HotelRanker().rank(
            [HotelCandidate("a", {"night": 30, "hot_hours": 5, "persistence": 2, "day": 32})],
            {"night": -0.35, "hot_hours": 0.25, "persistence": 0.2, "day": 0.9},
        )


def test_route_comparator_fetches_routes_once_and_uses_shortest_when_heat_is_low() -> None:
    calls = 0

    def routes() -> list[RouteCandidate]:
        nonlocal calls
        calls += 1
        return [RouteCandidate("short", 1000, 600), RouteCandidate("long", 1300, 700)]

    result = RouteComparator(representative_threshold_m=1500).compare(
        routes, heat_value=30, heat_threshold=35, shade=lambda route: 90
    )
    assert calls == 1
    assert result.recommended_id == "short"
    assert result.shade_was_computed is False


def test_route_comparator_uses_maximum_heat_and_weak_coverage_has_no_fallback() -> None:
    result = RouteComparator().compare(
        lambda: [RouteCandidate("short", 1000, 600), RouteCandidate("shady", 1200, 700)],
        heat_value=38,
        heat_values=[34, 38],
        heat_threshold=35,
        shade=lambda route: 80 if route.identity == "shady" else 20,
        building_coverage=0.5,
    )
    assert result.corridor_heat_value == 38
    assert result.recommended_id is None
    assert result.reason == "insufficient shade coverage; traveler comparison required"
    assert result.shade_was_computed is True


def test_route_comparator_uses_landmark_heat_for_short_and_corridor_max_for_long() -> None:
    comparator = RouteComparator(representative_threshold_m=1500)
    short = comparator.compare(
        lambda: [RouteCandidate("short", 1000, 600)],
        heat_value=30,
        heat_values=[40],
        heat_threshold=35,
        shade=lambda route: 50,
    )
    long = comparator.compare(
        lambda: [RouteCandidate("long", 1600, 900)],
        heat_value=30,
        heat_values=[34, 40],
        heat_threshold=35,
        shade=lambda route: 50,
    )
    assert short.corridor_heat_value == 30
    assert short.shade_was_computed is False
    assert long.corridor_heat_value == 40
    assert long.shade_was_computed is True


def test_area_request_supports_district_and_corridor_properties_without_sample_geometry() -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-98.50, 29.42], [-98.49, 29.42], [-98.49, 29.43], [-98.50, 29.42]]],
    }
    request = AreaHeatmapRequest(
        geometry=geometry,
        analytic_types=(AnalyticType.TCM, AnalyticType.EXCEEDANCE),
        context="district",
        unit="C",
        unit_source="explicit",
    )
    assert request.to_payload()["geometry"] == geometry
    assert request.to_payload()["analytic_types"] == ["tcm", "exceedance"]
    assert request.to_payload()["unit_source"] == "explicit"
