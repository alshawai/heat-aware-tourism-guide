"""End-to-end fixture-mode coverage for the four Issue 23 trip snapshots."""

from __future__ import annotations

import json
from pathlib import Path
import socket
from collections.abc import Callable
from typing import Any, cast
import urllib.request

from fastapi.testclient import TestClient
import pytest

from app.services.trip_adapters import FixtureTripAnalysisAdapter
from app.settings import AppSettings
from app.wiring import create_production_app


ROOT = Path(__file__).resolve().parents[1]
TRIP_FIXTURES = tuple(
    ROOT / "fixtures" / "trips" / name
    for name in (
        "menger-alamo.trip.json",
        "main-plaza-market-square.trip.json",
        "cathedral-governors-palace.trip.json",
        "briscoe-tower-unavailable.trip.json",
    )
)


def _request(path: Path) -> dict[str, object]:
    sidecar = json.loads(
        path.with_name(f"{path.stem}.acquisition.json").read_text(encoding="utf-8")
    )
    identity = sidecar["request_configuration"]
    return {
        "mode": identity["mode"],
        "execution_mode": "fixture",
        "origin_latitude": identity["origin"]["latitude"],
        "origin_longitude": identity["origin"]["longitude"],
        "destination_latitude": identity["destination"]["latitude"],
        "destination_longitude": identity["destination"]["longitude"],
        "landmark_name": identity["landmark_name"],
        "district_name": identity["district_name"],
        "date": identity["date"],
        "start_hour": identity["start_hour"],
        "end_hour": identity["end_hour"],
        "cautious": identity["cautious"],
    }


@pytest.fixture  # type: ignore[misc]
def offline_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[str]]:
    external_calls: list[str] = []

    def blocked(name: str) -> Callable[..., Any]:
        def fail(*args: object, **kwargs: object) -> Any:
            external_calls.append(name)
            raise AssertionError(f"external seam called in fixture mode: {name}")

        return fail

    original_connect = socket.socket.connect

    def loopback_only(sock: socket.socket, address: object) -> Any:
        host = address[0] if isinstance(address, tuple) and address else ""
        if host not in {"127.0.0.1", "::1", "localhost"}:
            return blocked("socket.connect")(sock, address)
        return original_connect(  # pragma: no cover - TestClient is in-process
            sock, cast(tuple[Any, ...] | str | bytes, address)
        )

    monkeypatch.setattr(socket, "create_connection", blocked("socket.create_connection"))
    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    monkeypatch.setattr(urllib.request, "urlopen", blocked("urllib.request.urlopen"))
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", blocked("opener.open"))
    monkeypatch.setattr("app.integrations.osrm.client.OsrmClient.load", blocked("osrm.load"))
    monkeypatch.setattr(
        "app.integrations.overpass.client.OverpassClient.query", blocked("overpass.query")
    )
    monkeypatch.setattr(
        "app.integrations.overpass.client.OverpassClient.query_buildings",
        blocked("overpass.query_buildings"),
    )
    monkeypatch.setattr(
        "app.integrations.fortyguard.client.FortyGuardClient.submit_and_poll",
        blocked("fortyguard.submit_and_poll"),
    )
    monkeypatch.setattr("app.services.cache.CacheService.get", blocked("cache.get"))
    monkeypatch.setattr("app.services.cache.CacheService.put", blocked("cache.put"))
    monkeypatch.setattr("app.wiring.build_ledger", blocked("ledger"))

    settings = AppSettings(
        allow_live=False,
        fortyguard_api_key=None,
        fortyguard_base_url="https://blocked.invalid",
        ledger_path=ROOT / "does-not-exist" / "ledger.jsonl",
    )
    adapter = FixtureTripAnalysisAdapter(TRIP_FIXTURES)
    app = create_production_app(settings, trip_adapter=adapter, frontend_dist=ROOT / "missing-dist")
    return TestClient(app), external_calls


def test_four_exact_snapshot_requests_and_place_searches_are_fully_offline(
    offline_client: tuple[TestClient, list[str]],
) -> None:
    client, external_calls = offline_client

    for query in ("menger", "main", "cathedral", "briscoe", "tower"):
        response = client.get("/api/places/search", params={"q": query})
        assert response.status_code == 200
        assert response.json()["places"]

    results: list[dict[str, object]] = []
    for fixture_path in TRIP_FIXTURES:
        response = client.post("/api/trip/analyze", json=_request(fixture_path))
        assert response.status_code == 200
        result = response.json()
        snapshot = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert {key: result[key] for key in snapshot} == snapshot
        results.append(result)

    canonical, main_plaza, cathedral, briscoe = results
    assert canonical["state"] == "degraded"
    assert canonical["best_time"]["temporal_evidence"] == "inconsistent"  # type: ignore[index]
    assert len(canonical["hotels"]["ranked"]) == 6  # type: ignore[index]
    assert canonical["routes"]["route_set_state"] == "single_route"  # type: ignore[index]
    assert canonical["routes"]["routing_provenance"]["provider"] == "fossgis-osrm"  # type: ignore[index]

    assert main_plaza["state"] == "degraded"
    assert main_plaza["routes"]["route_set_state"] == "single_route"  # type: ignore[index]

    assert cathedral["state"] == "degraded"
    assert len(cathedral["routes"]["alternatives"]) == 2  # type: ignore[index]
    assert cathedral["routes"]["decision_state"] == (  # type: ignore[index]
        "insufficient_shade_comparison_required"
    )
    assert cathedral["routes"]["recommended_id"] is None  # type: ignore[index]
    assert cathedral["routes"]["confidence"] == "insufficient"  # type: ignore[index]
    assert all(
        route["building_coverage"] < 0.35
        for route in cathedral["routes"]["alternatives"]  # type: ignore[index]
    )
    assert cathedral["hotels"]["enrichment"]["code"] == "optional_provider_failure"  # type: ignore[index]

    assert briscoe["state"] == "unavailable"
    assert briscoe["unavailable"]["code"] == "provider_data_missing"  # type: ignore[index]
    assert briscoe["best_time"] is briscoe["hotels"] is briscoe["routes"] is None
    assert external_calls == []


@pytest.mark.parametrize(  # type: ignore[misc]
    "mutation",
    (
        {"origin_latitude": 29.4245778},
        {
            "origin_latitude": 29.4254009,
            "origin_longitude": -98.4994785,
            "destination_latitude": 29.4245773,
            "destination_longitude": -98.4935063,
        },
        {"date": "2024-07-16"},
        {"start_hour": 9},
    ),
    ids=("near-coordinate", "reversed", "wrong-date", "wrong-window"),
)
def test_non_exact_fixture_requests_are_structurally_unavailable(
    offline_client: tuple[TestClient, list[str]], mutation: dict[str, object]
) -> None:
    client, external_calls = offline_client
    request = _request(TRIP_FIXTURES[1]) | mutation
    response = client.post("/api/trip/analyze", json=request)
    assert response.status_code == 200
    result = response.json()
    assert result["state"] == "unavailable"
    assert result["unavailable"]["code"] == "scenario_unavailable"
    assert result["best_time"] is result["hotels"] is result["routes"] is None
    assert external_calls == []
