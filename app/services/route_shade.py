"""One-request OSM building acquisition and per-route modeled shade evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Mapping, cast

from pyproj import Transformer
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from app.domain.hotels import BoundingBox
from app.domain.route_heat import build_shared_route_aoi
from app.domain.route_shade import (
    SHADE_UNAVAILABLE_LIMITATION,
    BuildingFootprint,
    BuildingHeightQuality,
    RouteShadeEvidence,
    ShadeConfidence,
    SolarPosition,
    building_from_geojson,
    route_shade_percent,
    unavailable_shade_evidence,
)
from app.domain.routing import RouteSet
from app.integrations.overpass.errors import OverpassError
from app.services.building_execution import (
    BuildingExecution,
    BuildingOutcome,
    BuildingsUnavailable,
)


@dataclass(frozen=True)
class RouteShadeOutcome:
    """Per-route shade evidence and the building acquisition that produced it."""

    evidence: Mapping[str, RouteShadeEvidence]
    request_identity: Mapping[str, Any]
    metres_per_level: float
    minimum_building_coverage: float
    dropped_geometry_count: int = 0
    building: BuildingOutcome | None = None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if (self.building is None) != (self.unavailable_reason is not None):
            raise ValueError("shade outcomes record either a building source or why none answered")


class RouteShadeService:
    """Acquire one shared building set and derive detailed evidence for each route."""

    def __init__(
        self,
        execution: BuildingExecution,
        *,
        corridor_buffer_m: float = 250.0,
        minimum_building_coverage: float = 0.70,
        metres_per_level: float = 3.0,
    ) -> None:
        if not math.isfinite(corridor_buffer_m) or corridor_buffer_m <= 0:
            raise ValueError("shade corridor buffer must be positive and finite")
        if not math.isfinite(minimum_building_coverage) or not 0 <= minimum_building_coverage <= 1:
            raise ValueError("minimum building coverage must be between zero and one")
        if not math.isfinite(metres_per_level) or metres_per_level <= 0:
            raise ValueError("metres per building level must be positive and finite")
        self._execution = execution
        self._corridor_buffer_m = corridor_buffer_m
        self._minimum_building_coverage = minimum_building_coverage
        self._metres_per_level = metres_per_level

    def load(
        self,
        routes: RouteSet,
        solar: SolarPosition,
        instant: datetime,
    ) -> RouteShadeOutcome:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("shade instant must be timezone-aware")
        aoi = _shared_bbox(routes, self._corridor_buffer_m)
        identity = self._execution.identity(aoi)
        try:
            outcome = self._execution.run(aoi)
            buildings, dropped_geometry_count = _normalize_buildings(
                outcome.payload, metres_per_level=self._metres_per_level
            )
        except (BuildingsUnavailable, OverpassError) as error:
            return RouteShadeOutcome(
                evidence={route.identity: unavailable_shade_evidence() for route in routes.routes},
                request_identity=identity,
                metres_per_level=self._metres_per_level,
                minimum_building_coverage=self._minimum_building_coverage,
                unavailable_reason=str(error) or SHADE_UNAVAILABLE_LIMITATION,
            )
        return RouteShadeOutcome(
            evidence={
                route.identity: self._route_evidence(
                    LineString(route.geometry.coordinates),
                    buildings,
                    solar,
                    dropped_geometry_count,
                )
                for route in routes.routes
            },
            request_identity=identity,
            metres_per_level=self._metres_per_level,
            minimum_building_coverage=self._minimum_building_coverage,
            dropped_geometry_count=dropped_geometry_count,
            building=outcome,
        )

    def _route_evidence(
        self,
        route: LineString,
        buildings: tuple[BuildingFootprint, ...],
        solar: SolarPosition,
        dropped_geometry_count: int,
    ) -> RouteShadeEvidence:
        epsg = _local_epsg(route)
        corridor = _project(route, epsg).buffer(self._corridor_buffer_m)
        projected = tuple((building, _project(building.geometry, epsg)) for building in buildings)
        relevant = tuple(
            (building, geometry)
            for building, geometry in projected
            if geometry.intersects(corridor)
        )
        areas: dict[BuildingHeightQuality, float] = {}
        counts: dict[BuildingHeightQuality, int] = {}
        for quality in BuildingHeightQuality:
            geometries = [
                geometry.intersection(corridor)
                for building, geometry in relevant
                if building.height_quality is quality
            ]
            usable = [geometry for geometry in geometries if geometry.area > 0]
            areas[quality] = float(unary_union(usable).area) if usable else 0.0
            counts[quality] = sum(
                1 for building, _ in relevant if building.height_quality is quality
            )
        total = sum(areas.values())
        fractions = {
            quality: (areas[quality] / total if total > 0 else 0.0)
            for quality in BuildingHeightQuality
        }
        coverage = (
            fractions[BuildingHeightQuality.EXPLICIT]
            + fractions[BuildingHeightQuality.INFERRED_LEVELS]
        )
        confidence = (
            ShadeConfidence.SUFFICIENT
            if coverage >= self._minimum_building_coverage and dropped_geometry_count == 0
            else ShadeConfidence.INSUFFICIENT
        )
        relevant_buildings = tuple(building for building, _ in relevant)
        return RouteShadeEvidence(
            modeled_shade_percent=route_shade_percent(route, relevant_buildings, solar),
            building_coverage=coverage,
            confidence=confidence,
            explicit_area_fraction=fractions[BuildingHeightQuality.EXPLICIT],
            inferred_levels_area_fraction=fractions[BuildingHeightQuality.INFERRED_LEVELS],
            unknown_area_fraction=fractions[BuildingHeightQuality.UNKNOWN],
            explicit_count=counts[BuildingHeightQuality.EXPLICIT],
            inferred_levels_count=counts[BuildingHeightQuality.INFERRED_LEVELS],
            unknown_count=counts[BuildingHeightQuality.UNKNOWN],
            dropped_geometry_count=dropped_geometry_count,
        )


def _shared_bbox(routes: RouteSet, buffer_m: float) -> BoundingBox:
    polygon = build_shared_route_aoi(routes, buffer_m=buffer_m)
    rings = polygon.get("coordinates")
    if not isinstance(rings, list) or not rings or not isinstance(rings[0], list):
        raise ValueError("shared route AOI must be a GeoJSON polygon")
    points = rings[0]
    longitudes = [float(point[0]) for point in points]
    latitudes = [float(point[1]) for point in points]
    return BoundingBox(min(latitudes), min(longitudes), max(latitudes), max(longitudes))


@dataclass(frozen=True)
class _RawBuilding:
    footprint: BuildingFootprint
    is_part: bool


def _normalize_buildings(
    response: Mapping[str, object], *, metres_per_level: float = 3.0
) -> tuple[tuple[BuildingFootprint, ...], int]:
    elements = response.get("elements")
    if not isinstance(elements, list):
        raise OverpassError("Overpass building response elements must be a list")
    raw: list[_RawBuilding] = []
    dropped = 0
    for element in elements:
        if not isinstance(element, Mapping):
            dropped += 1
            continue
        object_type = element.get("type")
        object_id = element.get("id")
        tags = element.get("tags")
        if (
            object_type not in {"way", "relation"}
            or not isinstance(object_id, int)
            or isinstance(object_id, bool)
            or not isinstance(tags, Mapping)
            or ("building" not in tags and "building:part" not in tags)
        ):
            continue
        geometry = _element_geometry(element)
        if geometry is None:
            dropped += 1
            continue
        try:
            footprint = building_from_geojson(
                f"{object_type}/{object_id}",
                geometry,
                tags,
                metres_per_level=metres_per_level,
            )
        except ValueError:
            dropped += 1
            continue
        raw.append(_RawBuilding(footprint, "building:part" in tags))
    return _effective_footprints(raw), dropped


def _element_geometry(element: Mapping[str, object]) -> Mapping[str, object] | None:
    if element.get("type") == "way":
        ring = _ring(element.get("geometry"))
        return {"type": "Polygon", "coordinates": [ring]} if ring is not None else None
    members = element.get("members")
    if not isinstance(members, list):
        return None
    rings = [
        ring
        for member in members
        if isinstance(member, Mapping)
        for ring in [_ring(member.get("geometry"))]
        if ring is not None and member.get("role") != "inner"
    ]
    if not rings:
        return None
    merged = cast(BaseGeometry, unary_union([Polygon(ring) for ring in rings]))
    if merged.geom_type == "Polygon":
        polygon = cast(Polygon, merged)
        return {"type": "Polygon", "coordinates": [list(polygon.exterior.coords)]}
    if merged.geom_type == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [list(polygon.exterior.coords)] for polygon in cast(MultiPolygon, merged).geoms
            ],
        }
    return None


def _ring(value: object) -> list[list[float]] | None:
    if not isinstance(value, list):
        return None
    coordinates: list[list[float]] = []
    for point in value:
        if not isinstance(point, Mapping):
            return None
        latitude, longitude = point.get("lat"), point.get("lon")
        if (
            not isinstance(latitude, (int, float))
            or isinstance(latitude, bool)
            or not math.isfinite(latitude)
            or not -90 <= latitude <= 90
            or not isinstance(longitude, (int, float))
            or isinstance(longitude, bool)
            or not math.isfinite(longitude)
            or not -180 <= longitude <= 180
        ):
            return None
        coordinates.append([float(longitude), float(latitude)])
    if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
        return None
    return coordinates


def _effective_footprints(raw: list[_RawBuilding]) -> tuple[BuildingFootprint, ...]:
    parts = sorted((item.footprint for item in raw if item.is_part), key=lambda item: item.identity)
    parents = sorted(
        (item.footprint for item in raw if not item.is_part), key=lambda item: item.identity
    )
    effective: list[BuildingFootprint] = []
    occupied_parts: BaseGeometry = GeometryCollection()
    for part in parts:
        geometry = part.geometry.difference(occupied_parts)
        if not geometry.is_empty and geometry.geom_type in {"Polygon", "MultiPolygon"}:
            effective.append(
                BuildingFootprint(part.identity, geometry, part.height_m, part.height_quality)
            )
        occupied_parts = occupied_parts.union(part.geometry)
    occupied_parents: BaseGeometry = GeometryCollection()
    for parent in parents:
        geometry = parent.geometry.difference(occupied_parts).difference(occupied_parents)
        if not geometry.is_empty and geometry.geom_type in {"Polygon", "MultiPolygon"}:
            effective.append(
                BuildingFootprint(parent.identity, geometry, parent.height_m, parent.height_quality)
            )
        occupied_parents = occupied_parents.union(parent.geometry)
    return tuple(effective)


def _local_epsg(geometry: BaseGeometry) -> int:
    centroid = geometry.centroid
    zone = int((centroid.x + 180) // 6) + 1
    return 32600 + zone if centroid.y >= 0 else 32700 + zone


def _project(geometry: BaseGeometry, epsg: int) -> BaseGeometry:
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    return transform(transformer.transform, geometry)
