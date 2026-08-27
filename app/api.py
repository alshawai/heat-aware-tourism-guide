"""Minimal product-facing HTTP boundary for fixture-backed analysis."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.contracts import (
    Coordinates,
    HotelCandidateData,
    Provenance,
    RouteCandidateData,
    TripAnalysisRequest,
    TripMode,
)
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
    allow_live: bool = False,
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
                request = _heatmap_request(body)
                live = body.get("execution_mode", "fixture") == "live"
                if body.get("execution_mode", "fixture") not in {"fixture", "live"}:
                    raise ValueError("execution_mode must be fixture or live")
                if live and not allow_live:
                    raise ValueError("live execution is not enabled for this server")
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


def create_app(
    fixture_path: Path,
    *,
    execution: HeatmapExecution | None = None,
    allow_live: bool = False,
    frontend_dist: Path | None = None,
) -> FastAPI:
    """Create the server-owned product API used by local runs and deployment."""
    configured_execution: HeatmapExecution = execution or HeatmapExecution(fixture_path=fixture_path)
    app = FastAPI(title="Heat-Aware Tourism Guide")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "live" if allow_live else "fixture"}

    @app.post("/api/heatmap")
    def heatmap(body: dict[str, object]) -> dict[str, object]:
        try:
            request = _heatmap_request(body)
            mode = body.get("execution_mode", "fixture")
            if mode not in {"fixture", "live"} or mode == "live" and not allow_live:
                raise ValueError("requested execution mode is unavailable")
            return _result_json(configured_execution.run(request, live=mode == "live"))
        except (KeyError, TypeError, ValueError, OSError, RuntimeError, ProviderError) as error:
            raise HTTPException(status_code=400, detail={"status": "unavailable", "error": str(error)}) from error

    @app.post("/api/trip/analyze")
    def trip_analyze(body: dict[str, object]) -> dict[str, object]:
        try:
            return _trip_result(body)
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail={"status": "unavailable", "error": str(error)}) from error

    if frontend_dist is not None and frontend_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def frontend(path: str) -> FileResponse:
            requested = frontend_dist / path
            return FileResponse(requested if requested.is_file() else frontend_dist / "index.html")

    return app


def _required_bool(body: dict[str, object], field: str, *, default: bool) -> bool:
    value = body.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _heatmap_request(body: dict[str, object]) -> HeatmapRequest:
    latitude = _finite_number(body.get("latitude"), "latitude")
    longitude = _finite_number(body.get("longitude"), "longitude")
    start_date = body.get("start_date")
    if not isinstance(start_date, str):
        raise ValueError("start_date must be a date string")
    threshold = body.get("threshold_celsius")
    if threshold is not None:
        threshold = _finite_number(threshold, "threshold_celsius")
    direction = body.get("direction")
    if direction is not None and not isinstance(direction, str):
        raise ValueError("direction must be a string")
    return HeatmapRequest(
        AnalyticType(body["analytic_type"]),
        latitude,
        longitude,
        date.fromisoformat(start_date),
        _required_bool(body, "forecast", default=True),
        threshold,
        direction,
    )


def _parse_trip_request(body: dict[str, object]) -> TripAnalysisRequest:
    """Validate a raw request body against the shared trip-analysis contract.

    Accepts both the full contract fields and the legacy compact format
    used by existing tests and internal callers.
    """
    origin_lat = _finite_number(
        body.get("origin_latitude", body.get("latitude")), "origin_latitude"
    )
    origin_lon = _finite_number(
        body.get("origin_longitude", body.get("longitude")), "origin_longitude"
    )
    dest_lat = _finite_number(
        body.get("destination_latitude", body.get("latitude")), "destination_latitude"
    )
    dest_lon = _finite_number(
        body.get("destination_longitude", body.get("longitude")), "destination_longitude"
    )
    landmark = body.get("landmark_name", "")
    district = body.get("district_name", "")
    trip_date = body.get("date", body.get("start_date", ""))
    hour = body.get("hour", 12)

    hotels_raw = body.get("hotels")
    routes_raw = body.get("routes")
    shade_raw = body.get("shade")
    if not isinstance(hotels_raw, list) or not hotels_raw:
        raise ValueError("hotels must be a non-empty list")
    if not isinstance(routes_raw, list) or not routes_raw:
        raise ValueError("routes must be a non-empty list")
    if not isinstance(shade_raw, dict):
        raise ValueError("shade must be a dict mapping route identity to shade value")

    hotels = tuple(
        HotelCandidateData(
            identity=item["identity"],
            components=dict(item["components"]),
        )
        for item in hotels_raw
    )
    routes = tuple(
        RouteCandidateData(
            identity=item["identity"],
            distance_m=float(item["distance_m"]),
            duration_s=float(item["duration_s"]),
        )
        for item in routes_raw
    )
    shade = {str(k): float(v) for k, v in shade_raw.items()}

    heat_metric = body.get("heat_metric", "tcm")
    if not isinstance(heat_metric, str) or not heat_metric:
        raise ValueError("heat_metric must be a non-empty string")

    return TripAnalysisRequest(
        mode=TripMode.CURATED,
        origin=Coordinates(origin_lat, origin_lon),
        destination=Coordinates(dest_lat, dest_lon),
        landmark_name=landmark,
        district_name=district,
        date=trip_date,
        hour=hour,
        cautious=bool(body.get("cautious", False)),
        heat_metric=heat_metric,
        heat_value=_finite_number(body.get("heat_value"), "heat_value"),
        heat_threshold=_finite_number(body.get("heat_threshold"), "heat_threshold"),
        corridor_heat_values=tuple(
            _finite_number(v, "corridor_heat_values entry")
            for v in (body.get("corridor_heat_values") or [])
        ),
        building_coverage=_finite_number(body.get("building_coverage", 0), "building_coverage"),
        hotels=hotels,
        routes=routes,
        shade=shade,
    )


def _trip_result(body: dict[str, object]) -> dict[str, object]:
    """Run the trip analysis and return the product-shaped response.

    Validates the request against the shared contract before computation.
    """
    _parse_trip_request(body)

    hotels = body.get("hotels")
    routes = body.get("routes")
    shade = body.get("shade")
    candidates = tuple(HotelCandidate(item["identity"], item["components"]) for item in hotels)
    route_candidates = tuple(RouteCandidate(item["identity"], item["distance_m"], item["duration_s"]) for item in routes)
    heat_metric = body.get("heat_metric", "tcm")
    building_coverage = _finite_number(body.get("building_coverage", 0), "building_coverage")
    heat_value = _finite_number(body.get("heat_value"), "heat_value")
    heat_threshold = _finite_number(body.get("heat_threshold"), "heat_threshold")
    corridor_values = body.get("corridor_heat_values", [])
    shade_map = {str(k): float(v) for k, v in shade.items()}

    route_result = RouteComparator().compare(
        lambda: route_candidates,
        heat_value=heat_value,
        heat_values=tuple(float(value) for value in corridor_values),
        heat_threshold=heat_threshold,
        shade=lambda route: shade_map[route.identity],
        building_coverage=building_coverage,
    )
    return {
        "hotels": [asdict(hotel) for hotel in HotelRanker().rank(candidates)],
        "route": {
            **asdict(route_result),
            "routes": [asdict(route) for route in route_candidates],
            "heat_metric": heat_metric,
            "heat_status": "elevated" if route_result.corridor_heat_value > heat_threshold else "not_elevated",
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
