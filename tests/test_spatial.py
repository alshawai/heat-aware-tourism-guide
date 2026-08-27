import pytest
from shapely.geometry import Point, Polygon

from app.domain.analysis import TileGeometry, build_aoi, join_point_to_tiles, join_polygon_to_tiles


def test_polygon_join_area_weights_partial_overlap_in_projected_crs() -> None:
    target = Polygon([(-98.50, 29.42), (-98.48, 29.42), (-98.48, 29.44), (-98.50, 29.44)])
    tiles = [
        TileGeometry("west", Polygon([(-98.50, 29.42), (-98.49, 29.42), (-98.49, 29.44), (-98.50, 29.44)]), 30),
        TileGeometry("east-half", Polygon([(-98.49, 29.42), (-98.485, 29.42), (-98.485, 29.44), (-98.49, 29.44)]), 40),
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
    tile = TileGeometry("tile", Polygon([(-98.50, 29.42), (-98.49, 29.42), (-98.49, 29.43), (-98.50, 29.43)]), 35)
    assert join_point_to_tiles(Point(-98.495, 29.425), [tile]).quality == "containing_tile"
    assert join_point_to_tiles(Point(-98.50, 29.425), [tile]).quality == "boundary"
    fallback = join_point_to_tiles(Point(-98.4899, 29.425), [tile], nearest_max_distance_m=20)
    assert fallback.quality == "nearest_fallback"
    assert fallback.distance_m is not None and fallback.distance_m > 0
    assert join_point_to_tiles(Point(-98.40, 29.425), [tile], nearest_max_distance_m=20).quality == "outside_aoi"


def test_build_aoi_handles_district_points_and_route_corridors() -> None:
    district = build_aoi([Point(-98.50, 29.42), Point(-98.49, 29.43)], buffer_m=100)
    corridor = build_aoi([Point(-98.50, 29.42), Point(-98.49, 29.43)], buffer_m=25, corridor=True)
    assert district.is_valid and corridor.is_valid
    assert district.area > corridor.area
