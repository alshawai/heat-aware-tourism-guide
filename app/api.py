"""Minimal product-facing HTTP boundary for fixture-backed analysis."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.execution import HeatmapExecution
from app.fortyguard import AnalyticType, HeatmapRequest
from app.trip import HotelCandidate, HotelRanker, RouteCandidate, RouteComparator


def _result_json(result: Any) -> dict[str, object]:
    return {
        "tiles": [asdict(tile) for tile in result.tiles],
        "provenance": asdict(result.provenance),
    }


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def create_fixture_server(fixture_path: Path) -> ThreadingHTTPServer:
    execution = HeatmapExecution(fixture_path=fixture_path)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path not in {"/api/heatmap", "/api/trip/analyze"}:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                if path == "/api/trip/analyze":
                    response = json.dumps(_trip_result(body), default=_json_default).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                    return
                request = HeatmapRequest(
                    AnalyticType(body["analytic_type"]),
                    float(body["latitude"]),
                    float(body["longitude"]),
                    date.fromisoformat(body["start_date"]),
                    _required_bool(body, "forecast", default=True),
                    body.get("threshold_celsius"),
                    body.get("direction"),
                )
                response = json.dumps(_result_json(execution.run(request)), default=_json_default).encode()
                self.send_response(200)
            except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
                response = json.dumps({"error": str(error), "status": "unavailable"}).encode()
                self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def _required_bool(body: dict[str, object], field: str, *, default: bool) -> bool:
    value = body.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _trip_result(body: dict[str, object]) -> dict[str, object]:
    hotels = body.get("hotels")
    routes = body.get("routes")
    shade = body.get("shade")
    if not isinstance(hotels, list) or not isinstance(routes, list) or not isinstance(shade, dict):
        raise ValueError("trip analysis requires hotels, routes, and shade data")
    candidates = tuple(HotelCandidate(item["identity"], item["components"]) for item in hotels)
    route_candidates = tuple(RouteCandidate(item["identity"], item["distance_m"], item["duration_s"]) for item in routes)
    route_result = RouteComparator().compare(
        lambda: route_candidates,
        heat_value=float(body["heat_value"]),
        heat_threshold=float(body["heat_threshold"]),
        shade=lambda route: float(shade[route.identity]),
        building_coverage=float(body.get("building_coverage", 0)),
    )
    return {
        "hotels": [asdict(hotel) for hotel in HotelRanker().rank(candidates)],
        "route": asdict(route_result),
    }
