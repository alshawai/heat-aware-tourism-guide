"""Validation tests for the shared trip-analysis contracts.

Covers valid construction, incomplete fields, malformed payloads, and
unavailable/error states as required by Issue #9.
"""

import pytest

from app.contracts import (
    Confidence,
    Coordinates,
    ExecutionMode,
    HeatStatus,
    HeatMetricName,
    HourlyEntry,
    Metric,
    MetricLabel,
    Provenance,
    RankedHotel,
    ResultState,
    RouteComparisonResult,
    RouteOption,
    BestTimeResult,
    HotelCandidateData,
    HotelRankingResult,
    RouteCandidateData,
    TripAnalysisRequest,
    TripAnalysisInputs,
    TripAnalysisResponse,
    TripMode,
    UnavailableResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_hotel_candidate(identity: str = "hotel-a") -> HotelCandidateData:
    return HotelCandidateData(
        identity=identity,
        components={"night": 30, "hot_hours": 5, "persistence": 2, "day": 32},
    )


def _valid_route_candidate(identity: str = "route-a") -> RouteCandidateData:
    return RouteCandidateData(identity=identity, distance_m=1000, duration_s=600)


def _valid_route_option(identity: str = "route-a", *, recommended: bool = False) -> RouteOption:
    return RouteOption(
        identity=identity,
        distance_m=1000,
        duration_s=600,
        heat_value=34,
        heat_metric=HeatMetricName.TCM,
        heat_status=HeatStatus.ELEVATED,
        modeled_shade_percent=65 if recommended else None,
        shade_confidence=Confidence.SUFFICIENT if recommended else None,
        building_coverage=0.9,
        recommended=recommended,
        recommendation_reason="highest modeled shade" if recommended else None,
        shade_model_label=(
            "modeled shade estimate based on OSM building data" if recommended else None
        ),
    )


def _valid_request(**overrides: object) -> TripAnalysisRequest:
    defaults: dict[str, object] = {
        "mode": TripMode.CURATED,
        "origin": Coordinates(29.42, -98.49),
        "destination": Coordinates(29.43, -98.48),
        "landmark_name": "The Alamo",
        "district_name": "Downtown San Antonio",
        "date": "2026-08-23",
        "hour": 14,
        "cautious": False,
    }
    defaults.update(overrides)
    return TripAnalysisRequest(**defaults)  # type: ignore[arg-type]


def _valid_provenance() -> Provenance:
    return Provenance(source="fixture", data_date="2026-08-23", confidence=Confidence.SUFFICIENT, coverage=0.9)


def _valid_hourly() -> tuple[HourlyEntry, ...]:
    return tuple(
        HourlyEntry(hour=h, metric=Metric(value=30 + h * 0.5, unit="C", label=MetricLabel.PROVIDER_TCM, is_actual_heat_index=False))
        for h in range(24)
    )


def _valid_best_time() -> BestTimeResult:
    return BestTimeResult(
        hourly=_valid_hourly(),
        recommendation_hour=6,
        recommendation_reason="coolest available period",
        metric_label=MetricLabel.PROVIDER_TCM,
        provenance=_valid_provenance(),
    )


def _valid_ranked_hotels() -> HotelRankingResult:
    return HotelRankingResult(
        ranked=(
            RankedHotel(identity="a", components={"night": 30, "hot_hours": 5, "persistence": 2, "day": 32}, score=18.5, percentile=100, tie_group=0),
            RankedHotel(identity="b", components={"night": 36, "hot_hours": 9, "persistence": 5, "day": 38}, score=24.8, percentile=0, tie_group=1),
        ),
        weights={"night": 0.35, "hot_hours": 0.25, "persistence": 0.20, "day": 0.20},
        usable_count=2,
        discovered_count=3,
        provenance=_valid_provenance(),
    )


def _valid_route_comparison() -> RouteComparisonResult:
    return RouteComparisonResult(
        alternatives=(
            _valid_route_option("short"),
            _valid_route_option("shady", recommended=True),
        ),
        recommended_id="shady",
        reason="highest modeled shade among returned routes",
        heat_status=HeatStatus.ELEVATED,
        corridor_heat_value=38.0,
        heat_metric=HeatMetricName.TCM,
        coverage=0.9,
        confidence=Confidence.SUFFICIENT,
        comparison_scope="returned alternatives",
        provenance=_valid_provenance(),
    )


def _valid_response(**overrides: object) -> TripAnalysisResponse:
    defaults: dict[str, object] = {
        "request_identity": "req-1",
        "mode": TripMode.CURATED,
        "execution_mode": ExecutionMode.FIXTURE,
        "state": ResultState.SUCCESS,
        "best_time": _valid_best_time(),
        "hotels": _valid_ranked_hotels(),
        "routes": _valid_route_comparison(),
    }
    defaults.update(overrides)
    return TripAnalysisResponse(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Valid construction
# ---------------------------------------------------------------------------

class TestValidConstruction:
    def test_request_with_all_fields(self) -> None:
        request = _valid_request()
        assert request.landmark_name == "The Alamo"
        assert request.mode is TripMode.CURATED

    def test_response_success_with_all_sections(self) -> None:
        response = _valid_response()
        assert response.state is ResultState.SUCCESS
        assert response.best_time is not None
        assert response.hotels is not None
        assert response.routes is not None
        assert response.unavailable is None

    def test_coordinates_valid(self) -> None:
        coords = Coordinates(29.42, -98.49)
        assert coords.latitude == 29.42

    def test_provenance_with_coverage(self) -> None:
        prov = Provenance(source="fixture", data_date="2026-08-23", confidence=Confidence.SUFFICIENT, coverage=0.85, note="strong data")
        assert prov.coverage == 0.85
        assert prov.note == "strong data"

    def test_metric_labels_distinguish_provider_from_noaa(self) -> None:
        provider = Metric(value=35.0, unit="C", label=MetricLabel.PROVIDER_TCM, is_actual_heat_index=False)
        noaa = Metric(value=38.0, unit="C", label=MetricLabel.NOAA_HEAT_INDEX, is_actual_heat_index=True)
        assert provider.label is MetricLabel.PROVIDER_TCM
        assert noaa.label is MetricLabel.NOAA_HEAT_INDEX

    def test_ranked_hotel_percentile_and_ties(self) -> None:
        hotels = _valid_ranked_hotels()
        assert hotels.ranked[0].tie_group != hotels.ranked[1].tie_group
        assert hotels.ranked[0].percentile == 100

    def test_route_comparison_includes_all_alternatives(self) -> None:
        rc = _valid_route_comparison()
        assert len(rc.alternatives) == 2
        identities = {r.identity for r in rc.alternatives}
        assert "short" in identities
        assert "shady" in identities

    def test_unavailable_result(self) -> None:
        unavail = UnavailableResult(reason="no fixture for this scenario", recoverable=True)
        assert unavail.recoverable is True

    def test_hourly_entry_valid_range(self) -> None:
        entry = HourlyEntry(hour=0, metric=Metric(value=28.0, unit="C", label=MetricLabel.PROVIDER_TCM, is_actual_heat_index=False))
        assert entry.hour == 0
        last = HourlyEntry(hour=23, metric=Metric(value=35.0, unit="C", label=MetricLabel.PROVIDER_TCM, is_actual_heat_index=False))
        assert last.hour == 23


# ---------------------------------------------------------------------------
# Incomplete / missing required fields
# ---------------------------------------------------------------------------

class TestIncompleteFields:
    def test_request_missing_landmark_rejected(self) -> None:
        with pytest.raises(ValueError, match="landmark_name"):
            _valid_request(landmark_name="")

    def test_request_missing_date_rejected(self) -> None:
        with pytest.raises(ValueError, match="date"):
            _valid_request(date="")

    def test_request_hour_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="hour"):
            _valid_request(hour=24)

    def test_response_success_missing_best_time(self) -> None:
        with pytest.raises(ValueError, match="best_time"):
            _valid_response(best_time=None)

    def test_response_success_missing_hotels(self) -> None:
        with pytest.raises(ValueError, match="hotels"):
            _valid_response(hotels=None)

    def test_response_success_missing_routes(self) -> None:
        with pytest.raises(ValueError, match="routes"):
            _valid_response(routes=None)

    def test_unavailable_state_without_detail(self) -> None:
        with pytest.raises(ValueError, match="unavailable"):
            TripAnalysisResponse(
                request_identity="req-1",
                mode=TripMode.CURATED,
                execution_mode=ExecutionMode.FIXTURE,
                state=ResultState.UNAVAILABLE,
            )

    def test_error_state_without_detail(self) -> None:
        with pytest.raises(ValueError, match="unavailable"):
            TripAnalysisResponse(
                request_identity="req-1",
                mode=TripMode.CURATED,
                execution_mode=ExecutionMode.FIXTURE,
                state=ResultState.ERROR,
            )


# ---------------------------------------------------------------------------
# Malformed payloads
# ---------------------------------------------------------------------------

class TestMalformedPayloads:
    def test_coordinates_invalid_latitude(self) -> None:
        with pytest.raises(ValueError, match="coordinates"):
            Coordinates(91.0, -98.49)

    def test_coordinates_invalid_longitude(self) -> None:
        with pytest.raises(ValueError, match="coordinates"):
            Coordinates(29.42, -181.0)

    def test_coordinates_nan(self) -> None:
        with pytest.raises(ValueError, match="coordinates"):
            Coordinates(float("nan"), -98.49)

    def test_coordinates_infinite(self) -> None:
        with pytest.raises(ValueError, match="coordinates"):
            Coordinates(float("inf"), -98.49)

    def test_provenance_empty_source(self) -> None:
        with pytest.raises(ValueError, match="source"):
            Provenance(source="", data_date="2026-08-23", confidence=Confidence.SUFFICIENT)

    def test_provenance_empty_data_date(self) -> None:
        with pytest.raises(ValueError, match="data_date"):
            Provenance(source="fixture", data_date="", confidence=Confidence.SUFFICIENT)

    def test_provenance_coverage_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="coverage"):
            Provenance(source="fixture", data_date="2026-08-23", confidence=Confidence.SUFFICIENT, coverage=1.5)

    def test_metric_nan_value(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            Metric(value=float("nan"), unit="C", label=MetricLabel.PROVIDER_TCM, is_actual_heat_index=False)

    def test_metric_empty_unit(self) -> None:
        with pytest.raises(ValueError, match="unit"):
            Metric(value=35.0, unit="", label=MetricLabel.PROVIDER_TCM, is_actual_heat_index=False)

    def test_hourly_entry_invalid_hour(self) -> None:
        with pytest.raises(ValueError, match="hour"):
            HourlyEntry(hour=24, metric=Metric(value=30.0, unit="C", label=MetricLabel.PROVIDER_TCM, is_actual_heat_index=False))

    def test_hotel_candidate_wrong_components(self) -> None:
        with pytest.raises(ValueError, match="components"):
            HotelCandidateData(identity="a", components={"night": 30, "hot_hours": 5})

    def test_hotel_candidate_nan_component(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            HotelCandidateData(identity="a", components={"night": float("nan"), "hot_hours": 5, "persistence": 2, "day": 32})

    def test_hotel_candidate_bool_component(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            HotelCandidateData(identity="a", components={"night": True, "hot_hours": 5, "persistence": 2, "day": 32})

    def test_route_candidate_negative_distance(self) -> None:
        with pytest.raises(ValueError, match="distance_m"):
            RouteCandidateData(identity="a", distance_m=-100, duration_s=600)

    def test_route_candidate_zero_duration(self) -> None:
        with pytest.raises(ValueError, match="duration_s"):
            RouteCandidateData(identity="a", distance_m=1000, duration_s=0)

    def test_ranked_hotel_nan_score(self) -> None:
        with pytest.raises(ValueError, match="score"):
            RankedHotel(identity="a", components={"night": 30, "hot_hours": 5, "persistence": 2, "day": 32}, score=float("nan"), percentile=50, tie_group=0)

    def test_hotel_ranking_weights_not_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match="weights"):
            HotelRankingResult(
                ranked=(RankedHotel(identity="a", components={"night": 30, "hot_hours": 5, "persistence": 2, "day": 32}, score=18.5, percentile=100, tie_group=0),),
                weights={"night": 0.5, "hot_hours": 0.5, "persistence": 0.5, "day": 0.0},
                usable_count=1,
                discovered_count=1,
                provenance=_valid_provenance(),
            )

    def test_hotel_ranking_usable_exceeds_discovered(self) -> None:
        with pytest.raises(ValueError, match="usable_count"):
            HotelRankingResult(
                ranked=(),
                weights={"night": 0.35, "hot_hours": 0.25, "persistence": 0.20, "day": 0.20},
                usable_count=5,
                discovered_count=3,
                provenance=_valid_provenance(),
            )

    def test_route_option_negative_heat(self) -> None:
        with pytest.raises(ValueError, match="heat_value"):
            RouteOption(
                identity="a", distance_m=1000, duration_s=600, heat_value=float("-inf"),
                heat_metric=HeatMetricName.TCM, heat_status=HeatStatus.ELEVATED,
                modeled_shade_percent=None, shade_confidence=None, building_coverage=0.9,
                recommended=False, recommendation_reason=None, shade_model_label=None,
            )

    def test_route_comparison_empty_alternatives(self) -> None:
        with pytest.raises(ValueError, match="route alternative"):
            RouteComparisonResult(
                alternatives=(),
                recommended_id="a",
                reason="test",
                heat_status=HeatStatus.NOT_ELEVATED,
                corridor_heat_value=30.0,
                heat_metric=HeatMetricName.TCM,
                coverage=0.9,
                confidence=Confidence.SUFFICIENT,
                comparison_scope="returned alternatives",
                provenance=_valid_provenance(),
            )

    def test_route_comparison_recommendation_not_in_alternatives(self) -> None:
        with pytest.raises(ValueError, match="recommended_id"):
            RouteComparisonResult(
                alternatives=(_valid_route_option("a"),),
                recommended_id="nonexistent",
                reason="test",
                heat_status=HeatStatus.NOT_ELEVATED,
                corridor_heat_value=30.0,
                heat_metric=HeatMetricName.TCM,
                coverage=0.9,
                confidence=Confidence.SUFFICIENT,
                comparison_scope="returned alternatives",
                provenance=_valid_provenance(),
            )

    def test_route_comparison_coverage_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="coverage"):
            RouteComparisonResult(
                alternatives=(_valid_route_option("a", recommended=True),),
                recommended_id="a",
                reason="test",
                heat_status=HeatStatus.NOT_ELEVATED,
                corridor_heat_value=30.0,
                heat_metric=HeatMetricName.TCM,
                coverage=2.0,
                confidence=Confidence.SUFFICIENT,
                comparison_scope="returned alternatives",
                provenance=_valid_provenance(),
            )

    def test_request_building_coverage_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="building_coverage"):
            TripAnalysisInputs(
                "tcm", 38, 35, (), 1.5,
                (_valid_hotel_candidate(),), (_valid_route_candidate(),), {"route-a": 50},
            )

    def test_request_heat_value_nan(self) -> None:
        with pytest.raises(ValueError, match="heat_value"):
            TripAnalysisInputs(
                "tcm", float("nan"), 35, (), 0.9,
                (_valid_hotel_candidate(),), (_valid_route_candidate(),), {"route-a": 50},
            )

    def test_request_heat_threshold_infinite(self) -> None:
        with pytest.raises(ValueError, match="heat_threshold"):
            TripAnalysisInputs(
                "tcm", 38, float("inf"), (), 0.9,
                (_valid_hotel_candidate(),), (_valid_route_candidate(),), {"route-a": 50},
            )


# ---------------------------------------------------------------------------
# Unavailable / error states
# ---------------------------------------------------------------------------

class TestUnavailableStates:
    def test_unavailable_response_no_result_data(self) -> None:
        response = _valid_response(
            state=ResultState.UNAVAILABLE,
            best_time=None,
            hotels=None,
            routes=None,
            unavailable=UnavailableResult(reason="no fixture available", recoverable=True),
        )
        assert response.state is ResultState.UNAVAILABLE
        assert response.best_time is None
        assert response.unavailable is not None
        assert response.unavailable.recoverable is True

    def test_error_response_no_result_data(self) -> None:
        response = _valid_response(
            state=ResultState.ERROR,
            best_time=None,
            hotels=None,
            routes=None,
            unavailable=UnavailableResult(reason="provider timeout", recoverable=False),
        )
        assert response.state is ResultState.ERROR
        assert response.unavailable is not None
        assert response.unavailable.recoverable is False

    def test_degraded_response_with_partial_results(self) -> None:
        response = _valid_response(
            state=ResultState.DEGRADED,
            hotels=None,
            unavailable=UnavailableResult(reason="hotel discovery failed", recoverable=True),
        )
        assert response.state is ResultState.DEGRADED
        assert response.best_time is not None
        assert response.hotels is None
        assert response.routes is not None

    def test_unavailable_rejected_with_success_state(self) -> None:
        with pytest.raises(ValueError, match="must not include unavailable"):
            _valid_response(
                unavailable=UnavailableResult(reason="should not exist", recoverable=True),
            )

    def test_success_rejected_with_unavailable_state(self) -> None:
        with pytest.raises(ValueError, match="requires unavailable"):
            TripAnalysisResponse(
                request_identity="req-1",
                mode=TripMode.CURATED,
                execution_mode=ExecutionMode.FIXTURE,
                state=ResultState.UNAVAILABLE,
            )

    def test_degraded_requires_at_least_one_result(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            TripAnalysisResponse(
                request_identity="req-1",
                mode=TripMode.CURATED,
                execution_mode=ExecutionMode.FIXTURE,
                state=ResultState.DEGRADED,
                best_time=None,
                hotels=None,
                routes=None,
            )


# ---------------------------------------------------------------------------
# API integration via contract validation
# ---------------------------------------------------------------------------

class TestApiContractValidation:
    """Validates that _parse_trip_request correctly rejects malformed bodies."""

    def test_missing_origin_coordinates_rejected(self) -> None:
        from app.api import _parse_trip_request
        with pytest.raises(ValueError, match="origin_latitude"):
            _parse_trip_request({
                "destination_latitude": 29.43,
                "destination_longitude": -98.48,
                "landmark_name": "The Alamo",
                "district_name": "Downtown",
                "date": "2026-08-23",
                "hour": 14,
            })

    def test_full_body_with_defaults_accepted(self) -> None:
        from app.api import _parse_trip_request
        request = _parse_trip_request({
            "origin_latitude": 29.42,
            "origin_longitude": -98.49,
            "destination_latitude": 29.43,
            "destination_longitude": -98.48,
            "landmark_name": "The Alamo",
            "district_name": "Downtown",
            "date": "2026-08-23",
            "hour": 12,
            "mode": "curated",
        })
        assert request.cautious is False
        assert request.hour == 12

    def test_full_contract_body_accepted(self) -> None:
        from app.api import _parse_trip_request
        request = _parse_trip_request({
            "origin_latitude": 29.421,
            "origin_longitude": -98.491,
            "destination_latitude": 29.425,
            "destination_longitude": -98.484,
            "mode": "exploratory",
            "landmark_name": "The Alamo",
            "district_name": "Downtown San Antonio",
            "date": "2026-08-23",
            "hour": 14,
            "cautious": True,
        })
        assert request.mode is TripMode.EXPLORATORY
        assert request.landmark_name == "The Alamo"
        assert request.cautious is True
        assert request.hour == 14

    def test_string_cautious_value_rejected(self) -> None:
        from app.api import _parse_trip_request

        with pytest.raises(ValueError, match="cautious must be a boolean"):
            _parse_trip_request({
                "origin_latitude": 29.42,
                "origin_longitude": -98.49,
                "destination_latitude": 29.43,
                "destination_longitude": -98.48,
                "mode": "curated",
                "landmark_name": "The Alamo",
                "district_name": "Downtown",
                "date": "2026-08-23",
                "hour": 14,
                "cautious": "false",
            })
