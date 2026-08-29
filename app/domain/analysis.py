"""Local extraction and spatial adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Mapping, Sequence

from pyproj import CRS, Transformer
from shapely.ops import transform
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union


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
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not isinstance(valid_from, str)
        or not isinstance(valid_to, str)
    ):
        raise ValueError("exposure response is missing value or date window")
    if not isinstance(fresh_at, str):
        raise ValueError("exposure response is missing freshness")
    if forecast:
        raise ValueError("historical exposure context cannot be forecast")

    expected_unit = "C" if metric == "tcm" else "hours"
    if payload.get("unit") != expected_unit:
        raise ValueError(f"{metric} exposure must use {expected_unit}")
    return ExposureSummary(
        metric,
        float(value),
        expected_unit,
        threshold_celsius,
        direction,
        source,
        forecast,
        valid_from,
        valid_to,
        fresh_at,
    )


@dataclass(frozen=True)
class SpatialMetadata:
    metric: str | None = None
    unit: str | None = None
    source: str | None = None
    valid_time: str | None = None
    forecast: bool | None = None
    threshold_celsius: float | None = None
    direction: str | None = None
    activity_id: str | None = None
    unit_source: str | None = None
    source_value: float | None = None
    source_unit: str | None = None
    converted: bool | None = None


@dataclass(frozen=True)
class SpatialMatch:
    value: float | None
    coverage: float
    quality: str
    projected_crs: str
    conflict_coverage: float = 0.0
    metadata: SpatialMetadata | None = None


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
    metadata: SpatialMetadata | None = None
    tile_id: str | None = None


@dataclass(frozen=True)
class TileGeometry:
    identity: str
    geometry: BaseGeometry
    value: float
    metadata: SpatialMetadata = SpatialMetadata()


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
    return transform(transformer.transform, geometry)


def _merged_metadata(tiles: Sequence[TileGeometry]) -> SpatialMetadata | None:
    if not tiles:
        return None
    metadata = tiles[0].metadata
    comparable = replace(metadata, source_value=None)
    if any(replace(tile.metadata, source_value=None) != comparable for tile in tiles[1:]):
        return None
    source_value = metadata.source_value
    if any(tile.metadata.source_value != source_value for tile in tiles[1:]):
        source_value = None
    return replace(metadata, source_value=source_value)


def join_polygon_to_tiles(target: BaseGeometry, tiles: Sequence[TileGeometry]) -> SpatialMatch:
    if not target.is_valid or target.is_empty or target.area == 0:
        raise ValueError("target geometry is invalid")
    crs = _local_crs(target)
    projected_target = _project(target, crs)
    intersections: list[tuple[BaseGeometry, float, TileGeometry]] = []
    for tile in _unique_tiles(tiles):
        if not tile.geometry.is_valid or tile.geometry.is_empty:
            raise ValueError(f"tile {tile.identity} geometry is invalid")
        intersection = projected_target.intersection(_project(tile.geometry, crs))
        if intersection.area > 0:
            intersections.append((intersection, tile.value, tile))
    if not intersections:
        return SpatialMatch(None, 0.0, "no_overlap", crs.to_string())
    covered = unary_union([intersection for intersection, _, _ in intersections])
    weighted_value = 0.0
    weighted_source_value = 0.0
    has_aggregate_source_value = True
    conflict_area = 0.0
    for region in _coverage_regions([(i, v) for i, v, _ in intersections]):
        covering_tiles = [
            (value, tile)
            for intersection, value, tile in intersections
            if intersection.covers(region.representative_point())
        ]
        covering_values = [value for value, _ in covering_tiles]
        if len(set(covering_values)) > 1:
            conflict_area += region.area
        else:
            weighted_value += covering_values[0] * region.area
            source_value = covering_tiles[0][1].metadata.source_value
            if source_value is None or any(
                tile.metadata.source_value != source_value for _, tile in covering_tiles[1:]
            ):
                has_aggregate_source_value = False
            else:
                weighted_source_value += source_value * region.area
    coverage = min(1.0, max(0.0, covered.area / projected_target.area))
    conflict_coverage = min(1.0, max(0.0, conflict_area / projected_target.area))
    if conflict_area > 0:
        return SpatialMatch(
            None,
            coverage,
            "conflicting_overlap",
            crs.to_string(),
            conflict_coverage,
        )
    quality = "complete" if coverage >= 0.95 else "partial"
    metadata = _merged_metadata([tile for _, _, tile in intersections])
    if metadata is None:
        return SpatialMatch(None, coverage, "mixed_provenance", crs.to_string())
    if has_aggregate_source_value:
        metadata = replace(metadata, source_value=weighted_source_value / covered.area)
    return SpatialMatch(
        weighted_value / covered.area,
        coverage,
        quality,
        crs.to_string(),
        metadata=metadata,
    )


def _coverage_regions(intersections: Sequence[tuple[BaseGeometry, float]]) -> list[BaseGeometry]:
    covered = unary_union([intersection for intersection, _ in intersections])
    boundaries = unary_union([intersection.boundary for intersection, _ in intersections])
    return [
        region for region in polygonize(boundaries) if covered.covers(region.representative_point())
    ]


def _unique_tiles(tiles: Sequence[TileGeometry]) -> list[TileGeometry]:
    unique: list[TileGeometry] = []
    identities: dict[str, TileGeometry] = {}
    for tile in tiles:
        existing = identities.get(tile.identity)
        if existing is not None and (
            not existing.geometry.equals(tile.geometry)
            or existing.value != tile.value
            or existing.metadata != tile.metadata
        ):
            raise ValueError(f"tile {tile.identity} has conflicting duplicates")
        identities[tile.identity] = tile
        if not any(
            existing.geometry.equals(tile.geometry)
            and existing.value == tile.value
            and existing.metadata == tile.metadata
            for existing in unique
        ):
            unique.append(tile)
    return unique


def join_point_to_tiles(
    point: Point,
    tiles: Sequence[TileGeometry],
    *,
    aoi: BaseGeometry,
    nearest_max_distance_m: float | None = None,
) -> PointMatch:
    if nearest_max_distance_m is not None and (
        not math.isfinite(nearest_max_distance_m) or nearest_max_distance_m < 0
    ):
        raise ValueError("nearest fallback distance must be finite and non-negative")
    if not isinstance(point, Point) or not point.is_valid or point.is_empty:
        raise ValueError("point geometry is invalid")
    if not aoi.is_valid or aoi.is_empty or aoi.area == 0:
        raise ValueError("AOI geometry is invalid")
    if not aoi.covers(point):
        return PointMatch(None, "outside_aoi", None)
    boundary_tiles: list[TileGeometry] = []
    containing_tiles: list[TileGeometry] = []
    unique_tiles = _unique_tiles(tiles)
    for tile in unique_tiles:
        if not tile.geometry.is_valid or tile.geometry.is_empty:
            raise ValueError(f"tile {tile.identity} geometry is invalid")
        if tile.geometry.boundary.covers(point):
            boundary_tiles.append(tile)
        if tile.geometry.contains(point):
            containing_tiles.append(tile)
    matched_values = [t.value for t in containing_tiles] + [t.value for t in boundary_tiles]
    all_matched = containing_tiles + boundary_tiles
    if boundary_tiles:
        value = matched_values[0] if len(set(matched_values)) == 1 else None
        metadata = _merged_metadata(all_matched) if value is not None else None
        quality = "mixed_provenance" if value is not None and metadata is None else "boundary"
        return PointMatch(
            value if metadata is not None else None,
            quality,
            0.0,
            metadata,
            min((tile.identity for tile in all_matched), default=None),
        )
    if containing_tiles:
        value = (
            containing_tiles[0].value if len(set(t.value for t in containing_tiles)) == 1 else None
        )
        quality = "containing_tile" if value is not None else "overlapping_tiles"
        metadata = _merged_metadata(containing_tiles) if value is not None else None
        if value is not None and metadata is None:
            return PointMatch(None, "mixed_provenance", 0.0)
        return PointMatch(
            value, quality, 0.0, metadata, min(tile.identity for tile in containing_tiles)
        )
    if nearest_max_distance_m is None or not unique_tiles:
        return PointMatch(None, "no_match", None)
    crs = _local_crs(point)
    projected_point = _project(point, crs)
    distances = [
        (tile, projected_point.distance(_project(tile.geometry, crs))) for tile in unique_tiles
    ]
    distance = min(candidate_distance for _, candidate_distance in distances)
    if distance <= nearest_max_distance_m:
        nearest_tiles = [
            tile
            for tile, candidate_distance in distances
            if math.isclose(candidate_distance, distance, abs_tol=1e-6)
        ]
        nearest_values = {tile.value for tile in nearest_tiles}
        if len(nearest_values) > 1:
            return PointMatch(None, "nearest_fallback_ambiguous", distance)
        metadata = _merged_metadata(nearest_tiles)
        if metadata is None:
            return PointMatch(None, "mixed_provenance", distance)
        return PointMatch(
            nearest_values.pop(),
            "nearest_fallback",
            distance,
            metadata,
            min(tile.identity for tile in nearest_tiles),
        )
    return PointMatch(None, "no_match", distance)


def build_aoi(points: Sequence[Point], *, buffer_m: float, corridor: bool = False) -> BaseGeometry:
    if not points or buffer_m <= 0:
        raise ValueError("AOI requires points and a positive buffer")
    if corridor and len(points) < 2:
        raise ValueError("corridor AOI requires at least two points")
    source: BaseGeometry = LineString(points) if len(points) > 1 else points[0]
    if not corridor and len(points) > 1:
        source = source.convex_hull
    crs = _local_crs(source)
    projected = _project(source, crs).buffer(buffer_m)
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return transform(inverse.transform, projected)
