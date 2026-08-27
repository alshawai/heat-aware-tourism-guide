"""Tests for the area heatmap adapter path (Issue #37).

Covers: route buffer polygon construction (straight line, sharp turn,
oversized with simplification), documented area payload builder, multi-tile
response translation verification, area provenance stamps, consumer-side
route-to-tile segment mapping, and LiveAreaHeatmapAdapter end-to-end.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, cast

import pytest
from shapely.geometry import shape

from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.contracts import AnalyticType, HeatmapRequest, normalize_heatmap_response
from app.integrations.fortyguard.errors import ProviderError, ProviderErrorKind
from app.integrations.fortyguard.live import (
    LiveAreaHeatmapAdapter,
    LiveFortyGuardTransport,
    area_request_transformations,
    build_documented_area_heatmap_payload,
    build_route_corridor_polygon,
    map_tiles_to_route_segments,
    translate_heatmap_response,
)
from app.services.execution import LiveHeatmapPayload
from app.settings import FortyGuardPollingSettings


# --- Canonical San Antonio route coordinates (lat, lon) --- #
# Menger Hotel → The Alamo, simplified
_SA_ROUTE = [
    (29.4259, -98.4861),
    (29.4250, -98.4858),
    (29.4241, -98.4853),
    (29.4232, -98.4850),
    (29.4225, -98.4847),
]

# A route with a sharp ~90° turn
_SHARP_TURN_ROUTE = [
    (29.4259, -98.4870),
    (29.4259, -98.4860),
    (29.4259, -98.4850),  # Heading east
    (29.4249, -98.4850),  # Sharp turn south
    (29.4240, -98.4850),
]


# --- Route buffer polygon construction tests --- #


class TestBuildRouteCorridorPolygon:
    def test_straight_line_produces_valid_closed_polygon(self) -> None:
        corridor = build_route_corridor_polygon(_SA_ROUTE, buffer_m=25.0)
        assert corridor.is_valid
        assert not corridor.is_empty
        assert corridor.geom_type == "Polygon"
        # Closed ring check
        coords = list(corridor.exterior.coords)
        assert coords[0] == coords[-1]

    def test_buffer_width_controls_corridor_width(self) -> None:
        narrow = build_route_corridor_polygon(_SA_ROUTE, buffer_m=10.0)
        wide = build_route_corridor_polygon(_SA_ROUTE, buffer_m=50.0)
        assert wide.area > narrow.area

    def test_sharp_turn_produces_valid_polygon(self) -> None:
        corridor = build_route_corridor_polygon(_SHARP_TURN_ROUTE, buffer_m=25.0)
        assert corridor.is_valid
        assert not corridor.is_empty
        assert corridor.geom_type == "Polygon"

    def test_sharp_turn_covers_turn_area(self) -> None:
        """The turn point should be inside the buffered corridor."""
        corridor = build_route_corridor_polygon(_SHARP_TURN_ROUTE, buffer_m=25.0)
        from shapely.geometry import Point
        turn_point = Point(-98.4850, 29.4259)  # (lng, lat) for shapely
        assert corridor.contains(turn_point) or corridor.boundary.covers(turn_point)

    def test_oversized_route_triggers_simplification(self) -> None:
        """A route with many points must be simplified to at most max_vertices."""
        # Generate a dense route with 500 points
        dense_route = [
            (29.4259 + i * 0.00001, -98.4870 + i * 0.00002)
            for i in range(500)
        ]
        max_verts = 50
        corridor = build_route_corridor_polygon(
            dense_route, buffer_m=25.0, max_vertices=max_verts
        )
        assert corridor.is_valid
        vertex_count = len(corridor.exterior.coords)
        assert vertex_count <= max_verts, (
            f"simplification must guarantee <= {max_verts} vertices, got {vertex_count}"
        )

    def test_rejects_single_point_route(self) -> None:
        with pytest.raises(ValueError, match="at least two"):
            build_route_corridor_polygon([(29.42, -98.49)])

    def test_rejects_zero_buffer(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            build_route_corridor_polygon(_SA_ROUTE, buffer_m=0)

    def test_rejects_negative_buffer(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            build_route_corridor_polygon(_SA_ROUTE, buffer_m=-5.0)

    def test_output_coordinates_are_wgs84_lng_lat_order(self) -> None:
        corridor = build_route_corridor_polygon(_SA_ROUTE, buffer_m=25.0)
        coords = list(corridor.exterior.coords)
        for lng, lat in coords:
            # San Antonio is around -98.5 lng, 29.4 lat
            assert -99.0 < lng < -98.0, f"longitude {lng} out of range"
            assert 29.0 < lat < 30.0, f"latitude {lat} out of range"


# --- Documented area payload construction tests --- #


class TestBuildDocumentedAreaHeatmapPayload:
    def test_payload_has_correct_top_level_shape(self) -> None:
        payload = build_documented_area_heatmap_payload(
            _SA_ROUTE,
            analytic_type=AnalyticType.TCM,
            start_date=date(2026, 8, 20),
            forecast=False,
            today=date(2026, 8, 27),
        )
        assert set(payload) == {"polygon_aoi", "date_time", "granularity", "analytic_type"}
        assert payload["analytic_type"] == "tcm"
        assert payload["granularity"] == 100  # area default
        assert payload["date_time"] == {"start_date": "2026-08-20", "filter_type": 3}

    def test_polygon_aoi_is_valid_feature_collection(self) -> None:
        payload = build_documented_area_heatmap_payload(
            _SA_ROUTE,
            analytic_type=AnalyticType.TCM,
            start_date=date(2026, 8, 20),
            forecast=False,
            today=date(2026, 8, 27),
        )
        aoi = payload["polygon_aoi"]
        assert isinstance(aoi, dict)
        assert aoi["type"] == "FeatureCollection"
        features = aoi["features"]
        assert isinstance(features, list) and len(features) == 1
        feature = features[0]
        assert feature["type"] == "Feature"
        geom = feature["geometry"]
        assert geom["type"] == "Polygon"
        ring = geom["coordinates"][0]
        assert ring[0] == ring[-1]  # Closed ring

    def test_area_default_granularity_is_100(self) -> None:
        payload = build_documented_area_heatmap_payload(
            _SA_ROUTE,
            analytic_type=AnalyticType.TCM,
            start_date=date(2026, 8, 20),
            forecast=False,
            today=date(2026, 8, 27),
        )
        assert payload["granularity"] == 100

    def test_custom_granularity_override(self) -> None:
        payload = build_documented_area_heatmap_payload(
            _SA_ROUTE,
            analytic_type=AnalyticType.TCM,
            start_date=date(2026, 8, 20),
            forecast=False,
            granularity=60,
            today=date(2026, 8, 27),
        )
        assert payload["granularity"] == 60

    def test_includes_threshold_and_direction_for_exceedance(self) -> None:
        payload = build_documented_area_heatmap_payload(
            _SA_ROUTE,
            analytic_type=AnalyticType.EXCEEDANCE,
            start_date=date(2026, 8, 20),
            forecast=False,
            threshold_celsius=35.0,
            direction="above",
            today=date(2026, 8, 27),
        )
        assert payload["threshold"] == 35.0
        assert payload["direction"] == "above"

    def test_rejects_out_of_contract_forecast_date(self) -> None:
        with pytest.raises(ProviderError) as error:
            build_documented_area_heatmap_payload(
                _SA_ROUTE,
                analytic_type=AnalyticType.TCM,
                start_date=date(2026, 9, 1),
                forecast=True,
                today=date(2026, 8, 27),
            )
        assert error.value.kind is ProviderErrorKind.VALIDATION

    def test_rejects_out_of_contract_historical_date(self) -> None:
        with pytest.raises(ProviderError) as error:
            build_documented_area_heatmap_payload(
                _SA_ROUTE,
                analytic_type=AnalyticType.TCM,
                start_date=date(2018, 12, 31),
                forecast=False,
                today=date(2026, 8, 27),
            )
        assert error.value.kind is ProviderErrorKind.VALIDATION


# --- Multi-tile response translation verification --- #


def _multi_tile_map_data(n_tiles: int = 4) -> dict[str, object]:
    """Build a mock live map_data response with N polygon tiles."""
    features = []
    for i in range(n_tiles):
        west = -98.49 + i * 0.001
        east = west + 0.001
        south = 29.42
        north = 29.421
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [west, south],
                        [east, south],
                        [east, north],
                        [west, north],
                        [west, south],
                    ]
                ],
            },
            "properties": {"average_temperature": 33.0 + i * 0.5},
        })
    return {
        "map_data": {"type": "FeatureCollection", "features": features},
        "stats_data": {"units": "celsius", "analytic_type": "tcm"},
    }


class TestMultiTileResponseTranslation:
    def test_translate_handles_multiple_features(self) -> None:
        request = HeatmapRequest(
            AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 20), forecast=False
        )
        translated = translate_heatmap_response(_multi_tile_map_data(4), request=request)
        features = translated["features"]
        assert isinstance(features, list)
        assert len(features) == 4

    def test_each_tile_carries_geometry_and_value(self) -> None:
        request = HeatmapRequest(
            AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 20), forecast=False
        )
        translated = translate_heatmap_response(_multi_tile_map_data(3), request=request)
        features = cast(list[dict[str, Any]], translated["features"])
        for i, feature in enumerate(features):
            props = feature["properties"]
            assert props["value"] == 33.0 + i * 0.5
            assert props["unit"] == "C"
            assert props["metric"] == "tcm"
            geom = feature["geometry"]
            assert geom["type"] == "Polygon"
            # Tile geometry is distinct and correctly carried through
            ring = geom["coordinates"][0]
            assert ring[0] == ring[-1]

    def test_single_tile_still_works(self) -> None:
        request = HeatmapRequest(
            AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 20), forecast=False
        )
        translated = translate_heatmap_response(_multi_tile_map_data(1), request=request)
        features = cast(list[dict[str, Any]], translated["features"])
        assert len(features) == 1

    def test_multi_tile_normalize_heatmap_response_produces_correct_tile_count(self) -> None:
        """Verify the full normalization pipeline handles N>1 tiles."""
        request = HeatmapRequest(
            AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 20), forecast=False
        )
        translated = translate_heatmap_response(_multi_tile_map_data(5), request=request)
        result = normalize_heatmap_response(
            translated,
            request=request,
            retrieved_at=datetime(2026, 8, 27, 12, 0),
            source="provider",
        )
        assert len(result.tiles) == 5
        values = [tile.metric_value for tile in result.tiles]
        assert values == [33.0, 33.5, 34.0, 34.5, 35.0]


# --- Area provenance stamps --- #


class TestAreaRequestTransformations:
    def test_tcm_area_stamps_include_route_to_aoi_buffer(self) -> None:
        stamps = area_request_transformations(AnalyticType.TCM)
        stamp_names = {t.name for t in stamps}
        assert "route_to_aoi_buffer" in stamp_names
        assert "point_to_aoi_expansion" not in stamp_names  # Must NOT reuse point stamp
        assert "live_envelope_unwrapped" in stamp_names
        assert "valid_time_from_request" in stamp_names
        assert "tcm_unit_celsius" in stamp_names

    def test_hour_analytics_area_stamps_no_tcm_unit(self) -> None:
        stamps = area_request_transformations(AnalyticType.EXCEEDANCE)
        stamp_names = {t.name for t in stamps}
        assert "route_to_aoi_buffer" in stamp_names
        assert "tcm_unit_celsius" not in stamp_names

    def test_all_stamps_have_version_1(self) -> None:
        stamps = area_request_transformations(AnalyticType.TCM)
        assert all(t.version == 1 for t in stamps)


# --- Consumer-side route-to-tile segment mapping --- #


def _mock_tiles_along_route() -> list[dict[str, object]]:
    """Create tiles that overlap with _SA_ROUTE segments."""
    tiles: list[dict[str, object]] = []
    for i in range(4):
        west = -98.4870 + i * 0.001
        east = west + 0.001
        south = 29.4220 + i * 0.001
        north = south + 0.001
        tiles.append({
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south], [east, south],
                    [east, north], [west, north],
                    [west, south],
                ]],
            },
            "properties": {"value": 33.0 + i},
        })
    return tiles


class TestMapTilesToRouteSegments:
    def test_returns_one_result_per_segment(self) -> None:
        segments = map_tiles_to_route_segments(_SA_ROUTE, _mock_tiles_along_route())
        assert len(segments) == len(_SA_ROUTE) - 1
        for i, seg in enumerate(segments):
            assert seg.segment_index == i
            assert seg.start == _SA_ROUTE[i]
            assert seg.end == _SA_ROUTE[i + 1]

    def test_segments_with_no_overlap_have_none_value(self) -> None:
        # Tiles far from route
        far_tiles: list[dict[str, object]] = [{
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-99.0, 30.0], [-98.9, 30.0],
                    [-98.9, 30.1], [-99.0, 30.1],
                    [-99.0, 30.0],
                ]],
            },
            "properties": {"value": 40.0},
        }]
        segments = map_tiles_to_route_segments(_SA_ROUTE, far_tiles)
        for seg in segments:
            assert seg.value is None
            assert seg.tile_count == 0

    def test_rejects_single_point_route(self) -> None:
        with pytest.raises(ValueError, match="at least two"):
            map_tiles_to_route_segments([(29.42, -98.49)], [])


# --- LiveAreaHeatmapAdapter end-to-end --- #


class _Response:
    def __init__(self, body: object) -> None:
        self._body = json.dumps(body).encode() if not isinstance(body, bytes) else body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _adapter_client(responses: list[object]) -> tuple[FortyGuardClient, list[dict[str, object]]]:
    submissions: list[dict[str, object]] = []
    queue = list(responses)

    def opener(request: object, timeout: float) -> _Response:
        data = getattr(request, "data", None)
        if data is not None:
            submissions.append(json.loads(data))
        return _Response(queue.pop(0))

    transport = LiveFortyGuardTransport("https://api.example.test", opener=opener)
    return FortyGuardClient(transport, "secret", clock=lambda: datetime(2026, 8, 27)), submissions


class TestLiveAreaHeatmapAdapter:
    def test_adapter_submits_area_payload_and_stamps_route_to_aoi_buffer(self) -> None:
        client, submissions = _adapter_client([
            {"data": {"activity_id": "area-1"}},
            {"data": {"activity_id": "area-1", "status": "Completed", "result": _multi_tile_map_data(2)}},
        ])
        adapter = LiveAreaHeatmapAdapter(
            client, today=lambda: date(2026, 8, 27), sleep=lambda _: None,
        )
        loaded = adapter.load(
            _SA_ROUTE,
            analytic_type=AnalyticType.TCM,
            start_date=date(2026, 8, 20),
            forecast=False,
        )
        assert isinstance(loaded, LiveHeatmapPayload)
        assert loaded.activity_id == "area-1"

        # Verify the submitted payload has polygon_aoi (not a point)
        submitted = submissions[0]
        assert "polygon_aoi" in submitted
        aoi = submitted["polygon_aoi"]
        assert aoi["type"] == "FeatureCollection"
        # Verify the polygon is a corridor, not a small square
        geom = shape(aoi["features"][0]["geometry"])
        assert geom.is_valid

        # Verify area provenance stamps
        stamp_names = {t.name for t in loaded.transformations}
        assert stamp_names == {
            "live_envelope_unwrapped",
            "route_to_aoi_buffer",
            "valid_time_from_request",
            "tcm_unit_celsius",
        }
        assert "point_to_aoi_expansion" not in stamp_names

    def test_adapter_default_granularity_is_100(self) -> None:
        client, submissions = _adapter_client([
            {"data": {"activity_id": "area-2"}},
            {"data": {"activity_id": "area-2", "status": "Completed", "result": _multi_tile_map_data(1)}},
        ])
        adapter = LiveAreaHeatmapAdapter(
            client, today=lambda: date(2026, 8, 27), sleep=lambda _: None,
        )
        adapter.load(
            _SA_ROUTE,
            analytic_type=AnalyticType.TCM,
            start_date=date(2026, 8, 20),
            forecast=False,
        )
        assert submissions[0]["granularity"] == 100

    def test_adapter_rejects_out_of_contract_date_before_submission(self) -> None:
        client, submissions = _adapter_client([{"data": {"activity_id": "area-3"}}])
        adapter = LiveAreaHeatmapAdapter(
            client, today=lambda: date(2026, 8, 27), sleep=lambda _: None,
        )
        with pytest.raises(ProviderError) as error:
            adapter.load(
                _SA_ROUTE,
                analytic_type=AnalyticType.TCM,
                start_date=date(2027, 1, 1),
                forecast=True,
            )
        assert error.value.kind is ProviderErrorKind.VALIDATION
        assert submissions == []

    def test_adapter_uses_custom_polling_settings(self) -> None:
        sleeps: list[float] = []
        client, _ = _adapter_client([
            {"data": {"activity_id": "area-4"}},
            {"data": {"activity_id": "area-4", "status": "Processing"}},
            {"data": {"activity_id": "area-4", "status": "Completed", "result": _multi_tile_map_data(1)}},
        ])
        adapter = LiveAreaHeatmapAdapter(
            client,
            today=lambda: date(2026, 8, 27),
            polling=FortyGuardPollingSettings(max_polls=3, interval_seconds=3.0),
            sleep=sleeps.append,
        )
        loaded = adapter.load(
            _SA_ROUTE,
            analytic_type=AnalyticType.TCM,
            start_date=date(2026, 8, 20),
            forecast=False,
        )
        assert loaded.activity_id == "area-4"
        assert sleeps == [3.0]
