"""Fixture acquisition: real provider runs committed as raw fixtures + sidecars.

The acquisition path (ADR 0004) submits one documented request through the
live client, proves the result normalizes into the shared domain shape, then
writes the sanitized raw provider payload and an honest acquisition-record
sidecar. Actual credit usage lands in the caller's ledger via the client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Callable, Mapping, Protocol, cast

from app.domain.provenance import AcquisitionRecord
from app.domain.routing import RouteRequest
from app.domain.contracts import Coordinates
from app.domain.security import sanitize_payload
from app.integrations.fortyguard.client import ActivityMetadata
from app.integrations.fortyguard.contracts import (
    PROVIDER_CONFIG_VERSION,
    AnalyticType,
    EnvParamsRequest,
    EnvParamsResult,
    HeatmapRequest,
    normalize_env_params_response,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.live import (
    build_documented_env_params_payload,
    build_documented_heatmap_payload,
    env_params_transformations,
    request_transformations,
    translate_heatmap_response,
)
from app.services.execution import env_params_request_payload, heatmap_request_payload
from app.services.sidecars import write_sidecar
from app.settings import FortyGuardPollingSettings
from app.integrations.osrm.client import normalize_response
from app.integrations.overpass.buildings import (
    building_request_payload,
    osm_source_timestamp,
)
from app.services.route_shade import RouteShadeService, _shared_bbox
from app.domain.route_shade import solar_position

SAN_ANTONIO_LATITUDE = 29.4241
SAN_ANTONIO_LONGITUDE = -98.4936
ENV_OBSERVATION_LATITUDE = 29.4259
ENV_OBSERVATION_LONGITUDE = -98.4861
CANONICAL_DATA_DATE = date(2026, 8, 23)

_CREDIT_METADATA_KEYS = ("credits_used", "request_id")


@dataclass(frozen=True)
class HeatmapScenario:
    name: str
    filename: str
    build_request: Callable[[], HeatmapRequest]


@dataclass(frozen=True)
class EnvParamsScenario:
    name: str
    filename: str
    build_request: Callable[[], EnvParamsRequest]


@dataclass(frozen=True)
class AcquisitionOutcome:
    fixture_path: Path
    record: AcquisitionRecord


@dataclass(frozen=True)
class OsrmScenario:
    name: str
    filename: str
    request: RouteRequest
    minimum_routes: int = 1
    maximum_routes: int | None = None


class _OsrmLoader(Protocol):
    @property
    def transport(self) -> object: ...

    def load(self, request: RouteRequest) -> Mapping[str, object]: ...


class _BuildingLoader(Protocol):
    _transport: object

    def query_buildings(self, aoi: object) -> dict[str, object]: ...


class AcquisitionClient(Protocol):
    def submit_and_poll(
        self,
        endpoint: str,
        payload: Mapping[str, object],
        *,
        sleep: Callable[[float], None] = ...,
        max_polls: int = ...,
        interval_seconds: float = ...,
        status_404_grace_checks: int = ...,
    ) -> tuple[Mapping[str, object], ActivityMetadata]: ...


OSRM_SCENARIOS: dict[str, OsrmScenario] = {
    "canonical-menger-alamo": OsrmScenario(
        "canonical-menger-alamo",
        "menger-alamo.json",
        RouteRequest(
            Coordinates(29.4245914, -98.4864288),
            Coordinates(29.425833, -98.485833),
            "foot",
            True,
            "full",
            "geojson",
            False,
            "fossgis-routed-foot",
            "v1",
        ),
    ),
    "main-plaza-market-square": OsrmScenario(
        "main-plaza-market-square",
        "main-plaza-market-square.json",
        RouteRequest(
            Coordinates(29.4245773, -98.4935063),
            Coordinates(29.4254009, -98.4994785),
            "foot",
            True,
            "full",
            "geojson",
            False,
            "fossgis-routed-foot",
            "v1",
        ),
        maximum_routes=1,
    ),
    "cathedral-governors-palace": OsrmScenario(
        "cathedral-governors-palace",
        "cathedral-governors-palace.json",
        RouteRequest(
            Coordinates(29.4245590, -98.4942042),
            Coordinates(29.4248225, -98.4959872),
            "foot",
            True,
            "full",
            "geojson",
            False,
            "fossgis-routed-foot",
            "v1",
        ),
        minimum_routes=2,
    ),
}


def osrm_request_payload(request: RouteRequest) -> dict[str, object]:
    """Keep the acquisition identity identical to production route caching."""
    from app.services.routing import route_request_payload

    return route_request_payload(request)


def acquire_osrm_fixture(
    scenario: OsrmScenario,
    client: _OsrmLoader,
    *,
    out_dir: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> AcquisitionOutcome:
    """Acquire, normalize, validate cardinality, then atomically write one OSRM payload."""
    payload = client.load(scenario.request)
    routes = normalize_response(payload, provider_instance=scenario.request.provider_instance)
    count = len(routes.routes)
    if count < scenario.minimum_routes or (
        scenario.maximum_routes is not None and count > scenario.maximum_routes
    ):
        raise ValueError(f"{scenario.name} returned {count} routes; fixture was not written")
    retrieved_at = clock().astimezone(timezone.utc)
    record = AcquisitionRecord(
        source="provider",
        provider="fossgis-osrm",
        endpoint=cast(str, getattr(client.transport, "base_url")),
        request_configuration=osrm_request_payload(scenario.request),
        retrieved_at=retrieved_at,
        data_date=retrieved_at.date().isoformat(),
        status="ok",
        schema_version="v1",
        provider_config_version="osrm-config-v1",
        activity_id=None,
        derived_from=(),
        transformations=(),
        response_metadata={
            "route_count": count,
            "distance_unit": "m",
            "duration_unit": "s",
            "waypoint_snaps": payload.get("waypoints", []),
        },
    )
    fixture_path = _write_provider_fixture(out_dir, scenario.filename, payload)
    write_sidecar(fixture_path, record)
    return AcquisitionOutcome(fixture_path, record)


def acquire_overpass_building_fixture(
    routes: object,
    client: _BuildingLoader,
    *,
    out_dir: Path,
    filename: str = "cathedral-governors-palace-buildings.json",
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> AcquisitionOutcome:
    """Acquire Cathedral's shared production AOI and validate height coverage."""
    from app.domain.routing import RouteSet

    route_set = cast(RouteSet, routes)
    aoi = _shared_bbox(route_set, 250.0)
    payload = client.query_buildings(aoi)
    source_timestamp = osm_source_timestamp(payload)
    execution = type(
        "Execution",
        (),
        {
            "identity": lambda self, candidate: building_request_payload(
                candidate, search_distance_m=250.0, model_version="route-shade-v1"
            ),
            "run": lambda self, candidate: type(
                "Outcome",
                (),
                {
                    "payload": payload,
                    "source": "provider",
                    "stale": False,
                    "retrieved_at": clock(),
                    "data_date": source_timestamp.date().isoformat(),
                },
            )(),
        },
    )()
    service = RouteShadeService(
        execution, corridor_buffer_m=250.0, minimum_building_coverage=0.70, metres_per_level=3.0
    )
    centroid = route_set.routes[0].geometry.coordinates[
        len(route_set.routes[0].geometry.coordinates) // 2
    ]
    solar = solar_position(clock(), centroid[1], centroid[0])
    outcome = service.load(route_set, solar, clock())
    coverages = [e.building_coverage for e in outcome.evidence.values()]
    if any(coverage >= 0.70 for coverage in coverages):
        raise ValueError(f"building coverage gate failed: {coverages}")
    record = AcquisitionRecord(
        source="provider",
        provider="overpass-api-de",
        endpoint=cast(str, getattr(client._transport, "endpoint")),
        request_configuration=building_request_payload(
            aoi, search_distance_m=250.0, model_version="route-shade-v1"
        ),
        retrieved_at=clock().astimezone(timezone.utc),
        data_date=source_timestamp.date().isoformat(),
        status="ok",
        schema_version="building-v1",
        provider_config_version="overpass-building-config-v1",
        activity_id=None,
        derived_from=(),
        transformations=(),
        response_metadata={
            "source_timestamp": source_timestamp.isoformat(),
            "element_count": len(cast(list[object], payload["elements"]))
            if isinstance(payload.get("elements"), list)
            else 0,
            "response_format": "overpass-json",
            "response_version": "0.7",
        },
    )
    fixture_path = _write_provider_fixture(out_dir, filename, payload)
    write_sidecar(fixture_path, record)
    return AcquisitionOutcome(fixture_path, record)


HEATMAP_SCENARIOS: dict[str, HeatmapScenario] = {
    "tcm-historical": HeatmapScenario(
        "tcm-historical",
        "heatmap-tcm-historical.json",
        lambda: HeatmapRequest(
            AnalyticType.TCM,
            SAN_ANTONIO_LATITUDE,
            SAN_ANTONIO_LONGITUDE,
            CANONICAL_DATA_DATE,
            forecast=False,
        ),
    ),
    "tcm-forecast": HeatmapScenario(
        "tcm-forecast",
        "heatmap-tcm-forecast.json",
        lambda: HeatmapRequest(
            AnalyticType.TCM,
            SAN_ANTONIO_LATITUDE,
            SAN_ANTONIO_LONGITUDE,
            date.today(),
            forecast=True,
        ),
    ),
    "exceedance-historical": HeatmapScenario(
        "exceedance-historical",
        "heatmap-exceedance-historical.json",
        lambda: HeatmapRequest(
            AnalyticType.EXCEEDANCE,
            SAN_ANTONIO_LATITUDE,
            SAN_ANTONIO_LONGITUDE,
            CANONICAL_DATA_DATE,
            forecast=False,
            threshold_celsius=35.0,
            direction="above",
        ),
    ),
}

ENV_PARAMS_SCENARIOS: dict[str, EnvParamsScenario] = {
    "env-params-anchor35": EnvParamsScenario(
        "env-params-anchor35",
        "env-params-anchor35.json",
        lambda: EnvParamsRequest(
            ENV_OBSERVATION_LATITUDE,
            ENV_OBSERVATION_LONGITUDE,
            date.today(),
            35.0,
            hour=13,
        ),
    ),
}


def acquire_heatmap_fixture(
    scenario: HeatmapScenario,
    client: AcquisitionClient,
    *,
    out_dir: Path,
    provider_config_version: str = PROVIDER_CONFIG_VERSION,
    schema_version: str = "v1",
    polling: FortyGuardPollingSettings | None = None,
) -> AcquisitionOutcome:
    """Run one documented heatmap request and commit the raw fixture + sidecar."""
    _preflight_fixture_paths(out_dir, scenario.filename)
    request = scenario.build_request()
    payload = build_documented_heatmap_payload(request)
    bounds = polling or FortyGuardPollingSettings()
    result, metadata = client.submit_and_poll(
        "/v1/heatmap",
        payload,
        max_polls=bounds.max_polls,
        interval_seconds=bounds.interval_seconds,
        status_404_grace_checks=bounds.status_404_grace_checks,
    )
    translated = translate_heatmap_response(result, request=request)
    normalize_heatmap_response(
        translated,
        request=request,
        retrieved_at=metadata.submitted_at,
        activity_id=metadata.activity_id,
    )
    record = AcquisitionRecord(
        source="provider",
        provider="fortyguard",
        endpoint="/v1/heatmap",
        request_configuration=heatmap_request_payload(request),
        retrieved_at=metadata.submitted_at,
        data_date=str(translated["data_date"]),
        status="ok",
        schema_version=schema_version,
        provider_config_version=provider_config_version,
        activity_id=metadata.activity_id,
        derived_from=(),
        transformations=request_transformations(request),
        response_metadata={
            **metadata.response_metadata,
            "raw_units_present": _raw_unit_keys(result),
            "freshness_present": "fresh" in result or "forecast" in result,
            "terminal_status": metadata.status_transitions[-1]
            if metadata.status_transitions
            else None,
        },
    )
    fixture_path = _write_fixture(out_dir, scenario.filename, result)
    write_sidecar(fixture_path, record)
    return AcquisitionOutcome(fixture_path, record)


def acquire_env_params_fixture(
    scenario: EnvParamsScenario,
    client: AcquisitionClient,
    *,
    out_dir: Path,
    provider_config_version: str = PROVIDER_CONFIG_VERSION,
    schema_version: str = "v1",
    polling: FortyGuardPollingSettings | None = None,
    validate: Callable[[EnvParamsResult], None] | None = None,
) -> AcquisitionOutcome:
    """Run one documented env-params request and commit the raw fixture + sidecar."""
    _preflight_fixture_paths(out_dir, scenario.filename)
    request = scenario.build_request()
    payload = build_documented_env_params_payload(request)
    bounds = polling or FortyGuardPollingSettings()
    result, metadata = client.submit_and_poll(
        "/v1/env_params",
        payload,
        max_polls=bounds.max_polls,
        interval_seconds=bounds.interval_seconds,
        status_404_grace_checks=bounds.status_404_grace_checks,
    )
    normalized = normalize_env_params_response(result, request=request)
    if validate is not None:
        validate(normalized)
    data_date = normalized.entries[0].valid_time.date().isoformat()
    record = AcquisitionRecord(
        source="provider",
        provider="fortyguard",
        endpoint="/v1/env_params",
        request_configuration=env_params_request_payload(request),
        retrieved_at=metadata.submitted_at,
        data_date=data_date,
        status="ok",
        schema_version=schema_version,
        provider_config_version=provider_config_version,
        activity_id=metadata.activity_id,
        derived_from=(),
        transformations=env_params_transformations(),
        response_metadata={
            **metadata.response_metadata,
            "raw_units_present": _raw_unit_keys(result),
            "freshness_present": "fresh" in result or "forecast" in result,
            "terminal_status": metadata.status_transitions[-1]
            if metadata.status_transitions
            else None,
        },
    )
    fixture_path = _write_fixture(out_dir, scenario.filename, result)
    write_sidecar(fixture_path, record)
    return AcquisitionOutcome(fixture_path, record)


def _write_fixture(out_dir: Path, filename: str, result: Mapping[str, object]) -> Path:
    payload = {
        key: value for key, value in dict(result).items() if key not in _CREDIT_METADATA_KEYS
    }
    sanitized = sanitize_payload(payload)
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = out_dir / filename
    fixture_path.write_text(json.dumps(sanitized, indent=2) + "\n", encoding="utf-8")
    return fixture_path


def _raw_unit_keys(result: Mapping[str, object]) -> list[str]:
    return sorted(str(key) for key in result if "unit" in str(key).lower())


def _preflight_fixture_paths(out_dir: Path, filename: str) -> None:
    """Reject either member of an existing fixture pair before provider spend."""
    fixture_path = out_dir / filename
    sidecar = fixture_path.with_name(f"{fixture_path.stem}.acquisition.json")
    if fixture_path.exists() or sidecar.exists():
        raise FileExistsError(f"refusing to overwrite existing fixture {fixture_path}")


def _write_provider_fixture(out_dir: Path, filename: str, result: Mapping[str, object]) -> Path:
    """Write public acquisitions without ever replacing an existing observation."""
    payload = sanitize_payload(dict(result))
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = out_dir / filename
    if (
        fixture_path.exists()
        or fixture_path.with_name(f"{fixture_path.stem}.acquisition.json").exists()
    ):
        raise FileExistsError(f"refusing to overwrite existing fixture {fixture_path}")
    fixture_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return fixture_path
