"""Shared returned-route AOI construction and conservative heat aggregation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import math
from typing import Mapping

from pyproj import CRS, Transformer
from shapely.geometry import LineString, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from app.domain.routing import RouteSet
from app.integrations.fortyguard.contracts import AnalyticType, HeatmapResult


@dataclass(frozen=True)
class SharedRouteHeatRequest:
    geometry: Mapping[str, object]
    start_date: date
    hour: int
    forecast: bool
    granularity: int
    buffer_m: float
    provider_instance: str
    request_version: str

    def __post_init__(self) -> None:
        polygon = shape(dict(self.geometry))
        if polygon.geom_type != "Polygon" or not polygon.is_valid or polygon.is_empty:
            raise ValueError("shared route heat geometry must be a valid polygon")
        if isinstance(self.hour, bool) or not isinstance(self.hour, int) or not 0 <= self.hour <= 23:
            raise ValueError("shared route heat hour must be between 0 and 23")
        if not isinstance(self.forecast, bool):
            raise ValueError("shared route heat forecast must be boolean")
        if self.granularity not in (60, 80, 100):
            raise ValueError("shared route heat granularity must be 60, 80, or 100")
        if not math.isfinite(self.buffer_m) or self.buffer_m <= 0:
            raise ValueError("shared route heat buffer must be positive and finite")
        if not self.provider_instance.strip() or not self.request_version.strip():
            raise ValueError("shared route heat provider and request version are required")

    def to_payload(self) -> dict[str, object]:
        return {
            "geometry": dict(self.geometry),
            "analytic_type": AnalyticType.TCM.value,
            "start_date": self.start_date.isoformat(),
            "hour": self.hour,
            "forecast": self.forecast,
            "granularity": self.granularity,
            "buffer_m": self.buffer_m,
            "provider_instance": self.provider_instance,
            "request_version": self.request_version,
        }


@dataclass(frozen=True)
class RouteHeatEvidence:
    route_id: str
    maximum_tcm_celsius: float | None
    coverage: float
    sufficient: bool
    tile_count: int

    def with_minimum_coverage(self, minimum_coverage: float) -> "RouteHeatEvidence":
        _validate_coverage_threshold(minimum_coverage)
        sufficient = self.coverage >= minimum_coverage and self.tile_count > 0
        return replace(
            self,
            maximum_tcm_celsius=self.maximum_tcm_celsius if sufficient else None,
            sufficient=sufficient,
        )


def build_shared_route_aoi(
    routes: RouteSet, *, buffer_m: float
) -> dict[str, object]:
    """Return a canonical buffered WGS84 rectangle covering every returned route."""
    if not math.isfinite(buffer_m) or buffer_m <= 0:
        raise ValueError("shared route AOI buffer must be positive and finite")
    lines = [LineString(route.geometry.coordinates) for route in routes.routes]
    merged = unary_union(lines)
    crs = _local_crs(merged)
    projected = _project(merged, crs)
    rectangle = projected.envelope.buffer(buffer_m, cap_style="square", join_style="mitre").envelope
    wgs84 = _unproject(rectangle, crs)
    min_x, min_y, max_x, max_y = wgs84.bounds
    ring = [
        [round(min_x, 9), round(min_y, 9)],
        [round(max_x, 9), round(min_y, 9)],
        [round(max_x, 9), round(max_y, 9)],
        [round(min_x, 9), round(max_y, 9)],
        [round(min_x, 9), round(min_y, 9)],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def aggregate_shared_route_heat(
    routes: RouteSet,
    heatmap: HeatmapResult,
    *,
    buffer_m: float,
    minimum_coverage: float,
    selected_hour: int | None = None,
) -> tuple[RouteHeatEvidence, ...]:
    """Use maximum intersecting TCM and independent projected coverage per route."""
    _validate_coverage_threshold(minimum_coverage)
    if not math.isfinite(buffer_m) or buffer_m <= 0:
        raise ValueError("route heat buffer must be positive and finite")
    if not heatmap.tiles:
        raise ValueError("route heat requires normalized tiles")
    if any(tile.metric is not AnalyticType.TCM for tile in heatmap.tiles):
        raise ValueError("route heat requires TCM tiles")
    if selected_hour is not None and any(
        tile.valid_time.hour != selected_hour for tile in heatmap.tiles
    ):
        raise ValueError("route heat tiles must match the selected hour")

    all_lines = unary_union(
        [LineString(route.geometry.coordinates) for route in routes.routes]
    )
    crs = _local_crs(all_lines)
    projected_tiles: list[tuple[BaseGeometry, float]] = []
    for tile in heatmap.tiles:
        if tile.value_celsius is None:
            continue
        geometry = shape(dict(tile.geometry))
        if not geometry.is_valid or geometry.is_empty:
            raise ValueError(f"tile {tile.identity} geometry is invalid")
        projected_tiles.append((_project(geometry, crs), tile.value_celsius))

    evidence: list[RouteHeatEvidence] = []
    for route in routes.routes:
        corridor = _project(LineString(route.geometry.coordinates), crs).buffer(buffer_m)
        intersections = [
            (corridor.intersection(tile), value)
            for tile, value in projected_tiles
            if corridor.intersects(tile)
        ]
        usable = [(intersection, value) for intersection, value in intersections if intersection.area > 0]
        covered = unary_union([intersection for intersection, _ in usable]) if usable else None
        coverage = (
            min(1.0, max(0.0, covered.area / corridor.area))
            if covered is not None and corridor.area > 0
            else 0.0
        )
        sufficient = coverage >= minimum_coverage and bool(usable)
        evidence.append(
            RouteHeatEvidence(
                route.identity,
                max(value for _, value in usable) if sufficient else None,
                coverage,
                sufficient,
                len(usable),
            )
        )
    return tuple(evidence)


def _validate_coverage_threshold(value: float) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("minimum route heat coverage must be between 0 and 1")


def _local_crs(geometry: BaseGeometry) -> CRS:
    centroid = geometry.centroid
    zone = int((centroid.x + 180) // 6) + 1
    return CRS.from_epsg((32600 if centroid.y >= 0 else 32700) + zone)


def _project(geometry: BaseGeometry, crs: CRS) -> BaseGeometry:
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return transform(transformer.transform, geometry)


def _unproject(geometry: BaseGeometry, crs: CRS) -> BaseGeometry:
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return transform(transformer.transform, geometry)
