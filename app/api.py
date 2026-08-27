"""Minimal product-facing HTTP boundary for fixture-backed analysis."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
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
    BestTimeResult,
    Confidence,
    Coordinates,
    EnrichmentState,
    ExecutionMode,
    HeatStatus,
    HotelCandidateData,
    HotelRankingResult,
    HourlyEntry,
    Metric,
    MetricLabel,
    Provenance,
    RankedHotel,
    RouteCandidateData,
    RouteComparisonResult,
    RouteOption,
    ResultState,
    TripAnalysisRequest,
    TripAnalysisInputs,
    TripAnalysisResponse,
    TripMode,
    UnavailableResult,
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
                    response = json.dumps(
                        _trip_result(body, allow_live=allow_live), default=_json_default
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
            return _trip_result(body, allow_live=allow_live)
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


def _parse_trip_inputs(body: dict[str, object]) -> TripAnalysisInputs:
    """Parse normalized adapter data kept separate from traveler input."""
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
    if heat_metric not in {"tcm", "heat_index_celsius"}:
        raise ValueError("heat_metric must be tcm or heat_index_celsius")
    corridor_values = body.get("corridor_heat_values", [])
    if not isinstance(corridor_values, list):
        raise ValueError("corridor_heat_values must be a list")

    return TripAnalysisInputs(
        heat_metric=heat_metric,
        heat_value=_finite_number(body.get("heat_value"), "heat_value"),
        heat_threshold=_finite_number(body.get("heat_threshold"), "heat_threshold"),
        corridor_heat_values=tuple(
            _finite_number(v, "corridor_heat_values entry")
            for v in corridor_values
        ),
        building_coverage=_finite_number(body.get("building_coverage", 0), "building_coverage"),
        hotels=hotels,
        routes=routes,
        shade=shade,
    )


def _trip_result(body: dict[str, object], *, allow_live: bool) -> dict[str, object]:
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
    inputs = _parse_trip_inputs(body)
    response = _analyze_trip(request, inputs, execution_mode)
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


def _analyze_trip(
    request: TripAnalysisRequest,
    inputs: TripAnalysisInputs,
    execution_mode: ExecutionMode,
) -> TripAnalysisResponse:
    candidates = tuple(HotelCandidate(hotel.identity, hotel.components) for hotel in inputs.hotels)
    route_candidates = tuple(
        RouteCandidate(route.identity, route.distance_m, route.duration_s)
        for route in inputs.routes
    )

    route_result = RouteComparator().compare(
        lambda: route_candidates,
        heat_value=inputs.heat_value,
        heat_values=inputs.corridor_heat_values,
        heat_threshold=inputs.heat_threshold,
        shade=lambda route: inputs.shade[route.identity],
        building_coverage=inputs.building_coverage,
    )
    confidence = (
        Confidence.SUFFICIENT
        if inputs.building_coverage >= 0.7
        else Confidence.INSUFFICIENT
    )
    metric_label = (
        MetricLabel.NOAA_HEAT_INDEX
        if inputs.heat_metric == "heat_index_celsius"
        else MetricLabel.PROVIDER_TCM
    )
    provenance = Provenance(
        source=execution_mode.value,
        provider="fortyguard",
        data_date=request.date,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        response_status="completed",
        transformation_version="trip-contract-v1",
        confidence=confidence,
        coverage=inputs.building_coverage,
    )
    ranked = tuple(
        RankedHotel(
            identity=hotel.identity,
            components=dict(hotel.components),
            score=hotel.score,
            percentile=hotel.percentile,
            tie_group=hotel.tie_group,
        )
        for hotel in HotelRanker().rank(candidates)
    )
    route_options = tuple(
        RouteOption(
            identity=route.identity,
            distance_m=route.distance_m,
            duration_s=route.duration_s,
            heat_value=route_result.corridor_heat_value,
            modeled_shade_percent=inputs.shade[route.identity] if route_result.shade_was_computed else None,
            shade_confidence=confidence if route_result.shade_was_computed else None,
        )
        for route in route_candidates
    )
    best_hour = request.hour
    return TripAnalysisResponse(
        request_identity=f"{request.mode.value}:{request.date}:{request.hour}",
        mode=request.mode,
        execution_mode=execution_mode,
        state=ResultState.DEGRADED if confidence is Confidence.INSUFFICIENT else ResultState.SUCCESS,
        best_time=BestTimeResult(
            hourly=(
                HourlyEntry(
                    hour=best_hour,
                    metric=Metric(
                        value=inputs.heat_value,
                        unit="C",
                        label=metric_label,
                        is_actual_heat_index=metric_label is MetricLabel.NOAA_HEAT_INDEX,
                    ),
                ),
            ),
            recommendation_hour=best_hour,
            recommendation_reason="selected trip hour is the available heat observation",
            metric_label=metric_label,
            provenance=provenance,
        ),
        hotels=HotelRankingResult(
            ranked=ranked,
            weights=dict(HotelRanker.default_weights),
            usable_count=len(ranked),
            discovered_count=len(ranked),
            provenance=provenance,
            enrichment=EnrichmentState.NOT_REQUESTED,
        ),
        routes=RouteComparisonResult(
            alternatives=route_options,
            recommended_id=route_result.recommended_id,
            reason=route_result.reason,
            heat_status=(
                HeatStatus.ELEVATED
                if route_result.corridor_heat_value > inputs.heat_threshold
                else HeatStatus.NOT_ELEVATED
            ),
            corridor_heat_value=route_result.corridor_heat_value,
            heat_metric=inputs.heat_metric,
            coverage=inputs.building_coverage,
            confidence=confidence,
            comparison_scope="returned alternatives",
            provenance=provenance,
        ),
    )


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be finite numeric")
    return float(value)
