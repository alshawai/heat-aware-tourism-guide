import math
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from app.domain.analysis import (
    SpatialMetadata,
    TileGeometry,
    build_aoi,
    join_point_to_tiles,
    join_polygon_to_tiles,
)
from app.integrations.fortyguard.contracts import (
    AnalyticType,
    HeatmapRequest,
    normalize_heatmap_response,
)


def test_polygon_join_area_weights_partial_overlap_in_projected_crs() -> None:
    target = Polygon([(-98.50, 29.42), (-98.48, 29.42), (-98.48, 29.44), (-98.50, 29.44)])
    tiles = [
        TileGeometry(
            "west",
            Polygon([(-98.50, 29.42), (-98.49, 29.42), (-98.49, 29.44), (-98.50, 29.44)]),
            30,
        ),
        TileGeometry(
            "east-half",
            Polygon([(-98.49, 29.42), (-98.485, 29.42), (-98.485, 29.44), (-98.49, 29.44)]),
            40,
        ),
    ]
    result = join_polygon_to_tiles(target, tiles)
    assert result.value == pytest.approx(100 / 3, rel=0.01)
    assert result.coverage == pytest.approx(0.75, rel=0.01)
    assert result.quality == "partial"
    assert result.projected_crs.startswith("EPSG:326")


def test_polygon_join_rejects_invalid_geometry_and_reports_no_overlap() -> None:
    invalid = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    with pytest.raises(ValueError, match="invalid"):
        join_polygon_to_tiles(invalid, [])
    target = Polygon([(-98.5, 29.42), (-98.49, 29.42), (-98.49, 29.43), (-98.5, 29.43)])
    distant = TileGeometry("far", Polygon([(-97, 30), (-96.9, 30), (-96.9, 30.1), (-97, 30.1)]), 30)
    assert join_polygon_to_tiles(target, [distant]).quality == "no_overlap"


def test_point_join_distinguishes_containing_boundary_and_nearest_fallback() -> None:
    tile = TileGeometry(
        "tile", Polygon([(-98.50, 29.42), (-98.49, 29.42), (-98.49, 29.43), (-98.50, 29.43)]), 35
    )
    aoi = Polygon([(-98.51, 29.41), (-98.48, 29.41), (-98.48, 29.44), (-98.51, 29.44)])
    assert join_point_to_tiles(Point(-98.495, 29.425), [tile], aoi=aoi).quality == "containing_tile"
    assert join_point_to_tiles(Point(-98.50, 29.425), [tile], aoi=aoi).quality == "boundary"
    fallback = join_point_to_tiles(
        Point(-98.4899, 29.425), [tile], aoi=aoi, nearest_max_distance_m=20
    )
    assert fallback.quality == "nearest_fallback"
    assert fallback.distance_m is not None and fallback.distance_m > 0
    assert (
        join_point_to_tiles(
            Point(-98.40, 29.425), [tile], aoi=aoi, nearest_max_distance_m=20
        ).quality
        == "outside_aoi"
    )
    assert join_point_to_tiles(Point(-98.485, 29.425), [tile], aoi=aoi).quality == "no_match"


@pytest.mark.parametrize("distance", [-1, float("nan"), float("inf"), float("-inf")])  # type: ignore[misc]
def test_point_join_rejects_invalid_nearest_fallback_distance(distance: float) -> None:
    aoi = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    with pytest.raises(ValueError, match="fallback distance"):
        join_point_to_tiles(Point(1, 1), [], aoi=aoi, nearest_max_distance_m=distance)


def test_point_join_allows_zero_nearest_fallback_distance() -> None:
    aoi = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    result = join_point_to_tiles(Point(1, 1), [], aoi=aoi, nearest_max_distance_m=0)
    assert result.quality == "no_match"


def test_point_outside_aoi_does_not_match_an_extending_tile() -> None:
    tile = TileGeometry(
        "wide", Polygon([(-98.6, 29.3), (-98.3, 29.3), (-98.3, 29.6), (-98.6, 29.6)]), 35
    )
    aoi = Polygon([(-98.5, 29.4), (-98.4, 29.4), (-98.4, 29.5), (-98.5, 29.5)])
    assert join_point_to_tiles(Point(-98.55, 29.45), [tile], aoi=aoi).quality == "outside_aoi"


def test_point_join_rejects_invalid_aoi() -> None:
    invalid = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    with pytest.raises(ValueError, match="AOI"):
        join_point_to_tiles(Point(0.5, 0.5), [], aoi=invalid)


def test_point_join_rejects_non_point_input() -> None:
    aoi = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    with pytest.raises(ValueError, match="point"):
        join_point_to_tiles(Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]), [], aoi=aoi)


def test_point_on_shared_boundary_reports_boundary_without_hiding_ambiguity() -> None:
    west = TileGeometry("west", Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]), 30)
    east = TileGeometry("east", Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]), 40)
    result = join_point_to_tiles(
        Point(1, 0.5), [west, east], aoi=Polygon([(0, 0), (2, 0), (2, 1), (0, 1)])
    )
    assert result.quality == "boundary"
    assert result.value is None


def test_point_in_overlapping_tiles_is_order_independent_and_exposes_ambiguity() -> None:
    first = TileGeometry("first", Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]), 30)
    second = TileGeometry("second", Polygon([(1, 0), (3, 0), (3, 2), (1, 2)]), 40)
    aoi = Polygon([(0, 0), (3, 0), (3, 2), (0, 2)])
    forward = join_point_to_tiles(Point(1.5, 1), [first, second], aoi=aoi)
    reverse = join_point_to_tiles(Point(1.5, 1), [second, first], aoi=aoi)
    assert forward == reverse
    assert forward.quality == "overlapping_tiles"
    assert forward.value is None


def test_point_inside_one_tile_and_on_another_boundary_reports_boundary() -> None:
    containing = TileGeometry("containing", Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]), 30)
    adjoining = TileGeometry("adjoining", Polygon([(1, 0), (3, 0), (3, 1), (1, 1)]), 40)
    aoi = Polygon([(0, 0), (3, 0), (3, 2), (0, 2)])
    result = join_point_to_tiles(Point(1.5, 1), [containing, adjoining], aoi=aoi)
    assert result.quality == "boundary"
    assert result.value is None


def test_equidistant_nearest_fallback_exposes_conflicting_values() -> None:
    geometry = Polygon([(0.001, 0), (0.002, 0), (0.002, 0.001), (0.001, 0.001)])
    west = TileGeometry("first", geometry, 30)
    east = TileGeometry("second", geometry, 40)
    aoi = Polygon([(-0.01, -0.01), (0.01, -0.01), (0.01, 0.01), (-0.01, 0.01)])
    forward = join_point_to_tiles(
        Point(0, 0.0005), [west, east], aoi=aoi, nearest_max_distance_m=200
    )
    reverse = join_point_to_tiles(
        Point(0, 0.0005), [east, west], aoi=aoi, nearest_max_distance_m=200
    )
    assert forward == reverse
    assert forward.quality == "nearest_fallback_ambiguous"
    assert forward.value is None


def test_point_join_rejects_empty_tile_geometry() -> None:
    empty = TileGeometry("empty", Polygon(), 35)
    aoi = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    with pytest.raises(ValueError, match="tile empty"):
        join_point_to_tiles(Point(0.5, 0.5), [empty], aoi=aoi, nearest_max_distance_m=10)


def test_build_aoi_handles_district_points_and_route_corridors() -> None:
    district = build_aoi([Point(-98.50, 29.42), Point(-98.49, 29.43)], buffer_m=100)
    corridor = build_aoi([Point(-98.50, 29.42), Point(-98.49, 29.43)], buffer_m=25, corridor=True)
    assert district.is_valid and corridor.is_valid
    assert district.area > corridor.area


def test_build_aoi_buffers_one_landmark_and_rejects_one_point_corridor() -> None:
    landmark = build_aoi([Point(-98.49, 29.42)], buffer_m=100)
    assert landmark.is_valid and landmark.area > 0
    with pytest.raises(ValueError, match="two points"):
        build_aoi([Point(-98.49, 29.42)], buffer_m=25, corridor=True)


def test_normalized_result_provides_point_and_polygon_lookup() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-98.5, 29.42],
                                [-98.49, 29.42],
                                [-98.49, 29.43],
                                [-98.5, 29.43],
                                [-98.5, 29.42],
                            ]
                        ],
                    },
                    "properties": {
                        "value": 35,
                        "unit": "C",
                        "valid_time": "2026-08-23T15:00:00+00:00",
                    },
                }
            ]
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
    )
    aoi = Polygon([(-98.5, 29.42), (-98.49, 29.42), (-98.49, 29.43), (-98.5, 29.43)])
    assert result.point_lookup(Point(-98.495, 29.425), aoi=aoi).quality == "containing_tile"
    joined = result.polygon_lookup(
        Polygon([(-98.5, 29.42), (-98.49, 29.42), (-98.49, 29.43), (-98.5, 29.42)])
    )
    assert joined.value == pytest.approx(35)
    assert joined.coverage == pytest.approx(1)


def test_point_lookup_carries_tile_metadata_to_result() -> None:
    request = HeatmapRequest(
        AnalyticType.TCM,
        29.4241,
        -98.4936,
        date.today(),
        threshold_celsius=None,
        direction=None,
    )
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-98.5, 29.42],
                                [-98.49, 29.42],
                                [-98.49, 29.43],
                                [-98.5, 29.43],
                                [-98.5, 29.42],
                            ]
                        ],
                    },
                    "properties": {
                        "value": 35,
                        "unit": "C",
                        "valid_time": "2026-08-23T15:00:00+00:00",
                    },
                }
            ]
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
        activity_id="act-1",
    )
    aoi = Polygon([(-98.5, 29.42), (-98.49, 29.42), (-98.49, 29.43), (-98.5, 29.43)])
    match = result.point_lookup(Point(-98.495, 29.425), aoi=aoi)
    assert match.quality == "containing_tile"
    assert match.value == 35
    assert match.metadata is not None
    assert match.metadata.metric == "tcm"
    assert match.metadata.unit == "C"
    assert match.metadata.source == "provider"
    assert match.metadata.valid_time is not None
    assert match.metadata.forecast is True
    assert match.metadata.activity_id == "act-1"
    assert match.metadata.unit_source == "explicit"
    assert match.metadata.source_value == 35
    assert match.metadata.source_unit == "C"
    assert match.metadata.converted is False


def test_polygon_lookup_carries_tile_metadata_to_result() -> None:
    request = HeatmapRequest(
        AnalyticType.EXCEEDANCE,
        29.4241,
        -98.4936,
        date(2026, 8, 23),
        forecast=False,
        threshold_celsius=35,
        direction="above",
    )
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-98.5, 29.42],
                                [-98.49, 29.42],
                                [-98.49, 29.43],
                                [-98.5, 29.43],
                                [-98.5, 29.42],
                            ]
                        ],
                    },
                    "properties": {
                        "value": 6,
                        "unit": "hours",
                        "valid_time": "2026-08-23T15:00:00+00:00",
                    },
                }
            ]
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
    )
    target = Polygon([(-98.5, 29.42), (-98.49, 29.42), (-98.49, 29.43), (-98.5, 29.43)])
    match = result.polygon_lookup(target)
    assert match.value == pytest.approx(6)
    assert match.quality == "complete"
    assert match.metadata is not None
    assert match.metadata.metric == "exceedance"
    assert match.metadata.unit == "hours"
    assert match.metadata.forecast is False
    assert match.metadata.threshold_celsius == 35
    assert match.metadata.direction == "above"


def test_lookup_preserves_inferred_and_converted_unit_provenance() -> None:
    request = HeatmapRequest(AnalyticType.TCM, 29.4241, -98.4936, date.today())
    result = normalize_heatmap_response(
        {
            "features": [
                {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-98.5, 29.42],
                                [-98.49, 29.42],
                                [-98.49, 29.43],
                                [-98.5, 29.43],
                                [-98.5, 29.42],
                            ]
                        ],
                    },
                    "properties": {
                        "temperature": 95,
                        "valid_time": "2026-08-23T15:00:00+00:00",
                    },
                }
            ]
        },
        request=request,
        retrieved_at=datetime.now(timezone.utc),
        inferred_unit="F",
    )
    aoi = Polygon([(-98.5, 29.42), (-98.49, 29.42), (-98.49, 29.43), (-98.5, 29.43)])
    match = result.point_lookup(Point(-98.495, 29.425), aoi=aoi)

    assert match.metadata is not None
    assert match.metadata.unit_source == "inferred"
    assert match.metadata.source_value == 95
    assert match.metadata.source_unit == "F"
    assert match.metadata.converted is True


def test_polygon_join_rejects_mixed_contributor_provenance_regardless_of_order() -> None:
    target = Polygon([(0, 0), (2, 0), (2, 1), (0, 1)])
    earlier = SpatialMetadata(valid_time="2026-08-23T15:00:00+00:00")
    later = SpatialMetadata(valid_time="2026-08-23T16:00:00+00:00")
    west = TileGeometry("west", Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]), 30, earlier)
    east = TileGeometry("east", Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]), 30, later)

    forward = join_polygon_to_tiles(target, [west, east])
    reverse = join_polygon_to_tiles(target, [east, west])

    assert forward == reverse
    assert forward.quality == "mixed_provenance"
    assert forward.value is None
    assert forward.metadata is None


def test_polygon_join_aggregates_distinct_source_values_with_shared_provenance() -> None:
    target = Polygon([(0, 0), (2, 0), (2, 1), (0, 1)])
    shared = SpatialMetadata(
        valid_time="2026-08-23T15:00:00+00:00",
        source_unit="F",
        converted=True,
    )
    west = TileGeometry(
        "west",
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        30,
        replace(shared, source_value=86),
    )
    east = TileGeometry(
        "east",
        Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        40,
        replace(shared, source_value=104),
    )

    result = join_polygon_to_tiles(target, [west, east])

    assert result.value == pytest.approx(35, rel=0.01)
    assert result.metadata is not None
    assert replace(result.metadata, source_value=None) == shared
    assert result.metadata.source_value == pytest.approx(95, rel=0.01)


def test_point_join_rejects_equal_values_with_mixed_provenance() -> None:
    geometry = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    first = TileGeometry(
        "first",
        geometry,
        30,
        SpatialMetadata(valid_time="2026-08-23T15:00:00+00:00"),
    )
    second = TileGeometry(
        "second",
        geometry,
        30,
        SpatialMetadata(valid_time="2026-08-23T16:00:00+00:00"),
    )

    match = join_point_to_tiles(
        Point(1, 1),
        [first, second],
        aoi=geometry,
    )

    assert match.quality == "mixed_provenance"
    assert match.value is None
    assert match.metadata is None


def test_polygon_join_does_not_double_count_duplicate_tiles() -> None:
    target = Polygon([(-98.5, 29.42), (-98.48, 29.42), (-98.48, 29.44), (-98.5, 29.44)])
    west = Polygon([(-98.5, 29.42), (-98.49, 29.42), (-98.49, 29.44), (-98.5, 29.44)])
    result = join_polygon_to_tiles(
        target,
        [TileGeometry("west-1", west, 30), TileGeometry("west-2", west, 40)],
    )
    assert result.coverage == pytest.approx(0.5, rel=0.01)
    assert result.value is None
    assert result.quality == "conflicting_overlap"
    assert result.conflict_coverage == pytest.approx(0.5, rel=0.01)
    assert 0 <= result.coverage <= 1


def test_polygon_join_duplicate_does_not_bias_an_overlapping_pair() -> None:
    target = Polygon([(0, 0), (3, 0), (3, 2), (0, 2)])
    first = TileGeometry("first", Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]), 30)
    second = TileGeometry("second", Polygon([(1, 0), (3, 0), (3, 2), (1, 2)]), 40)
    duplicate = TileGeometry("duplicate", first.geometry, first.value)
    baseline = join_polygon_to_tiles(target, [first, second])
    duplicated = join_polygon_to_tiles(target, [first, second, duplicate])
    assert duplicated.value == pytest.approx(baseline.value)
    assert duplicated.coverage == pytest.approx(baseline.coverage)


def test_polygon_join_exposes_conflicting_overlap_without_synthetic_average() -> None:
    target = Polygon([(0, 0), (3, 0), (3, 2), (0, 2)])
    first = TileGeometry("first", Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]), 30)
    second = TileGeometry("second", Polygon([(1, 0), (3, 0), (3, 2), (1, 2)]), 40)
    result = join_polygon_to_tiles(target, [first, second])
    assert result.value is None
    assert result.quality == "conflicting_overlap"
    assert result.coverage == pytest.approx(1, rel=0.001)
    assert result.conflict_coverage == pytest.approx(1 / 3, rel=0.01)


def test_polygon_join_handles_target_hole_without_counting_uncovered_hole() -> None:
    target = Polygon(
        [(0, 0), (4, 0), (4, 4), (0, 4)],
        holes=[[(1, 1), (3, 1), (3, 3), (1, 3)]],
    )
    tile = TileGeometry("donut", target, 35)
    result = join_polygon_to_tiles(target, [tile])
    assert result.value == pytest.approx(35)
    assert result.coverage == pytest.approx(1)
    assert result.conflict_coverage == 0


def test_polygon_join_exposes_conflicting_multipolygon_overlap() -> None:
    west = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    east = Polygon([(3, 0), (5, 0), (5, 2), (3, 2)])
    target = MultiPolygon([west, east])
    base = TileGeometry("base", target, 30)
    conflicting = TileGeometry(
        "conflict", MultiPolygon([Polygon([(1, 0), (2, 0), (2, 2), (1, 2)])]), 40
    )
    result = join_polygon_to_tiles(target, [base, conflicting])
    assert result.value is None
    assert result.quality == "conflicting_overlap"
    assert result.coverage == pytest.approx(1)
    assert 0 < result.conflict_coverage < 1
    assert math.isfinite(result.conflict_coverage)


def test_polygon_join_deduplicates_topologically_equivalent_rings() -> None:
    target = Polygon([(0, 0), (3, 0), (3, 2), (0, 2)])
    first = TileGeometry("first", Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]), 30)
    reversed_ring = TileGeometry("reversed", Polygon([(2, 2), (2, 0), (0, 0), (0, 2)]), 30)
    second = TileGeometry("second", Polygon([(1, 0), (3, 0), (3, 2), (1, 2)]), 40)
    baseline = join_polygon_to_tiles(target, [first, second])
    duplicated = join_polygon_to_tiles(target, [first, reversed_ring, second])
    assert duplicated == baseline


def test_polygon_join_deduplicates_equivalent_geometry_with_extra_vertex() -> None:
    target = Polygon([(0, 0), (3, 0), (3, 2), (0, 2)])
    first = TileGeometry("first", Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]), 30)
    extra_vertex = TileGeometry("extra", Polygon([(0, 0), (1, 0), (2, 0), (2, 2), (0, 2)]), 30)
    second = TileGeometry("second", Polygon([(1, 0), (3, 0), (3, 2), (1, 2)]), 40)
    assert join_polygon_to_tiles(target, [first, extra_vertex, second]) == join_polygon_to_tiles(
        target, [first, second]
    )


def test_polygon_join_rejects_conflicting_duplicate_identity() -> None:
    target = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    tiles = [
        TileGeometry("same", target, 30),
        TileGeometry("same", Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]), 40),
    ]
    with pytest.raises(ValueError, match="conflicting"):
        join_polygon_to_tiles(target, tiles)
