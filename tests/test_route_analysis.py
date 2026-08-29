"""Route acquisition and heat-branch orchestration tests."""

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from app.domain.contracts import (
    BestTimeResult,
    Confidence,
    Coordinates,
    HeatMetricName,
    HourlyEntry,
    Metric,
    MetricLabel,
    Provenance,
    RouteDecisionState,
    RouteHeatSource,
    TripAnalysisRequest,
    TripMode,
)
from app.domain.heat_policy import classify_heat
from app.domain.route_heat import SharedRouteHeatRequest
from app.domain.routing import RouteRequest
from app.services.route_analysis import RouteAnalysisService
from app.services.routing import RouteExecution


def _request() -> TripAnalysisRequest:
    return TripAnalysisRequest(
        mode=TripMode.CURATED,
        origin=Coordinates(29.4200, -98.4900),
        destination=Coordinates(29.4300, -98.4800),
        landmark_name="The Alamo",
        district_name="Downtown San Antonio",
        date="2020-08-23",
        start_hour=8,
        end_hour=12,
        cautious=False,
    )


def _best_time(value: float = 32.0) -> BestTimeResult:
    provenance = Provenance(
        source="provider",
        data_date="2020-08-23",
        confidence=Confidence.SUFFICIENT,
        retrieved_at="2020-08-23T14:00:00+00:00",
        transformation_version="best-time-decision-v1",
        provider="fortyguard",
        response_status="completed",
        request_configuration={"hour": 9},
        fresh=True,
    )
    return BestTimeResult(
        hourly=(
            HourlyEntry(
                9,
                Metric(
                    value=value,
                    unit="C",
                    label=MetricLabel.PROVIDER_TCM,
                    is_actual_heat_index=False,
                ),
            ),
        ),
        recommendation_hour=9,
        recommendation_reason="lowest available heat",
        metric_label=MetricLabel.PROVIDER_TCM,
        provenance=provenance,
        hourly_coverage=1 / 24,
        heat_interpretation=classify_heat(value, metric=HeatMetricName.TCM),
        recommended_hour_tcm_celsius=value,
    )


def _osrm_payload(*, long: bool = False, single: bool = False) -> dict[str, object]:
    routes: list[dict[str, object]] = [
        {
            "distance": 1800.0 if long else 900.0,
            "duration": 720.0,
            "geometry": {
                "type": "LineString",
                "coordinates": [[-98.4900, 29.4200], [-98.4800, 29.4300]],
            },
        }
    ]
    if not single:
        routes.append(
            {
                "distance": 1000.0,
                "duration": 780.0,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-98.4900, 29.4200], [-98.4850, 29.4260], [-98.4800, 29.4300]],
                },
            }
        )
    return {"code": "Ok", "routes": routes}


def _service(
    tmp_path: Path,
    route_loader: Callable[[RouteRequest], Mapping[str, object]],
    *,
    shared_loader: Callable[[SharedRouteHeatRequest], Mapping[str, object]] | None = None,
) -> RouteAnalysisService:
    execution = RouteExecution(
        fixture_path=tmp_path / "route.json",
        live_loader=route_loader,
    )
    return RouteAnalysisService(
        execution,
        profile="foot",
        alternatives=True,
        overview="full",
        geometries="geojson",
        steps=False,
        provider_instance="fossgis-routed-foot",
        request_version="v1",
        representative_distance_m=1500.0,
        minimum_heat_coverage=0.70,
        corridor_buffer_m=25.0,
        corridor_granularity=100,
        shared_heat_loader=shared_loader,
        clock=lambda: datetime(2020, 8, 23, 14, tzinfo=timezone.utc),
    )


def _shared_payload(value: float, *, hour: int = 9) -> dict[str, object]:
    return {
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-98.495, 29.415],
                            [-98.475, 29.415],
                            [-98.475, 29.435],
                            [-98.495, 29.435],
                            [-98.495, 29.415],
                        ]
                    ],
                },
                "properties": {
                    "id": "shared-tile",
                    "value": value,
                    "unit": "C",
                    "valid_time": f"2020-08-23T{hour:02d}:00:00+00:00",
                },
            }
        ]
    }


def test_all_short_routes_execute_osrm_once_and_reuse_landmark_heat(tmp_path: Path) -> None:
    route_calls = 0
    shared_calls = 0

    def load_routes(request: RouteRequest) -> Mapping[str, object]:
        nonlocal route_calls
        route_calls += 1
        return _osrm_payload()

    def load_shared(request: SharedRouteHeatRequest) -> Mapping[str, object]:
        nonlocal shared_calls
        shared_calls += 1
        return _shared_payload(38.0)

    result = _service(tmp_path, load_routes, shared_loader=load_shared).analyze(
        _request(), _best_time(32.0)
    )

    assert route_calls == 1
    assert shared_calls == 0
    assert result.decision_state is RouteDecisionState.MILD_SHORTEST_RECOMMENDED
    assert result.recommended_id == "route-1"
    assert {option.heat_value for option in result.alternatives} == {32.0}
    assert {option.heat_source for option in result.alternatives} == {
        RouteHeatSource.LANDMARK_REUSE
    }


def test_any_long_route_executes_one_shared_activity_and_defers_elevated_heat(
    tmp_path: Path,
) -> None:
    route_calls = 0
    shared_calls = 0

    def load_routes(request: RouteRequest) -> Mapping[str, object]:
        nonlocal route_calls
        route_calls += 1
        return _osrm_payload(long=True)

    def load_shared(request: SharedRouteHeatRequest) -> Mapping[str, object]:
        nonlocal shared_calls
        shared_calls += 1
        assert request.hour == 9
        return _shared_payload(38.0)

    result = _service(tmp_path, load_routes, shared_loader=load_shared).analyze(
        _request(), _best_time()
    )

    assert route_calls == 1
    assert shared_calls == 1
    assert result.decision_state is RouteDecisionState.SHADE_REQUIRED
    assert result.recommended_id is None
    assert {option.heat_source for option in result.alternatives} == {
        RouteHeatSource.SHARED_CORRIDOR
    }
    assert all(option.heat_value == 38.0 for option in result.alternatives)


def test_route_unavailable_returns_explicit_no_suitable_route_state(tmp_path: Path) -> None:
    result = _service(
        tmp_path,
        lambda request: {"code": "NoRoute", "routes": []},
    ).analyze(_request(), _best_time())

    assert result.decision_state is RouteDecisionState.NO_SUITABLE_RETURNED_ROUTE
    assert result.route_set_state is not None
    assert result.route_set_state.value == "no_suitable_returned_route"
    assert result.alternatives == ()
    assert result.recommended_id is None


def test_long_route_heat_hour_mismatch_returns_heat_unavailable(tmp_path: Path) -> None:
    result = _service(
        tmp_path,
        lambda request: _osrm_payload(long=True),
        shared_loader=lambda request: _shared_payload(38.0, hour=10),
    ).analyze(_request(), _best_time())

    assert result.decision_state is RouteDecisionState.HEAT_UNAVAILABLE
    assert len(result.alternatives) == 2
    assert all(option.heat_value is None for option in result.alternatives)


def test_long_route_heat_failure_preserves_routes_without_landmark_substitution(
    tmp_path: Path,
) -> None:
    def fail_shared(request: SharedRouteHeatRequest) -> Mapping[str, object]:
        raise ConnectionError("corridor unavailable")

    result = _service(
        tmp_path,
        lambda request: _osrm_payload(long=True),
        shared_loader=fail_shared,
    ).analyze(_request(), _best_time(31.0))

    assert result.decision_state is RouteDecisionState.HEAT_UNAVAILABLE
    assert len(result.alternatives) == 2
    assert result.recommended_id is None
    assert all(option.heat_value is None for option in result.alternatives)
    assert all(option.heat_source is None for option in result.alternatives)
