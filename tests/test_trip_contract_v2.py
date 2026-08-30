from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path

import pytest

from app.domain.contracts import (
    Confidence,
    Coordinates,
    EnrichmentState,
    ExecutionMode,
    HeatMetricName,
    HeatStatus,
    HotelRankingResult,
    HourlyEntry,
    Metric,
    MetricLabel,
    OptionalEnrichment,
    Provenance,
    RankedHotel,
    ResultState,
    RouteComparisonResult,
    RouteDecisionState,
    RouteHeatSource,
    RouteOption,
    RouteSetState,
    TemporalEvidenceState,
    TripAnalysisRequest,
    TripAnalysisResponse,
    TripMode,
    UnavailableResult,
    BestTimeResult,
)
from app.domain.heat_policy import classify_heat
from app.domain.route_shade import ShadeConfidence
from app.services.trip_contract_v2 import decode_trip_analysis_v2, encode_trip_analysis_v2
from app.services.trip_adapters import FixtureTripAnalysisAdapter, LiveTripAnalysisAdapter


def request() -> TripAnalysisRequest:
    return TripAnalysisRequest(
        mode=TripMode.EXPLORATORY,
        origin=Coordinates(29.42, -98.49),
        destination=Coordinates(29.43, -98.48),
        landmark_name="Market Square",
        district_name="Downtown San Antonio",
        date="2024-07-15",
        start_hour=10,
        end_hour=17,
        cautious=False,
    )


def provenance(source: str = "provider") -> Provenance:
    return Provenance(
        source=source,
        data_date="2024-07-15",
        confidence=Confidence.SUFFICIENT,
        retrieved_at="2024-07-16T00:00:00+00:00",
        transformation_version="test-v1",
        provider="test-provider",
        response_status="completed",
        request_configuration={"nested": {"value": 1}},
        fresh=True,
        coverage=1.0,
    )


def best_time() -> BestTimeResult:
    value = 29.0
    return BestTimeResult(
        hourly=(
            HourlyEntry(
                10,
                Metric(value, "C", MetricLabel.PROVIDER_TCM, False),
            ),
        ),
        recommendation_hour=10,
        recommendation_reason="coolest available period",
        metric_label=MetricLabel.PROVIDER_TCM,
        provenance=provenance(),
        hourly_coverage=1 / 24,
        heat_interpretation=classify_heat(value, metric=HeatMetricName.TCM),
        recommended_hour_tcm_celsius=value,
        exceedance_hours=2.0,
        persistence_hours=1.0,
        framing_threshold_celsius=35.0,
        framing_direction="above",
        recommendation_time=datetime.fromisoformat("2024-07-15T10:00:00-05:00"),
        recommendation_timezone="America/Chicago",
        temporal_evidence=TemporalEvidenceState.EXACT,
    )


def hotels(enrichment: OptionalEnrichment | None = None) -> HotelRankingResult:
    return HotelRankingResult(
        ranked=(
            RankedHotel(
                "hotel-a",
                {"night": 30, "hot_hours": 4, "persistence": 2, "day": 32},
                18.3,
                100,
                0,
            ),
        ),
        weights={"night": 0.35, "hot_hours": 0.25, "persistence": 0.2, "day": 0.2},
        usable_count=1,
        discovered_count=1,
        provenance=provenance(),
        enrichment=enrichment or OptionalEnrichment(EnrichmentState.NOT_REQUESTED),
        component_units={"night": "C", "hot_hours": "hours", "persistence": "hours", "day": "C"},
    )


def route_option(identity: str = "route-1", *, recommended: bool = True) -> RouteOption:
    value = 29.0
    return RouteOption(
        identity=identity,
        distance_m=900,
        duration_s=720,
        heat_value=value,
        heat_unit="C",
        heat_metric=HeatMetricName.TCM,
        heat_status=HeatStatus.NOT_ELEVATED,
        modeled_shade_percent=None,
        shade_confidence=None,
        building_coverage=0.0,
        recommended=recommended,
        recommendation_reason="shortest returned route" if recommended else None,
        shade_model_label=None,
        heat_interpretation=classify_heat(value, metric=HeatMetricName.TCM),
        geometry=((-98.49, 29.42), (-98.48, 29.43)),
        heat_coverage=1.0,
        heat_source=RouteHeatSource.LANDMARK_REUSE,
        shade_limitations=("single route returned",),
    )


def one_route() -> RouteComparisonResult:
    return RouteComparisonResult(
        alternatives=(route_option(),),
        recommended_id="route-1",
        reason="shortest returned route",
        heat_status=HeatStatus.NOT_ELEVATED,
        corridor_heat_value=29.0,
        heat_metric=HeatMetricName.TCM,
        heat_unit="C",
        coverage=1.0,
        confidence=Confidence.SUFFICIENT,
        comparison_scope="returned alternatives",
        provenance=provenance(),
        heat_interpretation=classify_heat(29.0, metric=HeatMetricName.TCM),
        route_set_state=RouteSetState.SINGLE_ROUTE,
        decision_state=RouteDecisionState.MILD_SHORTEST_RECOMMENDED,
        lowest_heat_route_id="route-1",
        routing_provenance=provenance(),
        heat_provenance=provenance(),
    )


def response(routes: RouteComparisonResult | None = None) -> TripAnalysisResponse:
    return TripAnalysisResponse(
        request_identity="ignored-by-snapshot",
        mode=TripMode.EXPLORATORY,
        execution_mode=ExecutionMode.LIVE,
        state=ResultState.SUCCESS,
        best_time=best_time(),
        hotels=hotels(),
        routes=routes or one_route(),
    )


def test_modern_explicit_one_route_round_trip_preserves_exact_evidence() -> None:
    decoded = decode_trip_analysis_v2(
        encode_trip_analysis_v2(response()), request(), ExecutionMode.FIXTURE
    )

    assert decoded.request_identity == "exploratory:2024-07-15:10-17"
    assert decoded.best_time == best_time()
    assert decoded.routes == one_route()
    assert decoded.execution_mode is ExecutionMode.FIXTURE


def test_weak_height_no_recommendation_round_trip() -> None:
    first = replace(
        route_option("route-1", recommended=False),
        heat_value=38.0,
        heat_status=HeatStatus.ELEVATED,
        heat_interpretation=classify_heat(38.0, metric=HeatMetricName.TCM),
        modeled_shade_percent=12.0,
        shade_confidence=ShadeConfidence.INSUFFICIENT,
        shade_model_label="modeled building shade",
        building_coverage=0.34,
        building_explicit_fraction=0.2,
        building_inferred_levels_fraction=0.14,
        building_unknown_fraction=0.66,
        building_explicit_count=2,
        building_inferred_levels_count=1,
        building_unknown_count=5,
    )
    second = replace(first, identity="route-2", distance_m=950, modeled_shade_percent=16.0)
    routes = RouteComparisonResult(
        alternatives=(first, second),
        recommended_id=None,
        reason="height evidence is insufficient for a recommendation",
        heat_status=HeatStatus.ELEVATED,
        corridor_heat_value=38.0,
        heat_metric=HeatMetricName.TCM,
        heat_unit="C",
        coverage=1.0,
        confidence=Confidence.SUFFICIENT,
        comparison_scope="returned alternatives",
        provenance=provenance(),
        heat_interpretation=classify_heat(38.0, metric=HeatMetricName.TCM),
        route_set_state=RouteSetState.ALTERNATIVES_RETURNED,
        decision_state=RouteDecisionState.INSUFFICIENT_SHADE_COMPARISON_REQUIRED,
        lowest_heat_route_id="route-1",
        routing_provenance=provenance(),
        heat_provenance=provenance(),
        building_provenance=provenance(),
        solar_provenance=provenance("computed"),
    )
    original = replace(
        response(routes),
        state=ResultState.DEGRADED,
        degraded_reasons={"routes": "height evidence is insufficient"},
    )

    decoded = decode_trip_analysis_v2(
        encode_trip_analysis_v2(original), request(), ExecutionMode.LIVE
    )

    assert decoded.routes == routes
    assert decoded.routes is not None and decoded.routes.recommended_id is None


def test_structured_whole_trip_unavailable_round_trip() -> None:
    original = TripAnalysisResponse(
        request_identity="ignored",
        mode=TripMode.EXPLORATORY,
        execution_mode=ExecutionMode.LIVE,
        state=ResultState.UNAVAILABLE,
        unavailable=UnavailableResult(
            "The initial TCM analysis failed.", True, "provider_data_missing", "retry_or_edit_setup"
        ),
    )

    decoded = decode_trip_analysis_v2(
        encode_trip_analysis_v2(original), request(), ExecutionMode.FIXTURE
    )

    assert decoded.unavailable is not None
    assert decoded.unavailable.code == "provider_data_missing"
    assert decoded.best_time is decoded.hotels is decoded.routes is None


def test_unavailable_enrichment_retains_hotels_and_degrades_trip() -> None:
    enrichment = OptionalEnrichment(
        EnrichmentState.UNAVAILABLE,
        code="optional_provider_failure",
        reason="Optional hotel enrichment was unavailable.",
    )
    original = replace(
        response(),
        state=ResultState.DEGRADED,
        hotels=hotels(enrichment),
        degraded_reasons={
            "hotels": "Optional hotel enrichment was unavailable.",
            "routes": "only one route was returned",
        },
    )

    decoded = decode_trip_analysis_v2(
        encode_trip_analysis_v2(original), request(), ExecutionMode.LIVE
    )

    assert decoded.state is ResultState.DEGRADED
    assert decoded.hotels is not None and decoded.hotels.enrichment == enrichment


def test_unavailable_enrichment_cannot_be_labeled_success() -> None:
    enrichment = OptionalEnrichment(
        EnrichmentState.UNAVAILABLE,
        code="optional_provider_failure",
        reason="Optional hotel enrichment was unavailable.",
    )

    with pytest.raises(ValueError, match="requires degraded state"):
        replace(response(), hotels=hotels(enrichment))


def test_unknown_key_is_rejected_at_nested_contract_boundary() -> None:
    payload = encode_trip_analysis_v2(response())
    routes = payload["routes"]
    assert isinstance(routes, dict)
    alternatives = routes["alternatives"]
    assert isinstance(alternatives, list) and isinstance(alternatives[0], dict)
    alternatives[0]["unexpected"] = True

    with pytest.raises(ValueError, match="unknown keys.*unexpected"):
        decode_trip_analysis_v2(payload, request(), ExecutionMode.FIXTURE)


def test_api_envelope_reuses_snapshot_sections_and_adds_adapter_identity() -> None:
    original = response()
    snapshot = encode_trip_analysis_v2(original)
    api = encode_trip_analysis_v2(original, envelope="api")

    assert {key: api[key] for key in snapshot} == snapshot
    assert api["request_identity"] == "ignored-by-snapshot"
    assert api["mode"] == "exploratory"
    assert api["execution_mode"] == "live"


def write_fixture(
    path: Path,
    trip_response: TripAnalysisResponse,
    trip_request: TripAnalysisRequest,
    *,
    status: str = "ok",
) -> None:
    path.write_text(json.dumps(encode_trip_analysis_v2(trip_response)), encoding="utf-8")
    sidecar = path.with_name(f"{path.stem}.acquisition.json")
    sidecar.write_text(
        json.dumps(
            {
                "source": "synthesized",
                "provider": "heat-aware-tourism-guide",
                "endpoint": "/api/trip/analyze",
                "request_configuration": {
                    "mode": trip_request.mode.value,
                    "landmark_name": trip_request.landmark_name,
                    "district_name": trip_request.district_name,
                    "date": trip_request.date,
                    "start_hour": trip_request.start_hour,
                    "end_hour": trip_request.end_hour,
                    "cautious": trip_request.cautious,
                    "origin": {
                        "latitude": trip_request.origin.latitude,
                        "longitude": trip_request.origin.longitude,
                    },
                    "destination": {
                        "latitude": trip_request.destination.latitude,
                        "longitude": trip_request.destination.longitude,
                    },
                },
                "retrieved_at": None,
                "data_date": trip_request.date,
                "status": status,
                "schema_version": "trip-contract-v2",
                "provider_config_version": "trip-product-config-v1",
                "activity_id": None,
                "derived_from": [],
                "transformations": [],
            }
        ),
        encoding="utf-8",
    )


def test_live_and_fixture_decode_the_same_v2_sections(tmp_path: Path) -> None:
    fixture_path = tmp_path / "trip.json"
    payload = encode_trip_analysis_v2(response())
    write_fixture(fixture_path, response(), request())

    fixture = FixtureTripAnalysisAdapter(fixture_path).analyze(request())
    live = LiveTripAnalysisAdapter(lambda _: payload).analyze(request())

    assert fixture.best_time == live.best_time
    assert fixture.hotels == live.hotels
    assert fixture.routes == live.routes
    assert fixture.execution_mode is ExecutionMode.FIXTURE
    assert live.execution_mode is ExecutionMode.LIVE


def test_multiple_paths_select_exact_sidecar_identity_in_any_order(tmp_path: Path) -> None:
    requested_path = tmp_path / "requested.json"
    other_path = tmp_path / "other.json"
    other_request = replace(request(), destination=Coordinates(29.44, -98.47))
    write_fixture(requested_path, response(), request())
    write_fixture(other_path, response(), other_request)

    selected = FixtureTripAnalysisAdapter((other_path, requested_path)).analyze(request())
    near_miss = FixtureTripAnalysisAdapter((other_path, requested_path)).analyze(
        replace(request(), destination=Coordinates(29.4300002, -98.48))
    )

    assert selected.state is ResultState.SUCCESS
    assert near_miss.state is ResultState.UNAVAILABLE
    assert near_miss.unavailable is not None
    assert near_miss.unavailable.code == "scenario_unavailable"


def test_duplicate_matching_sidecars_raise_configuration_error(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_fixture(first, response(), request())
    write_fixture(second, response(), request())

    adapter = FixtureTripAnalysisAdapter((first, second))

    with pytest.raises(ValueError, match="duplicate matching trip fixtures.*first.*second"):
        adapter.analyze(request())


def test_unavailable_product_sidecar_is_selectable(tmp_path: Path) -> None:
    fixture_path = tmp_path / "unavailable.json"
    unavailable = TripAnalysisResponse(
        request_identity="ignored",
        mode=request().mode,
        execution_mode=ExecutionMode.FIXTURE,
        state=ResultState.UNAVAILABLE,
        unavailable=UnavailableResult(
            "Initial provider data is missing.", True, "provider_data_missing"
        ),
    )
    write_fixture(fixture_path, unavailable, request(), status="unavailable")

    selected = FixtureTripAnalysisAdapter((fixture_path,)).analyze(request())

    assert selected.state is ResultState.UNAVAILABLE
    assert selected.unavailable is not None
    assert selected.unavailable.code == "provider_data_missing"


def test_malformed_configured_fixture_fails_inventory_even_when_not_selected(
    tmp_path: Path,
) -> None:
    valid_path = tmp_path / "valid.json"
    malformed_path = tmp_path / "malformed.json"
    write_fixture(valid_path, response(), request())
    write_fixture(malformed_path, response(), replace(request(), date="2024-07-16"))
    malformed_payload = json.loads(malformed_path.read_text(encoding="utf-8"))
    assert isinstance(malformed_payload, dict)
    malformed_payload["unexpected"] = True
    malformed_path.write_text(json.dumps(malformed_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="malformed.json.*invalid v2 envelope"):
        FixtureTripAnalysisAdapter((valid_path, malformed_path))
