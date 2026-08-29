"""OSRM response normalization and one-call client."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from app.domain.routing import RouteRequest, RouteSet, ReturnedRoute, RouteGeometry
from app.integrations.osrm.errors import OsrmMalformedResponse, OsrmNoRoute
from app.integrations.osrm.transport import HttpOsrmTransport


class OsrmClient:
    def __init__(self, transport: HttpOsrmTransport) -> None:
        self.transport = transport

    def load(self, request: RouteRequest) -> Mapping[str, object]:
        """Load one raw response so execution can cache the provider payload."""
        coordinates = (
            f"{request.origin.longitude},{request.origin.latitude};"
            f"{request.destination.longitude},{request.destination.latitude}"
        )
        return cast(
            Mapping[str, object],
            self.transport.get(
                f"{request.profile}/{coordinates}",
                {
                    "alternatives": str(request.alternatives).lower(),
                    "overview": request.overview,
                    "geometries": request.geometries,
                    "steps": str(request.steps).lower(),
                },
            ),
        )

    def route(self, request: RouteRequest) -> RouteSet:
        payload = self.load(request)
        return normalize_response(payload, provider_instance=request.provider_instance)


def normalize_response(payload: Mapping[str, object], *, provider_instance: str) -> RouteSet:
    if payload.get("code") != "Ok":
        if payload.get("code") == "NoRoute":
            raise OsrmNoRoute("OSRM found no suitable returned route")
        raise OsrmMalformedResponse("OSRM response did not complete successfully")
    raw_routes = payload.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise OsrmNoRoute("OSRM returned no routes")
    routes: list[ReturnedRoute] = []
    for index, raw in enumerate(raw_routes, start=1):
        if not isinstance(raw, Mapping):
            raise OsrmMalformedResponse("OSRM route must be an object")
        distance = _positive_number(raw.get("distance"), "distance")
        duration = _positive_number(raw.get("duration"), "duration")
        geometry = raw.get("geometry")
        if not isinstance(geometry, Mapping) or geometry.get("type") != "LineString":
            raise OsrmMalformedResponse("OSRM route geometry must be a LineString")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list):
            raise OsrmMalformedResponse("OSRM route geometry coordinates are required")
        try:
            normalized = tuple((float(point[0]), float(point[1])) for point in coordinates)
        except (IndexError, TypeError, ValueError):
            raise OsrmMalformedResponse("OSRM route geometry coordinates are malformed") from None
        try:
            route_geometry = RouteGeometry(normalized)
        except ValueError as error:
            raise OsrmMalformedResponse(str(error)) from error
        routes.append(ReturnedRoute(f"route-{index}", distance, duration, route_geometry))
    return RouteSet(tuple(routes), provider_instance)


def _positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OsrmMalformedResponse(f"OSRM {field} must be numeric")
    if not math.isfinite(value) or value <= 0:
        raise OsrmMalformedResponse(f"OSRM {field} must be positive and finite")
    return float(value)
