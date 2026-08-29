"""Temporal trip request and series-only response contracts for issue #44."""

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import _parse_trip_request, create_app
from app.domain.contracts import (
    Confidence,
    Coordinates,
    EnvironmentSeriesEntry,
    EnvironmentSeriesResult,
    ExecutionMode,
    Provenance,
    ResultState,
    TripAnalysisRequest,
    TripAnalysisResponse,
    TripMode,
)
from app.services.trip_adapters import FixtureTripAnalysisAdapter


def _trip_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "origin_latitude": 29.4245914,
        "origin_longitude": -98.4864288,
        "destination_latitude": 29.425833,
        "destination_longitude": -98.485833,
        "mode": "curated",
        "landmark_name": "The Alamo",
        "district_name": "Downtown San Antonio",
        "date": "2026-08-23",
        "start_hour": 8,
        "end_hour": 20,
    }
    body.update(overrides)
    return body


def _request(**overrides: object) -> TripAnalysisRequest:
    values: dict[str, object] = {
        "mode": TripMode.CURATED,
        "origin": Coordinates(29.4245914, -98.4864288),
        "destination": Coordinates(29.425833, -98.485833),
        "landmark_name": "The Alamo",
        "district_name": "Downtown San Antonio",
        "date": "2026-08-23",
        "start_hour": 8,
        "end_hour": 20,
        "cautious": False,
    }
    values.update(overrides)
    return TripAnalysisRequest(**values)  # type: ignore[arg-type]


def _provenance() -> Provenance:
    return Provenance(
        source="fixture",
        data_date="2026-08-23",
        confidence=Confidence.SUFFICIENT,
        retrieved_at="2026-08-24T00:00:00+00:00",
        transformation_version="trip-environment-series-v1",
        provider="fortyguard",
        response_status="completed",
        request_configuration={"start_hour": 8, "end_hour": 20},
        fresh=True,
        coverage=1.0,
    )


def _environment() -> EnvironmentSeriesResult:
    return EnvironmentSeriesResult(
        entries=(
            EnvironmentSeriesEntry(
                valid_time=datetime.fromisoformat("2026-08-23T08:00:00-05:00"),
                heat_index_celsius=None,
                humidity_percent=54.0,
            ),
            EnvironmentSeriesEntry(
                valid_time=datetime.fromisoformat("2026-08-23T09:00:00-05:00"),
                heat_index_celsius=33.2,
                humidity_percent=None,
            ),
        ),
        timezone="America/Chicago",
        temperature_anchor_celsius=36.4,
        warning="fixed temperature anchor; not a real 24-hour forecast",
        provenance=_provenance(),
    )


class TestTemporalTripRequest:
    def test_request_carries_the_traveler_window_without_a_visit_hour(self) -> None:
        request = _request()

        assert request.window.start_hour == 8
        assert request.window.end_hour == 20
        assert list(request.window.hours) == list(range(8, 20))
        assert not hasattr(request, "hour")

    @pytest.mark.parametrize(  # type: ignore[misc]
        ("overrides", "message"),
        [
            ({"start_hour": 8, "end_hour": 21}, "at most 12 hours"),
            ({"start_hour": 8, "end_hour": 8}, "before end_hour"),
            ({"start_hour": 20, "end_hour": 8}, "before end_hour"),
            ({"start_hour": 8.5, "end_hour": 20}, "whole hour"),
            ({"start_hour": 8, "end_hour": 24}, "whole hour"),
        ],
    )
    def test_request_reuses_time_window_validation(
        self, overrides: dict[str, object], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            _request(**overrides)


class TestSeriesReadyResponse:
    def test_series_ready_contains_raw_nullable_series_and_no_decisions(self) -> None:
        response = TripAnalysisResponse(
            request_identity="curated:2026-08-23:8-20",
            mode=TripMode.CURATED,
            execution_mode=ExecutionMode.FIXTURE,
            state=ResultState.SERIES_READY,
            environment=_environment(),
        )

        assert response.environment is not None
        assert response.environment.entries[0].heat_index_celsius is None
        assert response.environment.entries[1].humidity_percent is None
        assert response.best_time is None
        assert response.hotels is None
        assert response.routes is None

    def test_series_ready_requires_environment(self) -> None:
        with pytest.raises(ValueError, match="environment"):
            TripAnalysisResponse(
                request_identity="curated:2026-08-23:8-20",
                mode=TripMode.CURATED,
                execution_mode=ExecutionMode.FIXTURE,
                state=ResultState.SERIES_READY,
            )

    def test_series_ready_rejects_decision_sections(self) -> None:
        from tests.test_contracts import _valid_best_time

        with pytest.raises(ValueError, match="decision"):
            TripAnalysisResponse(
                request_identity="curated:2026-08-23:8-20",
                mode=TripMode.CURATED,
                execution_mode=ExecutionMode.FIXTURE,
                state=ResultState.SERIES_READY,
                environment=_environment(),
                best_time=_valid_best_time(),
            )

    def test_environment_rejects_empty_series(self) -> None:
        with pytest.raises(ValueError, match="entries"):
            EnvironmentSeriesResult(
                entries=(),
                timezone="America/Chicago",
                temperature_anchor_celsius=36.4,
                warning="fixed temperature anchor; not a real 24-hour forecast",
                provenance=_provenance(),
            )

    @pytest.mark.parametrize("humidity", [-0.1, 100.1, 999.0])  # type: ignore[misc]
    def test_entry_rejects_out_of_range_humidity(self, humidity: float) -> None:
        """Widening the entry to carry every parameter must not drop this bound."""
        with pytest.raises(ValueError, match="between 0 and 100"):
            EnvironmentSeriesEntry(
                valid_time=datetime.fromisoformat("2026-08-23T08:00:00-05:00"),
                heat_index_celsius=33.2,
                humidity_percent=humidity,
            )


class TestTemporalTripApi:
    def test_endpoint_accepts_a_valid_window(self) -> None:
        client = TestClient(
            create_app(
                Path("fixtures/heatmap-historical.json"),
                trip_adapter=FixtureTripAnalysisAdapter(Path("fixtures/trip-analysis.json")),
            )
        )

        response = client.post("/api/trip/analyze", json=_trip_body())

        assert response.status_code == 200
        assert response.json()["request_identity"] == "curated:2026-08-23:8-20"

    @pytest.mark.parametrize(  # type: ignore[misc]
        "overrides",
        [
            {"end_hour": None},
            {"start_hour": 8, "end_hour": 8},
            {"start_hour": 9, "end_hour": 8},
            {"start_hour": 0, "end_hour": 13},
            {"start_hour": 8.5, "end_hour": 20},
            {"start_hour": -1, "end_hour": 8},
            {"start_hour": 8, "end_hour": 24},
        ],
    )
    def test_endpoint_rejects_invalid_windows(self, overrides: dict[str, object]) -> None:
        client = TestClient(create_app(Path("fixtures/heatmap-historical.json")))

        response = client.post("/api/trip/analyze", json=_trip_body(**overrides))

        assert response.status_code == 400

    def test_endpoint_rejects_the_removed_selected_hour(self) -> None:
        client = TestClient(create_app(Path("fixtures/heatmap-historical.json")))
        body = _trip_body(hour=8)

        response = client.post("/api/trip/analyze", json=body)

        assert response.status_code == 400
        assert "no longer accepted" in response.json()["detail"]["error"]

    def test_api_parses_the_window_without_requiring_a_visit_hour(self) -> None:
        request = _parse_trip_request(
            {
                "origin_latitude": 29.4245914,
                "origin_longitude": -98.4864288,
                "destination_latitude": 29.425833,
                "destination_longitude": -98.485833,
                "mode": "curated",
                "landmark_name": "The Alamo",
                "district_name": "Downtown San Antonio",
                "date": "2026-08-23",
                "start_hour": 8,
                "end_hour": 20,
            }
        )

        assert request.window.start_time() == "08:00"
        assert request.window.end_time() == "19:00"

    def test_api_rejects_a_missing_window_bound(self) -> None:
        with pytest.raises(ValueError, match="end_hour"):
            _parse_trip_request(
                {
                    "origin_latitude": 29.4245914,
                    "origin_longitude": -98.4864288,
                    "destination_latitude": 29.425833,
                    "destination_longitude": -98.485833,
                    "mode": "curated",
                    "landmark_name": "The Alamo",
                    "district_name": "Downtown San Antonio",
                    "date": "2026-08-23",
                    "start_hour": 8,
                }
            )
