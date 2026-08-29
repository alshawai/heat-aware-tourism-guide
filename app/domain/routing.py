"""Provider-neutral walking-route request and response models."""

from __future__ import annotations

from dataclasses import dataclass
import math

from app.domain.contracts import Coordinates


@dataclass(frozen=True)
class RouteRequest:
    origin: Coordinates
    destination: Coordinates
    profile: str
    alternatives: bool
    overview: str
    geometries: str
    steps: bool
    provider_instance: str
    request_version: str

    def __post_init__(self) -> None:
        if not self.profile.strip():
            raise ValueError("route profile is required")
        if not isinstance(self.alternatives, bool) or not self.alternatives:
            raise ValueError("route alternatives must be requested")
        if self.overview != "full":
            raise ValueError("route overview must be full")
        if self.geometries != "geojson":
            raise ValueError("route geometries must be geojson")
        if not isinstance(self.steps, bool):
            raise ValueError("route steps option must be boolean")
        if not self.provider_instance.strip():
            raise ValueError("route provider instance is required")
        if not self.request_version.strip():
            raise ValueError("route request version is required")


@dataclass(frozen=True)
class RouteGeometry:
    """A full OSRM LineString in GeoJSON longitude,latitude order."""

    coordinates: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.coordinates) < 2:
            raise ValueError("route geometry requires at least two points")
        for point in self.coordinates:
            if len(point) != 2:
                raise ValueError("route geometry points must contain longitude and latitude")
            longitude, latitude = point
            if (
                isinstance(longitude, bool)
                or isinstance(latitude, bool)
                or not isinstance(longitude, (int, float))
                or not isinstance(latitude, (int, float))
                or not math.isfinite(longitude)
                or not math.isfinite(latitude)
                or not -180 <= longitude <= 180
                or not -90 <= latitude <= 90
            ):
                raise ValueError("route geometry points must be finite WGS84 coordinates")
        if len(set(self.coordinates)) < 2:
            raise ValueError("route geometry requires at least two distinct points")

    @property
    def geojson(self) -> dict[str, object]:
        return {
            "type": "LineString",
            "coordinates": [[longitude, latitude] for longitude, latitude in self.coordinates],
        }


@dataclass(frozen=True)
class ReturnedRoute:
    identity: str
    distance_m: float
    duration_s: float
    geometry: RouteGeometry

    def __post_init__(self) -> None:
        if not self.identity.strip():
            raise ValueError("returned route identity is required")
        if not math.isfinite(self.distance_m) or self.distance_m <= 0:
            raise ValueError("returned route distance must be positive and finite")
        if not math.isfinite(self.duration_s) or self.duration_s <= 0:
            raise ValueError("returned route duration must be positive and finite")
        if not isinstance(self.geometry, RouteGeometry):
            raise ValueError("returned route geometry is required")


@dataclass(frozen=True)
class RouteSet:
    routes: tuple[ReturnedRoute, ...]
    provider_instance: str

    def __post_init__(self) -> None:
        if not self.routes:
            raise ValueError("route set requires at least one returned route")
        if any(not isinstance(route, ReturnedRoute) for route in self.routes):
            raise ValueError("route set entries must be returned routes")
        identities = [route.identity for route in self.routes]
        if len(set(identities)) != len(identities):
            raise ValueError("returned route identities must be unique")
        if not self.provider_instance.strip():
            raise ValueError("route set provider instance is required")

    @property
    def shortest(self) -> ReturnedRoute:
        return min(self.routes, key=lambda route: route.distance_m)

    def any_longer_than(self, threshold_m: float) -> bool:
        if not math.isfinite(threshold_m) or threshold_m <= 0:
            raise ValueError("representative distance threshold must be positive and finite")
        return any(route.distance_m > threshold_m for route in self.routes)
