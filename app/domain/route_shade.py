"""Provider-neutral OSM building-height and deterministic route-shade geometry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
import re
from typing import Iterable, Mapping, cast

from pyproj import Transformer
from shapely.geometry import LineString, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union


class BuildingHeightQuality(str, Enum):
    EXPLICIT = "explicit"
    INFERRED_LEVELS = "inferred_levels"
    UNKNOWN = "unknown"


class ShadeConfidence(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    NOT_APPLICABLE = "not_applicable"


SHADE_MODEL_LIMITATIONS = (
    "modeled OSM building shade excludes trees, awnings, clouds, temporary obstructions, "
    "and buildings beyond the configured search boundary"
)


@dataclass(frozen=True)
class RouteShadeEvidence:
    modeled_shade_percent: float
    building_coverage: float
    confidence: ShadeConfidence
    explicit_area_fraction: float
    inferred_levels_area_fraction: float
    unknown_area_fraction: float
    explicit_count: int
    inferred_levels_count: int
    unknown_count: int
    dropped_geometry_count: int
    limitations: tuple[str, ...] = (SHADE_MODEL_LIMITATIONS,)

    def __post_init__(self) -> None:
        if not math.isfinite(self.modeled_shade_percent) or not 0 <= self.modeled_shade_percent <= 100:
            raise ValueError("modeled shade percent must be finite and between 0 and 100")
        fractions = (
            self.explicit_area_fraction,
            self.inferred_levels_area_fraction,
            self.unknown_area_fraction,
        )
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in fractions):
            raise ValueError("building quality fractions must be finite and between 0 and 1")
        if not math.isclose(sum(fractions), 1.0, abs_tol=1e-6) and any(fractions):
            raise ValueError("nonzero building quality fractions must sum to 1")
        if not math.isclose(
            self.building_coverage,
            self.explicit_area_fraction + self.inferred_levels_area_fraction,
            abs_tol=1e-6,
        ):
            raise ValueError("building coverage must equal known-height quality fractions")
        counts = (
            self.explicit_count,
            self.inferred_levels_count,
            self.unknown_count,
            self.dropped_geometry_count,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("building quality and dropped geometry counts must be non-negative")
        if not isinstance(self.confidence, ShadeConfidence):
            raise ValueError("shade confidence must be a ShadeConfidence value")
        if not self.limitations or any(not item.strip() for item in self.limitations):
            raise ValueError("modeled shade limitations are required")


@dataclass(frozen=True)
class BuildingFootprint:
    identity: str
    geometry: BaseGeometry
    height_m: float | None
    height_quality: BuildingHeightQuality

    def __post_init__(self) -> None:
        if not self.identity or self.geometry.is_empty or not self.geometry.is_valid:
            raise ValueError("building identity and valid geometry are required")
        if self.geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError("building geometry must be polygonal")
        if self.height_m is not None and (not math.isfinite(self.height_m) or self.height_m <= 0):
            raise ValueError("building height must be positive and finite")
        if self.height_quality is BuildingHeightQuality.UNKNOWN and self.height_m is not None:
            raise ValueError("unknown building height cannot have a numeric value")
        if self.height_quality is not BuildingHeightQuality.UNKNOWN and self.height_m is None:
            raise ValueError("known building height requires a quality")


@dataclass(frozen=True)
class SolarPosition:
    azimuth_degrees: float
    elevation_degrees: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.azimuth_degrees, self.elevation_degrees)):
            raise ValueError("solar position must be finite")
        if not 0 <= self.azimuth_degrees < 360:
            raise ValueError("solar azimuth must be in [0, 360)")


def parse_height(value: object) -> float | None:
    """Parse one positive OSM height value in metres; reject ambiguous syntax."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text or ";" in text or "-" in text or " to " in text or ".." in text:
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(m|meters?|ft|feet)?", text)
    if match:
        number = float(match.group(1))
        unit = match.group(2) or "m"
        metres = number * 0.3048 if unit in {"ft", "feet"} else number
    else:
        feet_inches = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*'\s*([0-9]+(?:\.[0-9]+)?)?\s*\"", text)
        if not feet_inches:
            return None
        metres = (float(feet_inches.group(1)) + float(feet_inches.group(2) or 0) / 12) * 0.3048
    return metres if math.isfinite(metres) and metres > 0 else None


def classify_building_height(
    tags: Mapping[str, object], *, metres_per_level: float = 3.0
) -> tuple[float | None, BuildingHeightQuality]:
    if not math.isfinite(metres_per_level) or metres_per_level <= 0:
        raise ValueError("metres_per_level must be positive and finite")
    explicit = parse_height(tags.get("height"))
    if explicit is not None:
        return explicit, BuildingHeightQuality.EXPLICIT
    levels = tags.get("building:levels")
    if isinstance(levels, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", levels.strip()):
        count = float(levels)
        if math.isfinite(count) and count > 0:
            return count * metres_per_level, BuildingHeightQuality.INFERRED_LEVELS
    return None, BuildingHeightQuality.UNKNOWN


def solar_position(instant: datetime, latitude: float, longitude: float) -> SolarPosition:
    """Return an approximate true-north solar position for deterministic modelling."""
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("solar instant must be timezone-aware")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("solar coordinates are out of range")
    utc = instant.astimezone(timezone.utc)
    day = utc.timetuple().tm_yday
    hour = utc.hour + utc.minute / 60 + utc.second / 3600
    gamma = 2 * math.pi / 365 * (day - 1 + (hour - 12) / 24)
    declination = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
                   - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma))
    equation = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                         - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    minutes = utc.hour * 60 + utc.minute + utc.second / 60
    true_solar_minutes = minutes + equation + 4 * longitude
    hour_angle = math.radians((true_solar_minutes / 4) - 180)
    lat = math.radians(latitude)
    elevation = math.degrees(math.asin(math.sin(lat) * math.sin(declination)
                                       + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)))
    azimuth = math.degrees(math.atan2(math.sin(hour_angle), math.cos(hour_angle) * math.sin(lat)
                                      - math.tan(declination) * math.cos(lat))) + 180
    return SolarPosition(azimuth % 360, elevation)


def route_shade_percent(
    route: LineString, buildings: Iterable[BuildingFootprint], solar: SolarPosition
) -> float:
    """Calculate route length covered by unioned projected building shadows."""
    if route.is_empty or route.length <= 0:
        raise ValueError("route must have positive length")
    if solar.elevation_degrees <= 0:
        return 0.0
    crs = _utm(route)
    projected_route = _project(route, crs)
    sweeps: list[BaseGeometry] = []
    occupied: list[BaseGeometry] = []
    for building in buildings:
        footprint = _project(building.geometry, crs)
        occupied.append(footprint)
        if building.height_m is None:
            continue
        length = building.height_m / math.tan(math.radians(solar.elevation_degrees))
        radians = math.radians(solar.azimuth_degrees + 180)
        dx, dy = length * math.sin(radians), length * math.cos(radians)
        shifted = transform(lambda x, y, z=None: (x + dx, y + dy), footprint)
        sweeps.append(footprint.union(shifted).convex_hull)
    if not sweeps:
        return 0.0
    shadow = cast(BaseGeometry, unary_union(sweeps)).difference(
        cast(BaseGeometry, unary_union(occupied))
    )
    covered = projected_route.intersection(shadow).length
    percentage = float(covered) / float(projected_route.length) * 100
    return max(0.0, min(100.0, percentage))


def _utm(geometry: BaseGeometry) -> int:
    centroid = geometry.centroid
    zone = int((centroid.x + 180) // 6) + 1
    return 32600 + zone if centroid.y >= 0 else 32700 + zone


def _project(geometry: BaseGeometry, epsg: int) -> BaseGeometry:
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    return transform(transformer.transform, geometry)


def building_from_geojson(
    identity: str,
    geometry: Mapping[str, object],
    tags: Mapping[str, object],
    *,
    metres_per_level: float = 3.0,
) -> BuildingFootprint:
    polygon = cast(BaseGeometry, shape(dict(geometry)))
    if polygon.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("building geometry must be polygonal")
    height, quality = classify_building_height(tags, metres_per_level=metres_per_level)
    return BuildingFootprint(identity, polygon, height, quality)
