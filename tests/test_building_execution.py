"""Shared OSM building acquisition: exact cache, exact fixture, explicit unavailability."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.domain.hotels import BoundingBox
from app.domain.provenance import AcquisitionRecord, CacheKey
from app.domain.route_shade import ShadeConfidence, solar_position
from app.integrations.osrm.client import normalize_response
from app.integrations.overpass.buildings import (
    build_building_query,
    building_request_payload,
    osm_source_timestamp,
)
from app.integrations.overpass.errors import OverpassError, OverpassRateLimited
from app.services.building_execution import BuildingExecution, BuildingsUnavailable
from app.services.cache import CacheService
from app.services.route_shade import RouteShadeService, _shared_bbox
from app.services.sidecars import write_sidecar

ENDPOINT = "https://overpass.example/api/interpreter"
AOI = BoundingBox(29.4223, -98.4890, 29.4281, -98.4832)
OTHER_AOI = BoundingBox(29.4223, -98.4890, 29.4281, -98.4820)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CANONICAL_BUILDINGS = FIXTURES / "acquired" / "overpass-buildings-canonical.json"
CANONICAL_ROUTE = FIXTURES / "acquired" / "osrm-canonical.json"


def _response(osm_base: str = "2026-08-24T18:03:11Z") -> dict[str, Any]:
    return {
        "version": 0.6,
        "osm3s": {"timestamp_osm_base": osm_base},
        "elements": [
            {
                "type": "way",
                "id": 1,
                "tags": {"building": "yes", "height": "18"},
                "geometry": [
                    {"lat": 29.4250, "lon": -98.4866},
                    {"lat": 29.4250, "lon": -98.4863},
                    {"lat": 29.4252, "lon": -98.4863},
                    {"lat": 29.4252, "lon": -98.4866},
                    {"lat": 29.4250, "lon": -98.4866},
                ],
            }
        ],
    }


def _execution(**overrides: Any) -> BuildingExecution:
    values: dict[str, Any] = {
        "endpoint": ENDPOINT,
        "search_distance_m": 250.0,
        "clock": lambda: datetime(2026, 8, 30, 9, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return BuildingExecution(**values)


def _fixture(tmp_path: Path, identity: dict[str, Any], **overrides: Any) -> Path:
    path = tmp_path / "buildings.json"
    path.write_text(json.dumps(_response("2026-08-20T04:00:00Z")), encoding="utf-8")
    values: dict[str, Any] = {
        "source": "synthesized",
        "endpoint": ENDPOINT,
        "request_configuration": identity,
        "retrieved_at": None,
        "data_date": "2026-08-20",
        "status": "ok",
        "schema_version": "building-v1",
        "provider_config_version": "overpass-building-config-v1",
        "activity_id": None,
    }
    values.update(overrides)
    write_sidecar(path, AcquisitionRecord(**values))
    return path


def test_building_query_selects_both_building_tags_for_ways_and_relations() -> None:
    query = build_building_query(AOI)

    assert query.startswith("[out:json][timeout:60];")
    assert query.endswith("out body geom;")
    for tag in ("building", "building:part"):
        for object_type in ("way", "relation"):
            assert f'{object_type}["{tag}"](29.4223,-98.489,29.4281,-98.4832);' in query


def test_live_success_caches_under_the_complete_request_identity() -> None:
    cache = CacheService()
    execution = _execution(live_loader=lambda aoi: _response(), cache=cache)

    outcome = execution.run(AOI)

    assert (outcome.source, outcome.stale) == ("provider", False)
    assert outcome.data_date == "2026-08-24"
    assert outcome.retrieved_at == datetime(2026, 8, 30, 9, tzinfo=timezone.utc)
    key = CacheKey.create(
        ENDPOINT, "building-v1", execution.identity(AOI), "overpass-building-config-v1"
    )
    assert cache.get(key) is not None


def test_provider_failure_replays_the_exact_cache_entry_and_keeps_the_osm_data_date() -> None:
    calls = 0

    def loader(aoi: BoundingBox) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OverpassRateLimited("throttled")
        return _response()

    execution = _execution(live_loader=loader, cache=CacheService())
    live = execution.run(AOI)
    replay = execution.run(AOI)

    assert calls == 2
    assert (replay.source, replay.stale) == ("cache", True)
    assert replay.data_date == live.data_date == "2026-08-24"
    assert replay.reason is not None and "stale" in replay.reason


def test_a_different_aoi_never_replays_another_aois_cache_entry() -> None:
    execution = _execution(live_loader=lambda aoi: _response(), cache=CacheService())
    execution.run(AOI)
    execution.live_loader = lambda aoi: (_ for _ in ()).throw(OverpassError("offline"))

    assert execution.run(AOI).source == "cache"
    with pytest.raises(BuildingsUnavailable, match="no matching cache entry or fixture"):
        execution.run(OTHER_AOI)


def test_matching_fixture_replays_as_stale_with_its_own_osm_data_date(tmp_path: Path) -> None:
    execution = _execution()
    outcome = _execution(
        fixture_path=_fixture(tmp_path, execution.identity(AOI)),
        live_loader=lambda aoi: (_ for _ in ()).throw(OverpassError("offline")),
    ).run(AOI)

    assert (outcome.source, outcome.stale) == ("fixture", True)
    assert outcome.data_date == "2026-08-20"
    assert outcome.retrieved_at is None


@pytest.mark.parametrize(  # type: ignore[misc]
    ("execution_overrides", "sidecar_overrides"),
    [
        ({}, {"request_configuration": {"aoi": "somewhere else"}}),
        ({}, {"endpoint": "https://overpass.other/api/interpreter"}),
        ({}, {"schema_version": "building-v2"}),
        ({}, {"provider_config_version": "overpass-building-config-v2"}),
        ({}, {"status": "failed", "data_date": None}),
        ({"model_version": "route-shade-v2"}, {}),
        ({"search_distance_m": 400.0}, {}),
    ],
)
def test_fixture_replay_requires_exact_request_identity(
    tmp_path: Path,
    execution_overrides: dict[str, Any],
    sidecar_overrides: dict[str, Any],
) -> None:
    identity = _execution().identity(AOI)
    execution = _execution(
        fixture_path=_fixture(tmp_path, identity, **sidecar_overrides),
        live_loader=lambda aoi: (_ for _ in ()).throw(OverpassError("offline")),
        **execution_overrides,
    )

    with pytest.raises(BuildingsUnavailable):
        execution.run(AOI)


def test_a_response_without_an_osm_source_timestamp_is_a_provider_failure() -> None:
    execution = _execution(live_loader=lambda aoi: {"elements": []}, cache=CacheService())

    with pytest.raises(BuildingsUnavailable):
        execution.run(AOI)
    with pytest.raises(OverpassError, match="missing its OSM source timestamp"):
        osm_source_timestamp({"elements": []})


def test_unconfigured_live_acquisition_without_replay_is_explicit() -> None:
    with pytest.raises(BuildingsUnavailable, match="not configured"):
        _execution().run(AOI)


def test_request_identity_separates_aoi_search_distance_and_model_version() -> None:
    baseline = building_request_payload(
        AOI, search_distance_m=250.0, model_version="route-shade-v1"
    )

    assert (
        building_request_payload(OTHER_AOI, search_distance_m=250.0, model_version="route-shade-v1")
        != baseline
    )
    assert (
        building_request_payload(AOI, search_distance_m=400.0, model_version="route-shade-v1")
        != baseline
    )
    assert (
        building_request_payload(AOI, search_distance_m=250.0, model_version="route-shade-v2")
        != baseline
    )


def _canonical_routes() -> Any:
    return normalize_response(
        json.loads(CANONICAL_ROUTE.read_text(encoding="utf-8")),
        provider_instance="fossgis-routed-foot",
    )


def test_the_committed_canonical_building_fixture_matches_the_canonical_route_aoi() -> None:
    routes = _canonical_routes()
    execution = BuildingExecution(
        fixture_path=CANONICAL_BUILDINGS,
        endpoint="https://overpass-api.de/api/interpreter",
        search_distance_m=250.0,
    )

    outcome = execution.run(_shared_bbox(routes, 250.0))

    assert (outcome.source, outcome.stale) == ("fixture", True)
    assert outcome.data_date == osm_source_timestamp(outcome.payload).date().isoformat()


def test_canonical_fixture_replay_yields_sufficient_daytime_shade_evidence() -> None:
    routes = _canonical_routes()
    service = RouteShadeService(
        BuildingExecution(
            fixture_path=CANONICAL_BUILDINGS,
            endpoint="https://overpass-api.de/api/interpreter",
            search_distance_m=250.0,
        )
    )
    instant = datetime(2026, 8, 29, 10, 30, tzinfo=ZoneInfo("America/Chicago"))
    solar = solar_position(instant, 29.4252122, -98.4861309)

    evidence = service.load(routes, solar, instant)["route-1"]

    assert evidence.confidence is ShadeConfidence.SUFFICIENT
    assert evidence.building_coverage >= 0.70
    assert evidence.dropped_geometry_count == 0
    assert 0 < evidence.modeled_shade_percent <= 100


def test_shade_evidence_is_explicitly_unavailable_when_no_building_source_answers() -> None:
    service = RouteShadeService(_execution())
    instant = datetime(2026, 8, 29, 10, 30, tzinfo=ZoneInfo("America/Chicago"))
    solar = solar_position(instant, 29.4252122, -98.4861309)

    evidence = service.load(_canonical_routes(), solar, instant)

    assert set(evidence) == {"route-1"}
    unavailable = evidence["route-1"]
    assert unavailable.confidence is ShadeConfidence.INSUFFICIENT
    assert unavailable.modeled_shade_percent == 0.0
    assert unavailable.building_coverage == 0.0
    assert any("no OSM building geometry was available" in item for item in unavailable.limitations)
