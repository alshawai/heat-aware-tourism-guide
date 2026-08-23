"""Local extraction and spatial adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from pyproj import CRS, Transformer
from shapely import transform
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class ExposureSummary:
    metric: str
    value: float
    unit: str
    threshold_celsius: float
    direction: str
    source: str
    forecast: bool
    valid_from: str
    valid_to: str
    fresh_at: str
    role: str = "supporting_context"


def extract_exposure(
    payload: Mapping[str, object],
    *,
    metric: str,
    threshold_celsius: float,
    direction: str,
    source: str,
    forecast: bool,
) -> ExposureSummary:
    value = payload.get("value")
    valid_from = payload.get("valid_from")
    valid_to = payload.get("valid_to")
    fresh_at = payload.get("fresh_at")
    if not isinstance(value, (int, float)) or not isinstance(valid_from, str) or not isinstance(valid_to, str):
        raise ValueError("exposure response is missing value or date window")
    if not isinstance(fresh_at, str):
        raise ValueError("exposure response is missing freshness")
    if forecast:
        raise ValueError("historical exposure context cannot be forecast")
    if payload.get("unit") != "C":
        raise ValueError("exposure must use Celsius")
    return ExposureSummary(metric, float(value), "C", threshold_celsius, direction, source, forecast, valid_from, valid_to, fresh_at)


@dataclass(frozen=True)
class SpatialMatch:
    value: float | None
    coverage: float
    quality: str
    projected_crs: str


def polygon_join_contract(
    tile_values: Sequence[tuple[float, float]],
    *,
    coverage: float,
    projected_crs: str,
) -> SpatialMatch:
    """Represent results from a projected, area-weighted join supplied by the geospatial adapter."""
    if not projected_crs or projected_crs.upper() in {"EPSG:4326", "WGS84"}:
        raise ValueError("polygon joins require a projected CRS")
    if not 0 <= coverage <= 1:
        raise ValueError("coverage must be between 0 and 1")
    if not tile_values or coverage == 0:
        return SpatialMatch(None, coverage, "no_overlap", projected_crs)
    total_weight = sum(weight for _, weight in tile_values)
    if total_weight <= 0:
        raise ValueError("tile overlap weights must be positive")
    value = sum(tile_value * weight for tile_value, weight in tile_values) / total_weight
    quality = "complete" if coverage >= 0.95 else "partial"
    return SpatialMatch(value, coverage, quality, projected_crs)


@dataclass(frozen=True)
class PointMatch:
    value: float | None
    quality: str
    distance_m: float | None


@dataclass(frozen=True)
class TileGeometry:
    identity: str
    geometry: BaseGeometry
    value: float


def point_join_contract(
    *,
    containing_value: float | None,
    boundary: bool,
    outside_aoi: bool,
    nearest_value: float | None = None,
    nearest_distance_m: float | None = None,
) -> PointMatch:
    if outside_aoi and nearest_value is None:
        return PointMatch(None, "outside_aoi", None)
    if containing_value is not None:
        return PointMatch(containing_value, "boundary" if boundary else "containing_tile", 0.0)
    if nearest_value is not None and nearest_distance_m is not None:
        return PointMatch(nearest_value, "nearest_fallback", nearest_distance_m)
    return PointMatch(None, "no_match", None)


def _local_crs(geometry: BaseGeometry) -> CRS:
    centroid = geometry.centroid
    zone = int((centroid.x + 180) // 6) + 1
    epsg = (32600 if centroid.y >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def _project(geometry: BaseGeometry, crs: CRS) -> BaseGeometry:
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return transform(geometry, transformer.transform, interleaved=False)


def join_polygon_to_tiles(target: BaseGeometry, tiles: Sequence[TileGeometry]) -> SpatialMatch:
    if not target.is_valid or target.is_empty or target.area == 0:
        raise ValueError("target geometry is invalid")
    crs = _local_crs(target)
    projected_target = _project(target, crs)
    weighted_value = 0.0
    overlap_area = 0.0
    for tile in tiles:
        if not tile.geometry.is_valid or tile.geometry.is_empty:
            raise ValueError(f"tile {tile.identity} geometry is invalid")
        intersection_area = projected_target.intersection(_project(tile.geometry, crs)).area
        if intersection_area > 0:
            weighted_value += tile.value * intersection_area
            overlap_area += intersection_area
    if overlap_area == 0:
        return SpatialMatch(None, 0.0, "no_overlap", crs.to_string())
    coverage = min(1.0, overlap_area / projected_target.area)
    quality = "complete" if coverage >= 0.95 else "partial"
    return SpatialMatch(weighted_value / overlap_area, coverage, quality, crs.to_string())


def join_point_to_tiles(
    point: Point,
    tiles: Sequence[TileGeometry],
    *,
    nearest_max_distance_m: float | None = None,
) -> PointMatch:
    if not point.is_valid or point.is_empty:
        raise ValueError("point geometry is invalid")
    for tile in tiles:
        if not tile.geometry.is_valid:
            raise ValueError(f"tile {tile.identity} geometry is invalid")
        if tile.geometry.boundary.covers(point):
            return PointMatch(tile.value, "boundary", 0.0)
        if tile.geometry.contains(point):
            return PointMatch(tile.value, "containing_tile", 0.0)
    if nearest_max_distance_m is None or not tiles:
        return PointMatch(None, "outside_aoi", None)
    crs = _local_crs(point)
    projected_point = _project(point, crs)
    nearest_tile, distance = min(
        ((tile, projected_point.distance(_project(tile.geometry, crs))) for tile in tiles),
        key=lambda match: match[1],
    )
    if distance <= nearest_max_distance_m:
        return PointMatch(nearest_tile.value, "nearest_fallback", distance)
    return PointMatch(None, "outside_aoi", distance)


def build_aoi(points: Sequence[Point], *, buffer_m: float, corridor: bool = False) -> BaseGeometry:
    if not points or buffer_m <= 0:
        raise ValueError("AOI requires points and a positive buffer")
    source: BaseGeometry = LineString(points) if corridor else LineString(points).convex_hull
    crs = _local_crs(source)
    projected = _project(source, crs).buffer(buffer_m)
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return transform(projected, inverse.transform, interleaved=False)
