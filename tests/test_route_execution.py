"""Route execution cache and fixture degradation for issue #18 phase 3."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.domain.contracts import Coordinates
from app.domain.provenance import AcquisitionRecord
from app.domain.routing import RouteRequest
from app.integrations.osrm.errors import OsrmTransportError
from app.services.cache import CacheService
from app.services.routing import RouteExecution, RouteUnavailable, route_request_payload
from app.services.sidecars import write_sidecar


def _request(
    *,
    origin: Coordinates = Coordinates(29.4245914, -98.4864288),
    destination: Coordinates = Coordinates(29.425833, -98.485833),
    profile: str = "foot",
    alternatives: bool = True,
    overview: str = "full",
    geometries: str = "geojson",
    steps: bool = False,
    provider_instance: str = "fossgis-routed-foot",
    request_version: str = "osrm-route-v1",
) -> RouteRequest:
    return RouteRequest(
        origin=origin,
        destination=destination,
        profile=profile,
        alternatives=alternatives,
        overview=overview,
        geometries=geometries,
        steps=steps,
        provider_instance=provider_instance,
        request_version=request_version,
    )


def _payload() -> dict[str, object]:
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": 132.0,
                "duration": 105.0,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-98.4864288, 29.4245914], [-98.485833, 29.425833]],
                },
            }
        ],
    }


def _fixture(tmp_path: Path, request: RouteRequest) -> Path:
    path = tmp_path / "route.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    write_sidecar(
        path,
        AcquisitionRecord(
            source="provider",
            provider="fossgis-osrm",
            endpoint="https://routing.example/route/v1",
            request_configuration=route_request_payload(request),
            retrieved_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
            data_date="2026-08-23",
            status="ok",
            schema_version="v1",
            provider_config_version="osrm-config-v1",
            activity_id=None,
            derived_from=(),
            response_metadata={},
        ),
    )
    return path


def test_live_success_is_cached_and_replayed_without_second_provider_call(tmp_path: Path) -> None:
    calls = 0

    def loader(request: RouteRequest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OsrmTransportError("offline")
        return _payload()

    execution = RouteExecution(
        fixture_path=tmp_path / "missing.json",
        live_loader=loader,
        cache=CacheService(),
        endpoint="https://routing.example/route/v1",
    )
    live = execution.run(_request(), live=True)
    replay = execution.run(_request(), live=True)

    assert live.source == "provider"
    assert replay.source == "cache"
    assert replay.stale is True
    assert calls == 2


def test_fixture_replay_requires_exact_request_and_configuration_identity(tmp_path: Path) -> None:
    request = _request()
    execution = RouteExecution(
        fixture_path=_fixture(tmp_path, request),
        endpoint="https://routing.example/route/v1",
    )
    replay = execution.run(request)
    assert replay.source == "fixture"
    assert replay.routes.routes[0].identity == "route-1"

    with pytest.raises(RouteUnavailable):
        execution.run(_request(profile="walking"))

    mismatched_version = RouteExecution(
        fixture_path=execution.fixture_path,
        endpoint="https://routing.example/route/v1",
        provider_config_version="osrm-config-v2",
    )
    with pytest.raises(RouteUnavailable):
        mismatched_version.run(request)


def test_live_failure_exhaustion_is_explicit(tmp_path: Path) -> None:
    execution = RouteExecution(
        fixture_path=tmp_path / "missing.json",
        live_loader=lambda request: (_ for _ in ()).throw(OsrmTransportError("offline")),
    )
    with pytest.raises(RouteUnavailable, match="no matching cache entry or fixture"):
        execution.run(_request(), live=True)


def test_complete_identity_changes_for_route_options_and_provider_instance() -> None:
    baseline = route_request_payload(_request())
    assert route_request_payload(_request(steps=True)) != baseline
    assert route_request_payload(_request(provider_instance="another-instance")) != baseline
    assert route_request_payload(_request(destination=Coordinates(29.43, -98.48))) != baseline
