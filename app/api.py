"""Minimal product-facing HTTP boundary for fixture-backed analysis."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from datetime import datetime
from enum import Enum
import math
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.execution import HeatmapExecution
from app.fortyguard import AnalyticType, HeatmapRequest, ProviderError
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


def create_fixture_server(
    fixture_path: Path,
    *,
    execution: HeatmapExecution | None = None,
) -> ThreadingHTTPServer:
    configured_execution: HeatmapExecution = execution or HeatmapExecution(fixture_path=fixture_path)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path not in {"/api/heatmap", "/api/trip/analyze"}:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")
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
                live = body.get("execution_mode", "fixture") == "live"
                if body.get("execution_mode", "fixture") not in {"fixture", "live"}:
                    raise ValueError("execution_mode must be fixture or live")
                response = json.dumps(_result_json(configured_execution.run(request, live=live)), default=_json_default).encode()
                self.send_response(200)
            except (KeyError, TypeError, ValueError, OSError, RuntimeError, ProviderError, json.JSONDecodeError) as error:
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
    heat_metric = body.get("heat_metric", "tcm")
    if heat_metric != "tcm":
        raise ValueError("trip analysis currently accepts the tcm provider metric only")
    building_coverage_value = body.get("building_coverage", 0)
    heat_value = body.get("heat_value")
    heat_threshold = body.get("heat_threshold")
    corridor_values = body.get("corridor_heat_values", [])
    if (
        isinstance(building_coverage_value, bool)
        or not isinstance(building_coverage_value, (int, float))
        or isinstance(heat_value, bool)
        or not isinstance(heat_value, (int, float))
        or isinstance(heat_threshold, bool)
        or not isinstance(heat_threshold, (int, float))
        or not isinstance(corridor_values, list)
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in corridor_values)
        or not math.isfinite(float(building_coverage_value))
        or not 0 <= float(building_coverage_value) <= 1
        or not math.isfinite(float(heat_value))
        or not math.isfinite(float(heat_threshold))
    ):
        raise ValueError("trip heat and coverage values must be numeric")
    building_coverage = float(building_coverage_value)
    route_result = RouteComparator().compare(
        lambda: route_candidates,
        heat_value=float(heat_value),
        heat_values=tuple(float(value) for value in corridor_values),
        heat_threshold=float(heat_threshold),
        shade=lambda route: _finite_number(shade[route.identity], "shade"),
        building_coverage=building_coverage,
    )
    return {
        "hotels": [asdict(hotel) for hotel in HotelRanker().rank(candidates)],
        "route": {
            **asdict(route_result),
            "routes": [asdict(route) for route in route_candidates],
            "heat_metric": heat_metric,
            "heat_status": "elevated" if route_result.corridor_heat_value > float(heat_threshold) else "not_elevated",
            "coverage": building_coverage,
            "confidence": "sufficient" if building_coverage >= 0.7 else "insufficient",
            "comparison_scope": "returned alternatives",
        },
        "provenance": {"source": "fixture", "stale": False},
    }


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be finite numeric")
    return float(value)
