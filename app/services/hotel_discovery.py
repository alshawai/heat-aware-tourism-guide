"""Hotel discovery orchestration and conservative OSM deduplication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

from app.domain.hotels import (
    BoundingBox,
    DiscoveryState,
    HotelCandidate,
    HotelDiscoveryResult,
    OsmIdentity,
)
from app.domain.provenance import CacheKey
from app.integrations.overpass.client import OverpassClient
from app.integrations.overpass.errors import OverpassError
from app.services.cache import CacheService

SCHEMA_VERSION = "v1"
PROVIDER_CONFIG_VERSION = "overpass-config-v1"
MINIMUM_USABLE_HOTELS = 5


@dataclass
class _HotelObject:
    identity: OsmIdentity
    name: str | None
    latitude: float | None
    longitude: float | None
    address: tuple[tuple[str, str], ...]
    website: str | None
    operator: str | None
    members: tuple[OsmIdentity, ...]


class HotelDiscoveryService:
    def __init__(
        self,
        client: OverpassClient,
        cache: CacheService,
        *,
        provider_endpoint: str,
        district_aoi: BoundingBox,
        clock: Callable[[], datetime],
    ) -> None:
        self._client = client
        self._cache = cache
        self._provider_endpoint = provider_endpoint
        self.district_aoi = district_aoi
        self._clock = clock

    def discover(self) -> HotelDiscoveryResult:
        request_payload = self.district_aoi.to_payload()
        retrieved_at = self._clock()
        source = "provider"
        stale = False
        try:
            response = self._client.query(self.district_aoi)
            source_timestamp = _source_timestamp(response)
            objects, discovered_count = _normalize(response)
            self._cache.put(
                self._provider_endpoint,
                SCHEMA_VERSION,
                request_payload,
                response,
                retrieved_at=retrieved_at,
                data_date=source_timestamp.date().isoformat(),
                provider_config_version=PROVIDER_CONFIG_VERSION,
            )
        except OverpassError:
            key = CacheKey.create(
                self._provider_endpoint,
                SCHEMA_VERSION,
                request_payload,
                PROVIDER_CONFIG_VERSION,
            )
            cached = self._cache.get(key)
            if cached is None:
                return HotelDiscoveryResult(
                    DiscoveryState.UNAVAILABLE,
                    (),
                    0,
                    0,
                    None,
                    retrieved_at,
                    "provider",
                    False,
                    "provider_failure",
                )
            response = dict(cached.payload)
            source_timestamp = _source_timestamp(response)
            retrieved_at = cached.provenance.retrieved_at
            source = "cache"
            stale = True
            try:
                objects, discovered_count = _normalize(response)
            except OverpassError:
                return HotelDiscoveryResult(
                    DiscoveryState.UNAVAILABLE,
                    (),
                    0,
                    0,
                    source_timestamp,
                    retrieved_at,
                    source,
                    stale,
                    "provider_failure",
                )
        candidates = _deduplicate(objects)
        state = (
            DiscoveryState.AVAILABLE
            if len(candidates) >= MINIMUM_USABLE_HOTELS
            else DiscoveryState.UNAVAILABLE
        )
        return HotelDiscoveryResult(
            state,
            candidates,
            discovered_count,
            len(candidates),
            source_timestamp,
            retrieved_at,
            source,
            stale,
            None if state is DiscoveryState.AVAILABLE else "insufficient_usable_hotels",
        )


def _source_timestamp(response: Mapping[str, object]) -> datetime:
    osm3s = response.get("osm3s")
    raw = osm3s.get("timestamp_osm_base") if isinstance(osm3s, Mapping) else None
    if not isinstance(raw, str) or not raw.strip():
        raise OverpassError("Overpass response is missing its OSM source timestamp")
    try:
        timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise OverpassError("Overpass OSM source timestamp is invalid") from None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def _normalize(response: Mapping[str, object]) -> tuple[list[_HotelObject], int]:
    elements = response.get("elements")
    if not isinstance(elements, list):
        raise OverpassError("Overpass response elements must be a list")
    normalized: list[_HotelObject] = []
    for element in elements:
        if not isinstance(element, Mapping):
            continue
        object_type = element.get("type")
        object_id = element.get("id")
        if (
            object_type not in {"node", "way", "relation"}
            or not isinstance(object_id, int)
            or isinstance(object_id, bool)
            or object_id < 1
        ):
            continue
        tags = element.get("tags")
        if not isinstance(tags, Mapping) or tags.get("tourism") != "hotel":
            continue
        lat, lon = _coordinates(element, object_type)
        normalized.append(
            _HotelObject(
                OsmIdentity(object_type, object_id),
                _text(tags.get("name")),
                lat,
                lon,
                tuple(
                    sorted(
                        (str(key)[5:], value.strip())
                        for key, value in tags.items()
                        if str(key).startswith("addr:") and isinstance(value, str) and value.strip()
                    )
                ),
                _website(tags),
                _text(tags.get("operator")),
                _members(element),
            )
        )
    return normalized, len(normalized)


def _coordinates(
    element: Mapping[str, object], object_type: str
) -> tuple[float | None, float | None]:
    source = element if object_type == "node" else element.get("center")
    if not isinstance(source, Mapping):
        return None, None
    lat, lon = source.get("lat"), source.get("lon")
    if (
        isinstance(lat, (int, float))
        and not isinstance(lat, bool)
        and isinstance(lon, (int, float))
        and not isinstance(lon, bool)
        and math.isfinite(lat)
        and math.isfinite(lon)
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    ):
        return float(lat), float(lon)
    return None, None


def _members(element: Mapping[str, object]) -> tuple[OsmIdentity, ...]:
    members = element.get("members")
    if not isinstance(members, list):
        return ()
    identities: list[OsmIdentity] = []
    for member in members:
        if not isinstance(member, Mapping):
            continue
        object_type, object_id = member.get("type"), member.get("ref")
        if (
            object_type in {"node", "way", "relation"}
            and isinstance(object_id, int)
            and not isinstance(object_id, bool)
            and object_id > 0
        ):
            identities.append(OsmIdentity(object_type, object_id))
    return tuple(identities)


def _deduplicate(objects: list[_HotelObject]) -> tuple[HotelCandidate, ...]:
    groups: list[list[_HotelObject]] = []
    for candidate in objects:
        matching = [
            group for group in groups if any(_same_hotel(candidate, item) for item in group)
        ]
        if not matching:
            groups.append([candidate])
            continue
        target = matching[0]
        target.append(candidate)
        for extra in matching[1:]:
            target.extend(extra)
            groups.remove(extra)

    results: list[HotelCandidate] = []
    for group in groups:
        named = [item for item in group if item.name and item.latitude is not None]
        if not named:
            continue
        representative = max(
            named,
            key=lambda item: (
                item.identity.object_type == "relation",
                len(item.address) + bool(item.website) + bool(item.operator),
                -item.identity.object_id,
            ),
        )
        identities = tuple(dict.fromkeys(item.identity for item in group))
        results.append(
            HotelCandidate(
                representative.identity,
                identities,
                representative.name or "",
                representative.latitude or 0.0,
                representative.longitude or 0.0,
                representative.address,
                representative.website,
                representative.operator,
            )
        )
    return tuple(results)


def _same_hotel(left: _HotelObject, right: _HotelObject) -> bool:
    if left.identity == right.identity:
        return True
    linked = left.identity in right.members or right.identity in left.members
    if linked and _compatible(left.name, right.name):
        return True
    names_match = _normalized(left.name) and _normalized(left.name) == _normalized(right.name)
    if not names_match:
        return False
    address_match = bool(left.address) and _normalized_address(left.address) == _normalized_address(
        right.address
    )
    website_match = bool(left.website) and left.website == right.website
    operator_match = bool(left.operator) and _normalized(left.operator) == _normalized(
        right.operator
    )
    return address_match or website_match or operator_match


def _compatible(left: str | None, right: str | None) -> bool:
    return left is None or right is None or _normalized(left) == _normalized(right)


def _normalized(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _normalized_address(address: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    return tuple((key.casefold(), _normalized(value)) for key, value in address)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _website(tags: Mapping[object, object]) -> str | None:
    raw = next(
        (
            _text(tags.get(key))
            for key in ("website", "contact:website", "url")
            if _text(tags.get(key))
        ),
        None,
    )
    if raw is None:
        return None
    try:
        parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    except ValueError:
        raise OverpassError("Overpass hotel website is invalid") from None
    host = (parsed.hostname or "").casefold()
    if not host:
        return None
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        raise OverpassError("Overpass hotel website is invalid") from None
    return urlunsplit(
        (parsed.scheme.casefold(), host + port, parsed.path.rstrip("/"), parsed.query, "")
    )
