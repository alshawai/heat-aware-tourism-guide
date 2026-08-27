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
    ExecutionMode,
    ResultState,
    TripAnalysisAdapter,
    TripAnalysisRequest,
    TripAnalysisResponse,
    TripMode,
    UnavailableResult,
)
from app.execution import HeatmapExecution
from app.fortyguard import AnalyticType, HeatmapRequest, ProviderError


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
    trip_adapter: TripAnalysisAdapter | None = None,
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
                    response = json.dumps(
                        _trip_result(
                            body,
                            allow_live=allow_live,
                            trip_adapter=trip_adapter,
                        ),
                        default=_json_default,
                    ).encode()
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
    trip_adapter: TripAnalysisAdapter | None = None,
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
            return _trip_result(
                body,
                allow_live=allow_live,
                trip_adapter=trip_adapter,
            )
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
    """Parse the frontend request into the provider-independent contract."""
    provider_fields = {
        "heat_metric",
        "heat_value",
        "heat_threshold",
        "corridor_heat_values",
        "building_coverage",
        "hotels",
        "routes",
        "shade",
        "provenance",
    }
    supplied_provider_fields = provider_fields.intersection(body)
    if supplied_provider_fields:
        raise ValueError(
            "provider analysis fields are server-owned: "
            + ", ".join(sorted(supplied_provider_fields))
        )
    origin_lat = _finite_number(body.get("origin_latitude"), "origin_latitude")
    origin_lon = _finite_number(body.get("origin_longitude"), "origin_longitude")
    dest_lat = _finite_number(body.get("destination_latitude"), "destination_latitude")
    dest_lon = _finite_number(body.get("destination_longitude"), "destination_longitude")
    landmark = body.get("landmark_name")
    district = body.get("district_name")
    trip_date = body.get("date")
    hour = body.get("hour")
    mode = body.get("mode")
    if not isinstance(landmark, str) or not landmark:
        raise ValueError("landmark_name must be a non-empty string")
    if not isinstance(district, str) or not district:
        raise ValueError("district_name must be a non-empty string")
    if not isinstance(trip_date, str) or not trip_date:
        raise ValueError("date must be a non-empty string")
    if isinstance(hour, bool) or not isinstance(hour, int):
        raise ValueError("hour must be an integer between 0 and 23")
    if not isinstance(mode, str):
        raise ValueError("mode must be curated or exploratory")

    return TripAnalysisRequest(
        mode=TripMode(mode),
        origin=Coordinates(origin_lat, origin_lon),
        destination=Coordinates(dest_lat, dest_lon),
        landmark_name=landmark,
        district_name=district,
        date=trip_date,
        hour=hour,
        cautious=_required_bool(body, "cautious", default=False),
    )


def _trip_result(
    body: dict[str, object],
    *,
    allow_live: bool,
    trip_adapter: TripAnalysisAdapter | None,
) -> dict[str, object]:
    """Run the trip analysis and serialize the shared product contract."""
    execution_mode = _execution_mode(body, allow_live=allow_live)
    unavailable_reason = body.get("unavailable_reason")
    if unavailable_reason is not None:
        if not isinstance(unavailable_reason, str) or not unavailable_reason:
            raise ValueError("unavailable_reason must be a non-empty string")
        response = TripAnalysisResponse(
            request_identity=str(body.get("request_identity", "unavailable")),
            mode=TripMode(str(body.get("mode", TripMode.EXPLORATORY.value))),
            execution_mode=execution_mode,
            state=ResultState.UNAVAILABLE,
            unavailable=UnavailableResult(unavailable_reason, recoverable=True),
        )
        return asdict(response)
    request = _parse_trip_request(body)
    if trip_adapter is None:
        raise ValueError("trip analysis adapter is not configured")
    response = trip_adapter.analyze(request)
    if response.execution_mode is not execution_mode:
        raise ValueError("trip adapter returned the wrong execution mode")
    return asdict(response)


def _execution_mode(body: dict[str, object], *, allow_live: bool) -> ExecutionMode:
    requested = body.get("execution_mode", ExecutionMode.FIXTURE.value)
    try:
        mode = ExecutionMode(requested)
    except ValueError as error:
        raise ValueError("execution_mode must be fixture or live") from error
    if mode is ExecutionMode.LIVE and not allow_live:
        raise ValueError("live execution is not enabled for this server")
    return mode


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be finite numeric")
    return float(value)
