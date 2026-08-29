from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from app.domain.contracts import (
    Confidence,
    Coordinates,
    ExecutionMode,
    GuidancePolicy,
    HeatBand,
    ResultState,
    TripAnalysisRequest,
    TripMode,
)
from app.services.trip_adapters import (
    FixtureTripAnalysisAdapter,
    LiveTripAnalysisAdapter,
    normalize_trip_analysis,
)


def _request() -> TripAnalysisRequest:
    return TripAnalysisRequest(
        mode=TripMode.CURATED,
        origin=Coordinates(29.4245914, -98.4864288),
        destination=Coordinates(29.425833, -98.485833),
        landmark_name="The Alamo",
        district_name="Downtown San Antonio",
        date="2026-08-23",
        start_hour=8,
        end_hour=20,
        cautious=False,
    )


def _payload() -> dict[str, object]:
    with Path("fixtures/trip-analysis.json").open(encoding="utf-8") as fixture:
        payload = json.load(fixture)
    assert isinstance(payload, dict)
    return payload


def test_fixture_and_live_adapters_return_the_same_domain_shape() -> None:
    payload = _payload()
    fixture = FixtureTripAnalysisAdapter(Path("fixtures/trip-analysis.json")).analyze(
        _request(), ExecutionMode.FIXTURE
    )
    live = LiveTripAnalysisAdapter(lambda request: payload).analyze(_request(), ExecutionMode.LIVE)

    fixture_dict = asdict(fixture)
    live_dict = asdict(live)
    assert fixture_dict.keys() == live_dict.keys()
    assert fixture.best_time is not None and live.best_time is not None
    assert fixture.hotels is not None and live.hotels is not None
    assert fixture.routes is not None and live.routes is not None
    assert fixture.best_time.hourly == live.best_time.hourly
    assert fixture.hotels.ranked == live.hotels.ranked
    assert fixture.routes.alternatives == live.routes.alternatives
    assert fixture.execution_mode is ExecutionMode.FIXTURE
    assert live.execution_mode is ExecutionMode.LIVE
    assert fixture.best_time.provenance.source == "fixture"
    assert live.best_time.provenance.source == "live"


def test_canonical_menger_to_alamo_identity_matches_committed_fixture() -> None:
    request = _request()
    assert request.origin == Coordinates(29.4245914, -98.4864288)
    assert request.destination == Coordinates(29.425833, -98.485833)
    response = FixtureTripAnalysisAdapter(Path("fixtures/trip-analysis.json")).analyze(
        request, ExecutionMode.FIXTURE
    )

    assert response.state is ResultState.SUCCESS
    assert response.best_time is not None
    assert response.hotels is not None
    assert response.routes is not None


def test_route_distances_reflect_observed_canonical_osrm_response() -> None:
    response = FixtureTripAnalysisAdapter(Path("fixtures/trip-analysis.json")).analyze(
        _request(), ExecutionMode.FIXTURE
    )

    assert response.routes is not None
    by_identity = {route.identity: route for route in response.routes.alternatives}
    assert by_identity["short"].distance_m == 193.1
    assert by_identity["short"].duration_s == 154.7
    assert by_identity["shady"].distance_m == 245.0
    assert by_identity["shady"].duration_s == 196.0


def test_fixture_adapter_returns_unavailable_for_unmatched_window() -> None:
    response = FixtureTripAnalysisAdapter(Path("fixtures/trip-analysis.json")).analyze(
        replace(_request(), start_hour=9), ExecutionMode.FIXTURE
    )

    assert response.state is ResultState.UNAVAILABLE
    assert response.unavailable is not None
    assert response.unavailable.reason == "no matching fixture for the requested trip"


def test_live_adapter_rejects_non_object_payload() -> None:
    adapter = LiveTripAnalysisAdapter(lambda request: [])  # type: ignore[arg-type,return-value]
    with pytest.raises(ValueError, match="must return an object"):
        adapter.analyze(_request(), ExecutionMode.LIVE)


@pytest.mark.parametrize(  # type: ignore[misc]
    ("section", "field"),
    [
        ("best_time", "unit"),
        ("best_time", "recommendation_reason"),
        ("routes", "recommended_id"),
    ],
)
def test_serialized_required_strings_are_not_coerced(section: str, field: str) -> None:
    payload = _payload()
    section_payload = payload[section]
    assert isinstance(section_payload, dict)
    section_payload[field] = None

    with pytest.raises(ValueError, match="non-empty string"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)


def test_serialized_provenance_rejects_non_string_provider() -> None:
    payload = _payload()
    best_time = payload["best_time"]
    assert isinstance(best_time, dict)
    provenance = best_time["provenance"]
    assert isinstance(provenance, dict)
    provenance["provider"] = ["fortyguard"]

    with pytest.raises(ValueError, match="provider must be a non-empty string"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)


def test_missing_section_with_reason_returns_partial_degraded_response() -> None:
    payload = _payload()
    payload["hotels"] = None
    payload["degraded_reasons"] = {"hotels": "hotel discovery unavailable"}

    response = normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)

    assert response.state is ResultState.DEGRADED
    assert response.best_time is not None
    assert response.hotels is None
    assert response.routes is not None
    assert response.degraded_reasons == {"hotels": "hotel discovery unavailable"}


def test_missing_section_without_reason_is_rejected() -> None:
    payload = _payload()
    payload["hotels"] = None

    with pytest.raises(ValueError, match="missing hotels without degraded reason"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)


def test_degraded_reason_rejects_present_or_unknown_section() -> None:
    payload = _payload()
    payload["degraded_reasons"] = {"hotels": "failed", "unknown": "bad"}

    with pytest.raises(ValueError, match="unknown section"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)

    payload["degraded_reasons"] = {"hotels": "failed"}
    with pytest.raises(ValueError, match="match unavailable or limited sections"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)


def test_adapter_owned_unavailable_payload_has_no_empty_success() -> None:
    response = normalize_trip_analysis(
        {"unavailable": "no matching fixture"},
        _request(),
        ExecutionMode.FIXTURE,
    )

    assert response.state is ResultState.UNAVAILABLE
    assert response.best_time is None
    assert response.hotels is None
    assert response.routes is None
    assert response.unavailable is not None


def test_unavailable_payload_rejects_contradictory_result_data() -> None:
    payload = _payload()
    payload["unavailable"] = "provider failed"

    with pytest.raises(ValueError, match="must not include result data"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)


def test_route_corridor_heat_unit_is_explicit_and_validated() -> None:
    payload = _payload()
    routes = payload["routes"]
    assert isinstance(routes, dict)
    routes["heat_unit"] = ""

    with pytest.raises(ValueError, match="heat_unit"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)


def test_cautious_request_records_one_band_earlier_policy_for_each_heat_section() -> None:
    payload = _payload()
    response = normalize_trip_analysis(
        payload,
        replace(_request(), cautious=True),
        ExecutionMode.FIXTURE,
    )

    assert response.best_time is not None
    assert response.routes is not None
    best_policy = response.best_time.heat_interpretation
    route_policy = response.routes.heat_interpretation
    assert best_policy is not None
    assert route_policy is not None
    assert best_policy.guidance_policy is GuidancePolicy.CAUTIOUS
    assert best_policy.policy_applied == "cautious_guidance_one_band_earlier"
    assert best_policy.band is HeatBand.PROVIDER_LOWER
    assert route_policy.band is HeatBand.PROVIDER_HIGHER
    assert response.routes.recommended_id == "shady"


def test_cautious_request_changes_route_action_to_the_least_hot_returned_route() -> None:
    payload = _payload()
    routes = payload["routes"]
    assert isinstance(routes, dict)
    routes["recommended_id"] = "short"
    routes["reason"] = "shortest returned route"
    short = routes["alternatives"][0]
    shady = routes["alternatives"][1]
    assert isinstance(short, dict) and isinstance(shady, dict)
    short["heat_value"] = 42
    shady["heat_value"] = 36
    shady["recommendation_reason"] = None

    response = normalize_trip_analysis(
        payload,
        replace(_request(), cautious=True),
        ExecutionMode.FIXTURE,
    )

    assert response.routes is not None
    assert response.routes.recommended_id == "shady"
    assert response.routes.reason == "cautious guidance selected the least-hot returned route"
    assert [route.identity for route in response.routes.alternatives if route.recommended] == [
        "shady"
    ]


def test_provider_metric_response_records_noaa_heat_index_as_unavailable() -> None:
    response = normalize_trip_analysis(_payload(), _request(), ExecutionMode.FIXTURE)

    assert response.best_time is not None
    interpretation = response.best_time.heat_interpretation
    assert interpretation is not None
    assert interpretation.metric.value == "tcm"
    assert interpretation.value_celsius == 29
    assert interpretation.is_actual_heat_index is False
    assert interpretation.noaa_heat_index_available is False
    assert interpretation.band_label == "Lower provider temperature"


def test_actual_heat_index_is_classified_with_noaa_names_without_relabeling_tcm() -> None:
    payload = _payload()
    best_time = payload["best_time"]
    assert isinstance(best_time, dict)
    hourly = best_time["hourly"]
    assert isinstance(hourly, list)
    for entry in hourly:
        assert isinstance(entry, dict)
        entry["heat_index_celsius"] = 38

    response = normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)

    assert response.best_time is not None
    interpretation = response.best_time.heat_interpretation
    assert interpretation is not None
    assert response.best_time.metric_label.value == "provider_tcm"
    assert interpretation.metric.value == "heat_index_celsius"
    assert interpretation.is_actual_heat_index is True
    assert interpretation.noaa_heat_index_available is True
    assert interpretation.band is HeatBand.EXTREME_CAUTION


def test_cautious_best_time_uses_each_hours_actual_heat_index() -> None:
    payload = _payload()
    best_time = payload["best_time"]
    assert isinstance(best_time, dict)
    best_time["hourly"] = [
        {"hour": 8, "value": 28.0, "heat_index_celsius": 34.0},
        {"hour": 14, "value": 27.0, "heat_index_celsius": 25.0},
        {"hour": 19, "value": 31.0, "heat_index_celsius": 24.0},
    ]
    best_time["recommendation_hour"] = 8

    response = normalize_trip_analysis(
        payload,
        replace(_request(), cautious=True),
        ExecutionMode.FIXTURE,
    )

    assert response.best_time is not None
    assert response.best_time.recommendation_hour == 19
    assert response.best_time.heat_interpretation is not None
    assert response.best_time.heat_interpretation.value_celsius == 24
    assert response.best_time.heat_interpretation.is_actual_heat_index is True


def test_cautious_best_time_prefers_an_hour_below_the_earlier_action_threshold() -> None:
    payload = _payload()
    best_time = payload["best_time"]
    assert isinstance(best_time, dict)
    best_time["hourly"] = [
        {"hour": 8, "value": 33.0},
        {"hour": 14, "value": 38.0},
        {"hour": 19, "value": 29.0},
    ]
    best_time["recommendation_hour"] = 8

    response = normalize_trip_analysis(
        payload,
        replace(_request(), cautious=True),
        ExecutionMode.FIXTURE,
    )

    assert response.best_time is not None
    assert response.best_time.recommendation_hour == 19
    assert response.best_time.heat_interpretation is not None
    assert response.best_time.heat_interpretation.action_required is False


def test_cautious_best_time_explains_lowest_value_fallback_when_all_hours_trigger_action() -> None:
    payload = _payload()
    best_time = payload["best_time"]
    assert isinstance(best_time, dict)
    best_time["hourly"] = [
        {"hour": 8, "value": 34.0},
        {"hour": 14, "value": 38.0},
        {"hour": 19, "value": 32.0},
    ]
    best_time["recommendation_hour"] = 19

    response = normalize_trip_analysis(
        payload,
        replace(_request(), cautious=True),
        ExecutionMode.FIXTURE,
    )

    assert response.best_time is not None
    assert response.best_time.recommendation_hour == 19
    assert (
        "all periods meet the earlier action threshold" in response.best_time.recommendation_reason
    )


def test_insufficient_confidence_shortest_route_fallback_overrides_cautious_optimization() -> None:
    payload = _payload()
    routes = payload["routes"]
    assert isinstance(routes, dict)
    routes["recommended_id"] = "short"
    routes["confidence"] = Confidence.INSUFFICIENT.value
    routes["fallback_reason"] = "insufficient route comparison confidence"
    payload["degraded_reasons"] = {"routes": "insufficient route comparison confidence"}

    response = normalize_trip_analysis(
        payload,
        replace(_request(), cautious=True),
        ExecutionMode.FIXTURE,
    )

    assert response.routes is not None
    assert response.routes.recommended_id == "short"
    assert response.routes.fallback_reason == "insufficient route comparison confidence"


def test_duplicate_hourly_evidence_is_rejected() -> None:
    payload = _payload()
    best_time = payload["best_time"]
    assert isinstance(best_time, dict)
    hourly = best_time["hourly"]
    assert isinstance(hourly, list)
    hourly.append(deepcopy(hourly[0]))
    best_time["hourly_coverage"] = len(hourly) / 24

    with pytest.raises(ValueError, match="duplicate hours"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)


def test_percentile_and_tie_group_validation_rejects_malformed_ranking() -> None:
    payload = _payload()
    hotels = payload["hotels"]
    assert isinstance(hotels, dict)
    ranked = hotels["ranked"]
    assert isinstance(ranked, list)
    first = ranked[0]
    assert isinstance(first, dict)
    first["percentile"] = 101

    with pytest.raises(ValueError, match="percentile"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)


def test_route_recommendation_must_be_internally_consistent() -> None:
    payload = _payload()
    routes = payload["routes"]
    assert isinstance(routes, dict)
    routes["recommended_id"] = "missing"

    with pytest.raises(ValueError, match="recommended_id"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)


def test_insufficient_confidence_requires_fallback_and_degraded_reason() -> None:
    payload = _payload()
    routes = payload["routes"]
    assert isinstance(routes, dict)
    routes["confidence"] = Confidence.INSUFFICIENT.value

    with pytest.raises(ValueError, match="fallback_reason"):
        normalize_trip_analysis(payload, _request(), ExecutionMode.FIXTURE)
