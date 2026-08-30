from datetime import date
import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from app.api import create_fixture_server
from app.services.trip_adapters import FixtureTripAnalysisAdapter

pytestmark = pytest.mark.integration


class MalformedTripAdapter:
    def analyze(self, request: object, execution_mode: object) -> object:
        return object()


def test_fixture_backed_http_flow_returns_normalized_domain_result() -> None:
    server = create_fixture_server(Path("fixtures/heatmap-historical.json"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "analytic_type": "tcm",
                "latitude": 29.4241,
                "longitude": -98.4936,
                "start_date": date(2026, 8, 23).isoformat(),
                "forecast": False,
            }
        ).encode()
        response = urlopen(
            Request(
                f"http://127.0.0.1:{server.server_port}/api/heatmap",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        )
        result = json.load(response)
        assert result["tiles"][0]["value_celsius"] == 33.2
        assert result["provenance"]["source"] == "fixture"
        assert result["provenance"]["forecast"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_invalid_boolean_returns_client_error() -> None:
    server = create_fixture_server(Path("fixtures/missing.json"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "analytic_type": "tcm",
                "latitude": 29.4241,
                "longitude": -98.4936,
                "start_date": "2026-08-23",
                "forecast": "false",
            }
        ).encode()
        try:
            urlopen(
                Request(
                    f"http://127.0.0.1:{server.server_port}/api/heatmap", data=body, method="POST"
                )
            )
        except HTTPError as error:
            assert error.code == 400
            assert json.load(error)["status"] == "error"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_place_search_returns_server_owned_places() -> None:
    server = create_fixture_server(Path("fixtures/heatmap-historical.json"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = urlopen(f"http://127.0.0.1:{server.server_port}/api/places/search?q=alamo")
        result = json.load(response)
        assert [place["name"] for place in result["places"]] == ["The Alamo"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_non_object_json_body_returns_client_error() -> None:
    server = create_fixture_server(Path("fixtures/heatmap-historical.json"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            urlopen(
                Request(
                    f"http://127.0.0.1:{server.server_port}/api/heatmap", data=b"[]", method="POST"
                )
            )
        except HTTPError as error:
            assert error.code == 400
            assert json.load(error)["status"] == "error"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_trip_analysis_endpoint_returns_ranked_hotels_and_route_decision() -> None:
    server = create_fixture_server(
        Path("fixtures/heatmap-historical.json"),
        trip_adapter=FixtureTripAnalysisAdapter(Path("fixtures/trip-analysis.json")),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
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
        ).encode()
        response = urlopen(
            Request(
                f"http://127.0.0.1:{server.server_port}/api/trip/analyze",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        )
        result = json.load(response)
        assert result["state"] == "success"
        assert result["execution_mode"] == "fixture"
        assert len(result["best_time"]["hourly"]) == 3
        assert result["best_time"]["recommendation_hour"] == 8
        assert result["best_time"]["hourly"][0]["metric"]["unit"] == "C"
        assert result["best_time"]["hourly"][0]["metric"]["label"] == "provider_tcm"
        assert result["best_time"]["provenance"]["transformation_version"] == "trip-contract-v1"
        assert result["best_time"]["provenance"]["provider"] == "fortyguard"
        assert result["routes"]["provenance"]["provider"] == "osrm_openstreetmap_and_fortyguard"
        assert result["hotels"]["ranked"][0]["identity"] == "cooler"
        assert result["routes"]["recommended_id"] == "shady"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_trip_analysis_endpoint_returns_unavailable_for_unmatched_window() -> None:
    server = create_fixture_server(
        Path("fixtures/heatmap-historical.json"),
        trip_adapter=FixtureTripAnalysisAdapter(Path("fixtures/trip-analysis.json")),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "origin_latitude": 29.4245914,
                "origin_longitude": -98.4864288,
                "destination_latitude": 29.425833,
                "destination_longitude": -98.485833,
                "mode": "curated",
                "landmark_name": "The Alamo",
                "district_name": "Downtown San Antonio",
                "date": "2026-08-23",
                "start_hour": 9,
                "end_hour": 20,
            }
        ).encode()
        response = urlopen(
            Request(
                f"http://127.0.0.1:{server.server_port}/api/trip/analyze",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        )

        result = json.load(response)
        assert result["state"] == "unavailable"
        assert result["unavailable"]["reason"] == ("no matching fixture for the requested trip")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_trip_analysis_returns_explicit_unavailable_contract() -> None:
    server = create_fixture_server(
        Path("fixtures/heatmap-historical.json"),
        trip_adapter=FixtureTripAnalysisAdapter(Path("fixtures/trip-analysis-unavailable.json")),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "mode": "exploratory",
                "execution_mode": "fixture",
                "origin_latitude": 29.4245914,
                "origin_longitude": -98.4864288,
                "destination_latitude": 29.425833,
                "destination_longitude": -98.485833,
                "landmark_name": "The Alamo",
                "district_name": "Downtown San Antonio",
                "date": "2026-08-23",
                "start_hour": 8,
                "end_hour": 20,
            }
        ).encode()
        response = urlopen(
            Request(
                f"http://127.0.0.1:{server.server_port}/api/trip/analyze",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        )
        result = json.load(response)
        assert result["state"] == "unavailable"
        assert result["mode"] == "exploratory"
        assert result["best_time"] is None
        assert (
            result["unavailable"]["reason"]
            == "no matching fixture for the requested exploratory trip"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_trip_analysis_rejects_untrusted_metric_and_provenance_fields() -> None:
    server = create_fixture_server(
        Path("fixtures/heatmap-historical.json"),
        trip_adapter=FixtureTripAnalysisAdapter(Path("fixtures/trip-analysis.json")),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "origin_latitude": 29.4245915,
                "origin_longitude": -98.4864287,
                "destination_latitude": 29.4258331,
                "destination_longitude": -98.4858332,
                "mode": "curated",
                "landmark_name": "The Alamo",
                "district_name": "Downtown San Antonio",
                "date": "2026-08-23",
                "start_hour": 8,
                "end_hour": 20,
                "heat_metric": "heat_index_celsius",
                "heat_value": 38,
                "heat_threshold": 35,
                "building_coverage": 0.9,
                "hotels": [
                    {
                        "identity": "a",
                        "components": {"night": 30, "hot_hours": 5, "persistence": 2, "day": 32},
                    },
                ],
                "routes": [
                    {"identity": "r1", "distance_m": 1000, "duration_s": 600},
                ],
                "shade": {"r1": 50},
            }
        ).encode()
        with pytest.raises(HTTPError) as caught:
            urlopen(
                Request(
                    f"http://127.0.0.1:{server.server_port}/api/trip/analyze",
                    data=body,
                    method="POST",
                )
            )
        assert caught.value.code == 400
        assert json.load(caught.value)["status"] == "error"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_trip_analysis_rejects_malformed_adapter_response() -> None:
    server = create_fixture_server(
        Path("fixtures/heatmap-historical.json"),
        trip_adapter=MalformedTripAdapter(),  # type: ignore[arg-type]
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
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
        ).encode()
        with pytest.raises(HTTPError) as caught:
            urlopen(
                Request(
                    f"http://127.0.0.1:{server.server_port}/api/trip/analyze",
                    data=body,
                    method="POST",
                )
            )
        assert caught.value.code == 400
        assert "invalid response" in json.load(caught.value)["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_heatmap_response_includes_complete_activity_metadata() -> None:
    from datetime import datetime, timezone
    from app.integrations.fortyguard.client import ActivityMetadata
    from app.integrations.fortyguard.live import LiveHeatmapPayload
    from app.services.execution import HeatmapExecution

    payload = json.loads(Path("fixtures/heatmap-historical.json").read_text())
    activity = ActivityMetadata(
        "act-42",
        datetime(2026, 8, 23, 14, tzinfo=timezone.utc),
        "/v1/heatmap",
        ("analytic_type", "latitude"),
        ("Processing", "Completed"),
        {"request_id": "req-1"},
    )
    execution = HeatmapExecution(
        fixture_path=Path("fixtures/heatmap-historical.json"),
        live_loader=lambda _: LiveHeatmapPayload(payload, activity=activity),
    )
    server = create_fixture_server(
        Path("fixtures/heatmap-historical.json"),
        execution=execution,
        allow_live=True,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "analytic_type": "tcm",
                "latitude": 29.4241,
                "longitude": -98.4936,
                "start_date": "2026-08-23",
                "forecast": False,
                "execution_mode": "live",
            }
        ).encode()
        response = urlopen(
            Request(
                f"http://127.0.0.1:{server.server_port}/api/heatmap",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        )
        result = json.load(response)
        assert "activity" in result
        act = result["activity"]
        assert act["activity_id"] == "act-42"
        assert act["endpoint"] == "/v1/heatmap"
        assert act["request_fields"] == ["analytic_type", "latitude"]
        assert act["status_transitions"] == ["Processing", "Completed"]
        assert act["response_metadata"] == {"request_id": "req-1"}
        assert "submitted_at" in act
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_missing_fixture_returns_service_unavailable_not_client_error() -> None:
    server = create_fixture_server(Path("fixtures/missing.json"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "analytic_type": "tcm",
                "latitude": 29.4241,
                "longitude": -98.4936,
                "start_date": "2026-08-23",
                "forecast": False,
            }
        ).encode()
        with pytest.raises(HTTPError) as caught:
            urlopen(
                Request(
                    f"http://127.0.0.1:{server.server_port}/api/heatmap", data=body, method="POST"
                )
            )
        assert caught.value.code == 503
        assert json.load(caught.value)["status"] == "unavailable"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
