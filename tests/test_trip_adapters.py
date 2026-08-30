from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from app.domain.contracts import (
    Coordinates,
    ExecutionMode,
    ResultState,
    TemporalEvidenceState,
    TripAnalysisRequest,
    TripMode,
)
from app.services.trip_adapters import FixtureTripAnalysisAdapter, LiveTripAnalysisAdapter


TRIP_FIXTURES = tuple(sorted(Path("fixtures/trips").glob("*.trip.json")))
CANONICAL = Path("fixtures/trips/menger-alamo.trip.json")


def _request() -> TripAnalysisRequest:
    return TripAnalysisRequest(
        mode=TripMode.CURATED,
        origin=Coordinates(29.4245914, -98.4864288),
        destination=Coordinates(29.425833, -98.485833),
        landmark_name="The Alamo",
        district_name="Downtown San Antonio",
        date="2024-07-15",
        start_hour=8,
        end_hour=20,
        cautious=False,
    )


def _payload() -> dict[str, object]:
    payload = json.loads(CANONICAL.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_fixture_and_live_adapters_return_the_same_v2_sections() -> None:
    fixture = FixtureTripAnalysisAdapter(TRIP_FIXTURES).analyze(_request())
    live = LiveTripAnalysisAdapter(lambda _: _payload()).analyze(_request())

    fixture_dict = asdict(fixture)
    live_dict = asdict(live)
    for section in ("best_time", "hotels", "routes"):
        assert fixture_dict[section] == live_dict[section]
    assert fixture.execution_mode is ExecutionMode.FIXTURE
    assert live.execution_mode is ExecutionMode.LIVE


def test_canonical_snapshot_is_truthful_single_route_with_inconsistent_time() -> None:
    response = FixtureTripAnalysisAdapter(TRIP_FIXTURES).analyze(_request())

    assert response.state is ResultState.DEGRADED
    assert response.best_time is not None
    assert response.best_time.temporal_evidence is TemporalEvidenceState.INCONSISTENT
    assert response.best_time.recommendation_time is None
    assert response.best_time.recommendation_timezone is None
    assert response.hotels is not None and response.hotels.usable_count >= 5
    assert response.routes is not None and len(response.routes.alternatives) == 1
    assert response.routes.alternatives[0].distance_m == 193.1
    assert response.routes.alternatives[0].duration_s == 154.7


def test_fixture_adapter_returns_unavailable_for_unmatched_window() -> None:
    response = FixtureTripAnalysisAdapter(TRIP_FIXTURES).analyze(replace(_request(), start_hour=9))

    assert response.state is ResultState.UNAVAILABLE
    assert response.unavailable is not None
    assert response.unavailable.code == "scenario_unavailable"


def test_live_adapter_rejects_non_object_payload() -> None:
    adapter = LiveTripAnalysisAdapter(lambda _: [])  # type: ignore[arg-type,return-value]
    with pytest.raises(ValueError, match="must return an object"):
        adapter.analyze(_request(), ExecutionMode.LIVE)


def test_fixture_adapter_rejects_legacy_product_schema(tmp_path: Path) -> None:
    fixture = tmp_path / "legacy.json"
    fixture.write_text('{"schema_version":"trip-contract-v1"}', encoding="utf-8")
    fixture.with_name("legacy.acquisition.json").write_text(
        json.dumps(
            {
                "source": "synthesized",
                "provider": "heat-aware-tourism-guide",
                "endpoint": "local:test",
                "request_configuration": {
                    "mode": "curated",
                    "landmark_name": "The Alamo",
                    "district_name": "Downtown San Antonio",
                    "date": "2024-07-15",
                    "start_hour": 8,
                    "end_hour": 20,
                    "cautious": False,
                    "origin": {"latitude": 29.4245914, "longitude": -98.4864288},
                    "destination": {"latitude": 29.425833, "longitude": -98.485833},
                },
                "retrieved_at": None,
                "data_date": "2024-07-15",
                "status": "ok",
                "schema_version": "trip-contract-v1",
                "provider_config_version": "test-v1",
                "activity_id": None,
                "derived_from": [],
                "transformations": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must use trip-contract-v2"):
        FixtureTripAnalysisAdapter(fixture)
