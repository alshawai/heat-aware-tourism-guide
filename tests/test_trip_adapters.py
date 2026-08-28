from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from app.domain.contracts import (
    Confidence,
    Coordinates,
    ExecutionMode,
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
        hour=8,
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


def test_fixture_adapter_returns_unavailable_for_unmatched_hour() -> None:
    response = FixtureTripAnalysisAdapter(Path("fixtures/trip-analysis.json")).analyze(
        replace(_request(), hour=9), ExecutionMode.FIXTURE
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
