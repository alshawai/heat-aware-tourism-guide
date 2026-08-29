"""Provider-neutral contracts for hotel discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math


@dataclass(frozen=True)
class BoundingBox:
    """A bounded WGS84 area in Overpass south/west/north/east order."""

    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        values = (self.south, self.west, self.north, self.east)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("bounding box coordinates must be finite")
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("bounding box latitude bounds are invalid")
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("bounding box longitude bounds are invalid")

    def to_payload(self) -> dict[str, float]:
        return {
            "south": self.south,
            "west": self.west,
            "north": self.north,
            "east": self.east,
        }


@dataclass(frozen=True, order=True)
class OsmIdentity:
    object_type: str
    object_id: int

    def __post_init__(self) -> None:
        if self.object_type not in {"node", "way", "relation"}:
            raise ValueError("OSM object type must be node, way, or relation")
        if self.object_id < 1:
            raise ValueError("OSM object ID must be positive")


@dataclass(frozen=True)
class HotelCandidate:
    primary_identity: OsmIdentity
    source_identities: tuple[OsmIdentity, ...]
    name: str
    latitude: float
    longitude: float
    address: tuple[tuple[str, str], ...] = ()
    website: str | None = None
    operator: str | None = None


class DiscoveryState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class HotelDiscoveryResult:
    state: DiscoveryState
    candidates: tuple[HotelCandidate, ...]
    discovered_count: int
    usable_count: int
    source_timestamp: datetime | None
    retrieved_at: datetime | None
    source: str
    stale: bool
    reason: str | None = None
