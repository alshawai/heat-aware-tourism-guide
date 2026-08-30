"""Minimal product-facing HTTP boundary for fixture-backed analysis."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.domain.contracts import (
    Coordinates,
    ExecutionMode,
    TripAnalysisAdapter,
    TripAnalysisRequest,
    TripAnalysisResponse,
    TripMode,
)
from app.domain.ledger import BudgetExceededError
from app.domain.enrichment import EnrichmentKind
from app.domain.result_tokens import ResultTokenError, issue_result_token, verify_result_token
from app.domain.hotel_heat_score import COMPONENTS, NeighbourhoodHeatScorer
from app.domain.hotels import BoundingBox
from app.integrations.fortyguard.contracts import AnalyticType, EnvParamsRequest, HeatmapRequest
from app.integrations.fortyguard.errors import ProviderError
from app.services.execution import EnvParamsExecution, HeatmapExecution, UnavailableError
from app.services.hotel_heat_score import (
    HotelHeatAnalysisOutcome,
    HotelHeatAnalysisService,
    build_fixture_hotel_heat_analysis_service,
)
from app.services.enrichment import EnrichmentService


def _result_json(result: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "tiles": [asdict(tile) for tile in result.tiles],
        "provenance": asdict(result.provenance),
    }
    if result.activity is not None:
        payload["activity"] = asdict(result.activity)
    return payload


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _error_kind(error: BaseException) -> str | None:
    if isinstance(error, BudgetExceededError):
        return "budget_exceeded"
    if isinstance(error, ProviderError):
        return error.kind.value
    if isinstance(error, UnavailableError):
        return error.error_kind
    return None


def _error_response(error: Exception) -> tuple[int, dict[str, object]]:
    """Three-way failure split: 400 client error, 503 unavailable, 503 budget (ADR 0004)."""
    if isinstance(error, (KeyError, TypeError, ValueError)):
        return 400, {"status": "error", "error": str(error)}
    detail: dict[str, object] = {"status": "unavailable", "error": str(error)}
    kind = _error_kind(error)
    if kind is not None:
        detail["error_kind"] = kind
    return 503, detail


def _http_error(error: Exception) -> HTTPException:
    status_code, detail = _error_response(error)
    return HTTPException(status_code=status_code, detail=detail)


def create_fixture_server(
    fixture_path: Path,
    *,
    execution: HeatmapExecution | None = None,
    allow_live: bool = False,
    trip_adapter: TripAnalysisAdapter | None = None,
) -> ThreadingHTTPServer:
    configured_execution: HeatmapExecution = execution or HeatmapExecution(
        fixture_path=fixture_path
    )

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
                            result_token_secret=None,
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
                response = json.dumps(
                    _result_json(configured_execution.run(request, live=live)),
                    default=_json_default,
                ).encode()
                self.send_response(200)
            except (
                BudgetExceededError,
                KeyError,
                TypeError,
                ValueError,
                OSError,
                RuntimeError,
                ProviderError,
                json.JSONDecodeError,
            ) as error:
                status_code, error_payload = _error_response(error)
                response = json.dumps(error_payload).encode()
                self.send_response(status_code)
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
    env_params_execution: EnvParamsExecution | None = None,
    allow_live: bool = False,
    frontend_dist: Path | None = None,
    trip_adapter: TripAnalysisAdapter | None = None,
    hotel_heat_analysis_service: HotelHeatAnalysisService | None = None,
    district_aoi: BoundingBox = BoundingBox(29.421, -98.490, 29.429, -98.482),
    enrichment_service: EnrichmentService | None = None,
    result_token_secret: str | None = None,
) -> FastAPI:
    """Create the server-owned product API used by local runs and deployment."""
    configured_execution: HeatmapExecution = execution or HeatmapExecution(
        fixture_path=fixture_path
    )
    configured_env_params: EnvParamsExecution = env_params_execution or EnvParamsExecution(
        fixture_path=fixture_path.parent / "env-params.json"
    )
    configured_hotel_analysis = (
        hotel_heat_analysis_service
        if hotel_heat_analysis_service is not None
        else build_fixture_hotel_heat_analysis_service(
            fixture_path.parent / "hotel-heat-analysis.json",
            district_aoi=district_aoi,
        )
    )
    app = FastAPI(title="Heat-Aware Tourism Guide")
    token_secret = result_token_secret or secrets.token_urlsafe(32)
    if enrichment_service is None:
        from app.domain.ledger import CreditLedger
        from app.services.enrichment import FixtureEnrichmentAdapter

        environment_fixture: dict[str, object] = {}
        environment_path = fixture_path.parent / "env-params.json"
        if environment_path.is_file():
            loaded = json.loads(environment_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                environment_fixture = loaded
        enrichment_service = EnrichmentService(
            ledger=CreditLedger(enrichment_budget=0),
            adapters={
                EnrichmentKind.ENVIRONMENT: FixtureEnrichmentAdapter(environment_fixture),
                EnrichmentKind.SATELLITE_CANOPY: FixtureEnrichmentAdapter(
                    {"fixture_data_unavailable": True}
                ),
                EnrichmentKind.STREET_VIEW: FixtureEnrichmentAdapter(
                    {"fixture_data_unavailable": True}
                ),
            },
            estimates={"environment": 0, "satellite_canopy": 0, "street_view": 0},
            live=False,
        )

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
        except (
            BudgetExceededError,
            KeyError,
            TypeError,
            ValueError,
            OSError,
            RuntimeError,
            ProviderError,
        ) as error:
            raise _http_error(error) from error

    @app.post("/api/env-params")
    def env_params(body: dict[str, object]) -> dict[str, object]:
        try:
            request = _env_params_request(body)
            mode = body.get("execution_mode", "fixture")
            if mode not in {"fixture", "live"} or mode == "live" and not allow_live:
                raise ValueError("requested execution mode is unavailable")
            outcome = configured_env_params.run(request, live=mode == "live")
            return {
                "entries": [asdict(entry) for entry in outcome.result.entries],
                "timezone": outcome.result.timezone,
                "forecast": outcome.result.forecast,
                "warning": outcome.result.warning,
                "provenance": {
                    "source": outcome.source,
                    "stale": outcome.stale,
                    "activity_id": outcome.activity_id,
                    "retrieved_at": (
                        outcome.retrieved_at.isoformat()
                        if outcome.retrieved_at is not None
                        else None
                    ),
                    "data_date": outcome.data_date,
                    "transformations": [
                        {"name": t.name, "version": t.version} for t in outcome.transformations
                    ],
                },
            }
        except (
            BudgetExceededError,
            KeyError,
            TypeError,
            ValueError,
            OSError,
            RuntimeError,
            ProviderError,
        ) as error:
            raise _http_error(error) from error

    @app.post("/api/trip/analyze")
    def trip_analyze(body: dict[str, object]) -> dict[str, object]:
        try:
            return _trip_result(
                body,
                allow_live=allow_live,
                trip_adapter=trip_adapter,
                result_token_secret=token_secret,
            )
        except (
            BudgetExceededError,
            KeyError,
            TypeError,
            ValueError,
            OSError,
            RuntimeError,
            ProviderError,
        ) as error:
            raise _http_error(error) from error

    @app.post("/api/hotels/rank")
    def rank_hotels(body: dict[str, object]) -> dict[str, object]:
        try:
            allowed_fields = {"district_name", "execution_mode", "weights"}
            unexpected = set(body) - allowed_fields
            if unexpected:
                raise ValueError(
                    "unsupported hotel ranking fields: " + ", ".join(sorted(unexpected))
                )
            district_name = body.get("district_name")
            if not isinstance(district_name, str) or not district_name.strip():
                raise ValueError("district_name must be a non-empty string")
            execution_mode = _execution_mode(body, allow_live=allow_live)
            weights = _hotel_weights(body.get("weights"))
            outcome = configured_hotel_analysis.analyze(
                district_name, execution_mode, weights=weights
            )
            result = _hotel_heat_result(outcome)
            ranking = result.get("ranking")
            if isinstance(ranking, dict) and isinstance(ranking.get("hotels"), list):
                coordinates = {
                    _hotel_target_id(asdict(assignment.identity)): {
                        "latitude": assignment.latitude,
                        "longitude": assignment.longitude,
                    }
                    for assignment in outcome.assignments
                }
                result["result_set_token"] = issue_result_token(
                    {
                        "request_identity": district_name,
                        "hotel_ids": [
                            _hotel_target_id(item["identity"])
                            for item in ranking["hotels"]
                            if isinstance(item, dict) and isinstance(item.get("identity"), dict)
                        ],
                        "hotel_coordinates": coordinates,
                    },
                    token_secret,
                )
            return result
        except (
            BudgetExceededError,
            KeyError,
            TypeError,
            ValueError,
            OSError,
            RuntimeError,
            ProviderError,
        ) as error:
            raise _http_error(error) from error

    def enrichment(
        kind: EnrichmentKind, target_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        token = body.get("result_set_token")
        try:
            if not isinstance(token, str):
                raise ResultTokenError("invalid result_set_token")
            claims = verify_result_token(token, token_secret)
            allowed = (
                claims.get("hotel_ids", [])
                if kind is EnrichmentKind.ENVIRONMENT
                else claims.get("route_ids", [])
            )
            if target_id not in allowed:
                raise ValueError("result_not_in_result_set")
            anchor = body.get("temperature_anchor_celsius")
            request: dict[str, object] = {"refresh": body.get("refresh", False)}
            if kind is EnrichmentKind.ENVIRONMENT:
                request["temperature_anchor_celsius"] = _finite_number(
                    anchor, "temperature_anchor_celsius"
                )
            if kind is EnrichmentKind.ENVIRONMENT and anchor is None:
                raise ValueError("temperature_anchor_celsius is required")
            if kind is EnrichmentKind.STREET_VIEW:
                point = body.get("point")
                if point is None:
                    point = _route_midpoint(claims, target_id)
                request["point"] = point
                if not _point_near_claimed_route(point, target_id, claims):
                    raise ValueError("street-view point must be within 50 meters of the route")
            if enrichment_service is None:
                return _enrichment_json(
                    None,
                    kind=kind,
                    target_id=target_id,
                    reason="configuration_missing",
                    base_result={
                        "request_identity": claims.get("request_identity"),
                        "result_id": target_id,
                    },
                )
            coordinates = None
            coordinate_claim = (
                claims.get("hotel_coordinates", {}).get(target_id)
                if kind is EnrichmentKind.ENVIRONMENT
                and isinstance(claims.get("hotel_coordinates"), dict)
                else None
            )
            if isinstance(coordinate_claim, dict):
                coordinates = Coordinates(
                    _finite_number(coordinate_claim.get("latitude"), "hotel.latitude"),
                    _finite_number(coordinate_claim.get("longitude"), "hotel.longitude"),
                )
            route_geometry = None
            route_claim = (
                claims.get("route_geometries", {}).get(target_id)
                if isinstance(claims.get("route_geometries"), dict)
                else None
            )
            if isinstance(route_claim, list):
                route_geometry = tuple(
                    tuple(point)
                    for point in route_claim
                    if isinstance(point, list) and len(point) == 2
                )
            return _enrichment_json(
                enrichment_service,
                kind=kind,
                target_id=target_id,
                request=request,
                coordinates=coordinates,
                route_geometry=route_geometry,
                base_result={
                    "request_identity": claims.get("request_identity"),
                    "result_id": target_id,
                },
            )
        except ResultTokenError as error:
            status = 410 if str(error) == "result_set_expired" else 400
            raise HTTPException(
                status_code=status, detail={"status": "error", "error_kind": str(error)}
            ) from error
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=400, detail={"status": "error", "error": str(error)}
            ) from error

    @app.post("/api/hotels/{hotel_id}/environment")
    def hotel_environment(hotel_id: str, body: dict[str, object]) -> dict[str, object]:
        return enrichment(EnrichmentKind.ENVIRONMENT, hotel_id, body)

    @app.post("/api/routes/{route_id}/canopy")
    def route_canopy(route_id: str, body: dict[str, object]) -> dict[str, object]:
        return enrichment(EnrichmentKind.SATELLITE_CANOPY, route_id, body)

    @app.post("/api/routes/{route_id}/street-view")
    def route_street_view(route_id: str, body: dict[str, object]) -> dict[str, object]:
        return enrichment(EnrichmentKind.STREET_VIEW, route_id, body)

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
    granularity = body.get("granularity", 60)
    if granularity is None:
        granularity = 60
    if isinstance(granularity, bool) or not isinstance(granularity, int):
        raise ValueError("granularity must be an integer")
    return HeatmapRequest(
        analytic_type=AnalyticType(body["analytic_type"]),
        latitude=latitude,
        longitude=longitude,
        start_date=date.fromisoformat(start_date),
        forecast=_required_bool(body, "forecast", default=True),
        threshold_celsius=threshold,
        direction=direction,
        granularity=granularity,
        start_hour=_optional_hour(body, "start_hour"),
        end_hour=_optional_hour(body, "end_hour"),
    )


def _env_params_request(body: dict[str, object]) -> EnvParamsRequest:
    latitude = _finite_number(body.get("latitude"), "latitude")
    longitude = _finite_number(body.get("longitude"), "longitude")
    start_date = body.get("start_date")
    if not isinstance(start_date, str):
        raise ValueError("start_date must be a date string")
    anchor = body.get("temperature_anchor_celsius")
    if anchor is not None:
        anchor = _finite_number(anchor, "temperature_anchor_celsius")
    hour = _optional_hour(body, "hour")
    return EnvParamsRequest(
        latitude=latitude,
        longitude=longitude,
        start_date=date.fromisoformat(start_date),
        temperature_anchor_celsius=anchor,
        hour=hour,
        start_hour=_optional_hour(body, "start_hour"),
        end_hour=_optional_hour(body, "end_hour"),
    )


def _parse_trip_request(body: dict[str, object]) -> TripAnalysisRequest:
    """Parse the frontend request into the provider-independent contract."""
    if "hour" in body:
        raise ValueError("hour is no longer accepted; provide start_hour and end_hour")
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
    start_hour = _required_hour(body, "start_hour")
    end_hour = _required_hour(body, "end_hour")
    mode = body.get("mode")
    if not isinstance(landmark, str) or not landmark:
        raise ValueError("landmark_name must be a non-empty string")
    if not isinstance(district, str) or not district:
        raise ValueError("district_name must be a non-empty string")
    if not isinstance(trip_date, str) or not trip_date:
        raise ValueError("date must be a non-empty string")
    if not isinstance(mode, str):
        raise ValueError("mode must be curated or exploratory")

    return TripAnalysisRequest(
        mode=TripMode(mode),
        origin=Coordinates(origin_lat, origin_lon),
        destination=Coordinates(dest_lat, dest_lon),
        landmark_name=landmark,
        district_name=district,
        date=trip_date,
        start_hour=start_hour,
        end_hour=end_hour,
        cautious=_required_bool(body, "cautious", default=False),
    )


def _trip_result(
    body: dict[str, object],
    *,
    allow_live: bool,
    trip_adapter: TripAnalysisAdapter | None,
    result_token_secret: str | None,
) -> dict[str, object]:
    """Run the trip analysis and serialize the shared product contract."""
    execution_mode = _execution_mode(body, allow_live=allow_live)
    request = _parse_trip_request(body)
    if trip_adapter is None:
        raise ValueError("trip analysis adapter is not configured")
    response = trip_adapter.analyze(request, execution_mode)
    if not isinstance(response, TripAnalysisResponse):
        raise ValueError("trip adapter returned an invalid response")
    if response.execution_mode is not execution_mode:
        raise ValueError("trip adapter returned the wrong execution mode")
    result = asdict(response)
    if response.state.value == "success" and result_token_secret:
        routes = result.get("routes") or {}
        alternatives = routes.get("alternatives", []) if isinstance(routes, dict) else []
        route_ids = [item.get("identity") for item in alternatives if isinstance(item, dict)]
        result["result_set_token"] = issue_result_token(
            {
                "request_identity": response.request_identity,
                "route_ids": route_ids,
                "route_geometries": {
                    item.get("identity"): item.get("geometry")
                    for item in alternatives
                    if isinstance(item, dict) and item.get("identity") is not None
                },
            },
            result_token_secret,
        )
    return result


def _execution_mode(body: dict[str, object], *, allow_live: bool) -> ExecutionMode:
    requested = body.get("execution_mode", ExecutionMode.FIXTURE.value)
    try:
        mode = ExecutionMode(requested)
    except ValueError as error:
        raise ValueError("execution_mode must be fixture or live") from error
    if mode is ExecutionMode.LIVE and not allow_live:
        raise ValueError("live execution is not enabled for this server")
    return mode


def _required_hour(body: dict[str, object], field: str) -> int:
    if field not in body:
        raise ValueError(f"{field} is required")
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be a whole hour between 0 and 23")
    return value


def _optional_hour(body: dict[str, object], field: str) -> int | None:
    value = body.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be finite numeric")
    return float(value)


def _hotel_weights(value: object) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("weights must be a JSON object")
    weights = {key: _finite_number(item, f"weights.{key}") for key, item in value.items()}
    # Use the domain validator so the API and local reranking have identical rules.
    NeighbourhoodHeatScorer().score((), weights=weights)
    return weights


def _hotel_heat_result(outcome: HotelHeatAnalysisOutcome) -> dict[str, object]:
    score = outcome.score
    return {
        "state": outcome.state.value,
        "district_name": outcome.district_name,
        "execution_mode": outcome.execution_mode.value,
        "reason": outcome.reason,
        "discovered_count": outcome.discovered_count,
        "usable_count": outcome.usable_count,
        "components": {
            name: asdict(outcome.components[name])
            for name in COMPONENTS
            if name in outcome.components
        },
        "ranking": None
        if score is None
        else {
            "weights": dict(score.weights),
            "weight_label": score.weight_label,
            "complete_candidate_count": score.complete_candidate_count,
            "ranked_output": score.ranked_output,
            "hotels": [
                {
                    "identity": asdict(hotel.identity),
                    "name": hotel.name,
                    "complete": hotel.complete,
                    "relative_aggregate": hotel.relative_aggregate,
                    "rank": hotel.rank,
                    "relative_percentile": hotel.relative_percentile,
                    "components": {
                        component: {
                            **asdict(hotel.components[component].assignment),
                            "percentile": hotel.components[component].percentile,
                        }
                        for component in COMPONENTS
                    },
                }
                for hotel in score.hotels
            ],
        },
    }


def _hotel_target_id(identity: dict[str, object]) -> str:
    object_type = identity.get("object_type")
    object_id = identity.get("object_id")
    if not isinstance(object_type, str) or not isinstance(object_id, int):
        raise ValueError("hotel identity is malformed")
    return f"{object_type}:{object_id}"


def _point_near_claimed_route(value: object, target_id: str, claims: dict[str, object]) -> bool:
    if not isinstance(value, dict):
        raise ValueError("point must be an object")
    latitude = _finite_number(value.get("latitude"), "point.latitude")
    longitude = _finite_number(value.get("longitude"), "point.longitude")
    geometries = claims.get("route_geometries")
    geometry = geometries.get(target_id) if isinstance(geometries, dict) else None
    if not isinstance(geometry, list):
        return False
    distances = [
        ((longitude - point[0]) * 111_000 * math.cos(math.radians(latitude))) ** 2
        + ((latitude - point[1]) * 111_000) ** 2
        for point in geometry
        if isinstance(point, (list, tuple)) and len(point) == 2
    ]
    return bool(distances) and min(distances) ** 0.5 <= 50


def _route_midpoint(claims: dict[str, object], target_id: str) -> dict[str, float]:
    geometries = claims.get("route_geometries")
    geometry = geometries.get(target_id) if isinstance(geometries, dict) else None
    if not isinstance(geometry, list) or not geometry:
        raise ValueError("route geometry is required")
    point = geometry[len(geometry) // 2]
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        raise ValueError("route geometry is malformed")
    return {"longitude": float(point[0]), "latitude": float(point[1])}


def _enrichment_json(
    service: EnrichmentService | None,
    *,
    kind: EnrichmentKind,
    target_id: str,
    request: dict[str, object] | None = None,
    base_result: dict[str, object] | None = None,
    coordinates: Coordinates | None = None,
    route_geometry: tuple[tuple[float, float], ...] | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    if reason is not None or service is None:
        return {
            "status": "success",
            "kind": kind.value,
            "target_id": target_id,
            "state": "unavailable",
            "reason": reason or "configuration_missing",
            "base_result": base_result or {},
            "usage": {"requested_calls": 0, "completed_calls": 0},
            "provenance": None,
            "limitations": [],
            "payload": None,
        }
    response = service.run(
        kind=kind,
        target_id=target_id,
        request=request,
        base_result=base_result,
        coordinates=coordinates,
        route_geometry=route_geometry,
    )
    return {"status": "success", **asdict(response)}
