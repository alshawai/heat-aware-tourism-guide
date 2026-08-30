"""Bounded Overpass building query, its cache identity, and its OSM data date.

The query options and selected tags that shape a building response are part of
the cache and fixture identity (ADR 0004), so they live here beside the query
they build rather than being restated at each call site.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from app.domain.hotels import BoundingBox
from app.integrations.overpass.errors import OverpassError

BUILDING_TAGS: tuple[str, ...] = ("building", "building:part")
BUILDING_OBJECT_TYPES: tuple[str, ...] = ("way", "relation")
BUILDING_RESPONSE_FORMAT = "json"
BUILDING_TIMEOUT_SECONDS = 60
BUILDING_OUTPUT = "body geom"


def build_building_query(aoi: BoundingBox) -> str:
    """One deterministic bounded query for building and building-part geometry."""
    bounds = ",".join(format(value, ".12g") for value in (aoi.south, aoi.west, aoi.north, aoi.east))
    selectors = "".join(
        f'{object_type}["{tag}"]({bounds});'
        for tag in BUILDING_TAGS
        for object_type in BUILDING_OBJECT_TYPES
    )
    return (
        f"[out:{BUILDING_RESPONSE_FORMAT}][timeout:{BUILDING_TIMEOUT_SECONDS}];\n"
        f"({selectors});\n"
        f"out {BUILDING_OUTPUT};"
    )


def building_query_options() -> dict[str, Any]:
    """The complete query options and selected tags that shape a building response."""
    return {
        "response_format": BUILDING_RESPONSE_FORMAT,
        "timeout_seconds": BUILDING_TIMEOUT_SECONDS,
        "output": BUILDING_OUTPUT,
        "object_types": list(BUILDING_OBJECT_TYPES),
        "selected_tags": list(BUILDING_TAGS),
    }


def building_request_payload(
    aoi: BoundingBox,
    *,
    search_distance_m: float,
    model_version: str,
) -> dict[str, Any]:
    """Complete building cache and fixture identity (ADR 0004).

    Two building responses only share an identity when the canonical shared AOI,
    the search distance that produced it, the complete query options and
    selected tags, and the route-shade model version all agree.
    """
    return {
        "aoi": aoi.to_payload(),
        "search_distance_m": search_distance_m,
        "query_options": building_query_options(),
        "model_version": model_version,
    }


def osm_source_timestamp(response: Mapping[str, object]) -> datetime:
    """Read the authoritative OSM data timestamp from one Overpass response."""
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
