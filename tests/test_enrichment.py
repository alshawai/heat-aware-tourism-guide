from datetime import datetime, timezone
import pytest

from app.domain.contracts import Coordinates, EnrichmentState
from app.domain.enrichment import EnrichmentKind
from app.domain.ledger import CreditLedger
from app.domain.result_tokens import ResultTokenError, issue_result_token, verify_result_token
from app.services.cache import CacheService
from app.services.enrichment import EnrichmentService
from app.api import create_app
from fastapi.testclient import TestClient
from pathlib import Path
from typing import Any, cast
from app.domain.enrichment import EnrichmentAdapter


class Adapter:
    def __init__(
        self, payload: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self.payload = payload
        self.error = error

    def enrich(self, context: object, request: dict[str, Any]) -> dict[str, Any] | None:
        if self.error is not None:
            raise self.error
        return self.payload


def service(adapter: Adapter, *, budget: int = 1, live: bool = True) -> EnrichmentService:
    return EnrichmentService(
        ledger=CreditLedger(enrichment_budget=budget),
        adapters={EnrichmentKind.ENVIRONMENT: cast(EnrichmentAdapter, adapter)},
        estimates={"environment": 10},
        clock=lambda: datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
        live=live,
    )


def test_budget_exhaustion_preserves_base_result() -> None:
    configured = service(Adapter({"entries": []}), budget=0)
    result = configured.run(
        kind=EnrichmentKind.ENVIRONMENT,
        target_id="hotel-1",
        coordinates=Coordinates(29.42, -98.48),
        base_result={"rank": 1},
    )
    assert result.state is EnrichmentState.UNAVAILABLE
    assert result.reason == "budget_exhausted"
    assert result.base_result == {"rank": 1}


def test_fixture_success_does_not_consume_budget() -> None:
    configured = service(Adapter({"entries": [{"value": 32}]}), budget=1, live=False)
    result = configured.run(kind=EnrichmentKind.ENVIRONMENT, target_id="hotel-1")
    assert result.state is EnrichmentState.AVAILABLE
    assert result.provenance is not None
    assert result.provenance.source == "fixture"
    assert result.usage.completed_calls == 0


def test_partial_failure_preserves_base_result() -> None:
    configured = service(Adapter(error=RuntimeError("provider down")))
    result = configured.run(
        kind=EnrichmentKind.ENVIRONMENT,
        target_id="hotel-1",
        base_result={"rank": 1, "score": 0.8},
    )
    assert result.state is EnrichmentState.UNAVAILABLE
    assert result.reason == "provider_failure"
    assert result.base_result == {"rank": 1, "score": 0.8}


def test_result_tokens_are_signed_and_expire() -> None:
    issued = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    token = issue_result_token(
        {"request_identity": "r1", "hotel_ids": ["h1"]}, "secret", now=issued
    )
    assert verify_result_token(token, "secret", now=issued)["hotel_ids"] == ["h1"]
    with pytest.raises(ResultTokenError, match="result_set_expired"):
        verify_result_token(token, "secret", now=datetime(2026, 8, 30, 13, tzinfo=timezone.utc))
    with pytest.raises(ResultTokenError):
        verify_result_token(token + "x", "secret", now=issued)


def test_fresh_cache_hit_does_not_invoke_adapter_or_budget() -> None:
    cache = CacheService()
    first = EnrichmentService(
        ledger=CreditLedger(enrichment_budget=1),
        adapters={
            EnrichmentKind.SATELLITE_CANOPY: cast(
                EnrichmentAdapter, Adapter({"canopy_percentage": 20})
            )
        },
        estimates={"satellite_canopy": 12},
        clock=lambda: datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
        live=True,
        cache=cache,
    )
    first_result = first.run(kind=EnrichmentKind.SATELLITE_CANOPY, target_id="route-1")
    assert first_result.state is EnrichmentState.AVAILABLE
    second = EnrichmentService(
        ledger=CreditLedger(enrichment_budget=0),
        adapters={},
        estimates={"satellite_canopy": 12},
        clock=lambda: datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
        live=True,
        cache=cache,
    )
    cached = second.run(kind=EnrichmentKind.SATELLITE_CANOPY, target_id="route-1")
    assert cached.state is EnrichmentState.AVAILABLE
    assert cached.provenance is not None
    assert cached.provenance.source == "cache"


def test_api_enrichment_requires_token_and_preserves_fixture_boundary() -> None:
    fixture_path = Path("fixtures/heatmap-historical.json")
    client = TestClient(create_app(fixture_path))
    missing = client.post(
        "/api/hotels/node:1/environment",
        json={"temperature_anchor_celsius": 32},
    )
    assert missing.status_code == 400
    assert missing.json()["detail"]["error_kind"] == "invalid result_set_token"

    token = issue_result_token(
        {
            "request_identity": "fixture-test",
            "hotel_ids": ["node:1"],
            "hotel_coordinates": {"node:1": {"latitude": 29.42, "longitude": -98.48}},
        },
        "api-secret",
    )
    app = create_app(
        fixture_path,
        result_token_secret="api-secret",
    )
    response = TestClient(app).post(
        "/api/hotels/node:1/environment",
        json={"result_set_token": token, "temperature_anchor_celsius": 32},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "available"
    assert payload["payload"]["temperature_anchor_celsius"] == 32
    assert payload["provenance"]["source"] == "fixture"
    assert payload["usage"]["completed_calls"] == 0


def test_api_route_enrichment_uses_midpoint_and_rejects_distant_point() -> None:
    geometry = [[-98.48, 29.42], [-98.479, 29.421]]
    token = issue_result_token(
        {
            "request_identity": "route-test",
            "route_ids": ["route-1"],
            "route_geometries": {"route-1": geometry},
        },
        "route-secret",
    )
    client = TestClient(
        create_app(
            Path("fixtures/heatmap-historical.json"),
            result_token_secret="route-secret",
        )
    )
    midpoint = client.post("/api/routes/route-1/street-view", json={"result_set_token": token})
    assert midpoint.status_code == 200
    assert midpoint.json()["state"] == "unavailable"
    assert midpoint.json()["reason"] == "fixture_data_unavailable"
    distant = client.post(
        "/api/routes/route-1/street-view",
        json={"result_set_token": token, "point": {"latitude": 30, "longitude": -97}},
    )
    assert distant.status_code == 400
