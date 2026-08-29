"""Shared route heat AOI and conservative tile aggregation behavior."""

from datetime import date, datetime, timezone
from typing import cast

import pytest
from shapely.geometry import LineString, shape

from app.domain.provenance import Provenance
from app.domain.route_heat import (
    SharedRouteHeatRequest,
    aggregate_shared_route_heat,
    build_shared_route_aoi,
)
from app.domain.routing import RouteGeometry, ReturnedRoute, RouteSet
from app.integrations.fortyguard.client import ActivityMetadata, FortyGuardClient
from app.integrations.fortyguard.contracts import AnalyticType, HeatmapResult, Tile
from app.integrations.fortyguard.live import (
    LiveSharedRouteHeatAdapter,
    build_documented_shared_route_heat_payload,
    shared_route_request_transformations,
)


def _route(identity: str, coordinates: tuple[tuple[float, float], ...]) -> ReturnedRoute:
    return ReturnedRoute(identity, 1800.0, 1200.0, RouteGeometry(coordinates))


def _routes() -> RouteSet:
    return RouteSet(
        (
            _route("route-1", ((-98.4900, 29.4200), (-98.4800, 29.4300))),
            _route("route-2", ((-98.4890, 29.4210), (-98.4780, 29.4280))),
        ),
        "fossgis-routed-foot",
    )


def _tile(identity: str, west: float, east: float, value: float) -> Tile:
    return Tile(
        identity=identity,
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [west, 29.415],
                    [east, 29.415],
                    [east, 29.435],
                    [west, 29.435],
                    [west, 29.415],
                ]
            ],
        },
        metric=AnalyticType.TCM,
        value_celsius=value,
        metric_value=value,
        unit="C",
        source="fixture",
        valid_time=datetime(2026, 8, 23, 16, tzinfo=timezone.utc),
        forecast=False,
    )


def _heatmap(*tiles: Tile) -> HeatmapResult:
    return HeatmapResult(
        tiles,
        Provenance(
            source="fixture",
            retrieved_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
            data_date="2026-08-23",
            stale=False,
            forecast=False,
        ),
    )


def test_shared_aoi_is_one_canonical_rectangle_covering_every_route() -> None:
    routes = _routes()
    first = build_shared_route_aoi(routes, buffer_m=25.0)
    reversed_routes = RouteSet(tuple(reversed(routes.routes)), routes.provider_instance)
    second = build_shared_route_aoi(reversed_routes, buffer_m=25.0)

    assert first == second
    polygon = shape(first)
    assert len(first["coordinates"][0]) == 5  # type: ignore[index]
    for route in routes.routes:
        assert polygon.covers(LineString(route.geometry.coordinates))


def _shared_request() -> SharedRouteHeatRequest:
    return SharedRouteHeatRequest(
        geometry=build_shared_route_aoi(_routes(), buffer_m=25.0),
        start_date=date(2026, 8, 23),
        hour=16,
        forecast=False,
        granularity=100,
        buffer_m=25.0,
        provider_instance="fortyguard",
        request_version="shared-route-heat-v1",
    )


def test_selected_hour_payload_and_identity_include_geometry_and_configuration() -> None:
    request = _shared_request()
    payload = build_documented_shared_route_heat_payload(request, today=date(2026, 8, 23))

    assert payload["date_time"] == {
        "start_date": "2026-08-23",
        "filter_type": 1,
        "start_time": "16:00",
    }
    assert payload["analytic_type"] == "tcm"
    assert payload["polygon_aoi"]["features"][0]["geometry"] == request.geometry  # type: ignore[index]
    identity = request.to_payload()
    assert identity["geometry"] == request.geometry
    assert identity["hour"] == 16
    assert identity["buffer_m"] == 25.0
    assert {item.name for item in shared_route_request_transformations()} >= {
        "multi_route_bounding_aoi",
        "valid_time_from_request",
        "tcm_unit_celsius",
    }


def test_live_shared_adapter_submits_exactly_one_activity() -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        def submit_and_poll(
            self, endpoint: str, payload: dict[str, object], **kwargs: object
        ) -> tuple[dict[str, object], ActivityMetadata]:
            calls.append(payload)
            result = {
                "map_data": {
                    "features": [
                        {
                            "geometry": _tile("one", -98.491, -98.477, 35.0).geometry,
                            "properties": {"average_temperature": 35.0},
                        }
                    ]
                }
            }
            metadata = ActivityMetadata(
                "activity-1",
                datetime(2026, 8, 23, tzinfo=timezone.utc),
                endpoint,
                tuple(sorted(payload)),
            )
            return cast(dict[str, object], result), metadata

    adapter = LiveSharedRouteHeatAdapter(
        cast(FortyGuardClient, FakeClient()),
        today=lambda: date(2026, 8, 23),
        sleep=lambda seconds: None,
    )
    outcome = adapter.load(_shared_request())

    assert len(calls) == 1
    assert outcome.activity_id == "activity-1"
    features = outcome.payload["features"]
    assert isinstance(features, list)
    properties = features[0]["properties"]
    assert isinstance(properties, dict)
    assert properties["valid_time"].endswith("T16:00:00+00:00")


def test_each_route_uses_maximum_intersecting_temperature_not_average() -> None:
    results = aggregate_shared_route_heat(
        _routes(),
        _heatmap(
            _tile("cool", -98.491, -98.4845, 31.0),
            _tile("hot", -98.4845, -98.477, 39.0),
        ),
        buffer_m=25.0,
        minimum_coverage=0.70,
    )

    assert {result.route_id: result.maximum_tcm_celsius for result in results} == {
        "route-1": 39.0,
        "route-2": 39.0,
    }
    assert all(result.coverage >= 0.70 for result in results)
    assert all(result.sufficient for result in results)


def test_route_coverage_is_independent_and_threshold_is_inclusive() -> None:
    routes = RouteSet(
        (
            _route("covered", ((-98.490, 29.420), (-98.486, 29.424))),
            _route("outside", ((-98.480, 29.430), (-98.476, 29.434))),
        ),
        "fossgis-routed-foot",
    )
    results = aggregate_shared_route_heat(
        routes,
        _heatmap(_tile("one", -98.491, -98.485, 35.0)),
        buffer_m=25.0,
        minimum_coverage=0.70,
    )
    by_id = {result.route_id: result for result in results}
    assert by_id["covered"].coverage > by_id["outside"].coverage
    assert by_id["covered"].sufficient is True
    assert by_id["outside"].maximum_tcm_celsius is None
    assert by_id["outside"].sufficient is False

    boundary = by_id["covered"]
    assert boundary.with_minimum_coverage(boundary.coverage).sufficient is True


def test_route_heat_rejects_wrong_metric_or_hour() -> None:
    route = RouteSet((_routes().routes[0],), "fossgis-routed-foot")
    wrong_hour = _tile("tile", -98.491, -98.477, 35.0)
    wrong_hour = Tile(
        **{
            **wrong_hour.__dict__,
            "valid_time": datetime(2026, 8, 23, 15, tzinfo=timezone.utc),
        }
    )
    with pytest.raises(ValueError, match="selected hour"):
        aggregate_shared_route_heat(
            route,
            _heatmap(wrong_hour),
            buffer_m=25.0,
            minimum_coverage=0.70,
            selected_hour=16,
        )
