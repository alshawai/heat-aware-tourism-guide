from datetime import date
import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from app.api import create_app, create_fixture_server
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


def test_place_search_catalog_is_identical_across_server_implementations() -> None:
    expected = {
        "menger": {
            "id": "menger-hotel",
            "name": "Menger Hotel",
            "context": "San Antonio, TX",
            "latitude": 29.4245914,
            "longitude": -98.4864288,
        },
        "alamo": {
            "id": "the-alamo",
            "name": "The Alamo",
            "context": "San Antonio, TX",
            "latitude": 29.425833,
            "longitude": -98.485833,
        },
        "main": {
            "id": "main-plaza",
            "name": "Main Plaza",
            "context": "San Antonio, TX",
            "latitude": 29.4245773,
            "longitude": -98.4935063,
        },
        "market": {
            "id": "historic-market-square-el-mercado",
            "name": "Historic Market Square (El Mercado)",
            "context": "San Antonio, TX",
            "latitude": 29.4254009,
            "longitude": -98.4994785,
        },
        "CATHEDRAL": {
            "id": "san-fernando-cathedral",
            "name": "San Fernando Cathedral",
            "context": "San Antonio, TX",
            "latitude": 29.424559,
            "longitude": -98.4942042,
        },
        "palace": {
            "id": "spanish-governors-palace",
            "name": "Spanish Governor's Palace",
            "context": "San Antonio, TX",
            "latitude": 29.4248225,
            "longitude": -98.4959872,
        },
        "briscoe": {
            "id": "briscoe-western-art-museum",
            "name": "Briscoe Western Art Museum",
            "context": "San Antonio, TX",
            "latitude": 29.4228983,
            "longitude": -98.4888465,
        },
        "tower": {
            "id": "tower-of-the-americas",
            "name": "Tower of the Americas",
            "context": "San Antonio, TX",
            "latitude": 29.4190825,
            "longitude": -98.4835734,
        },
    }
    server = create_fixture_server(Path("fixtures/heatmap-historical.json"))
    fastapi_client = TestClient(create_app(Path("fixtures/heatmap-historical.json")))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for query, place in expected.items():
            stdlib_response = urlopen(
                f"http://127.0.0.1:{server.server_port}/api/places/search?q={query}"
            )
            stdlib_result = json.load(stdlib_response)
            fastapi_result = fastapi_client.get("/api/places/search", params={"q": query}).json()

            assert stdlib_result == fastapi_result == {"places": [place]}

        stdlib_result = json.load(
            urlopen(f"http://127.0.0.1:{server.server_port}/api/places/search?q=the")
        )
        fastapi_result = fastapi_client.get("/api/places/search", params={"q": "the"}).json()
        assert stdlib_result == fastapi_result
        assert [place["id"] for place in stdlib_result["places"]] == [
            "the-alamo",
            "san-fernando-cathedral",
            "tower-of-the-americas",
        ]
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
        trip_adapter=FixtureTripAnalysisAdapter(Path("fixtures/trips/menger-alamo.trip.json")),
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
                "date": "2024-07-15",
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
        assert result["state"] == "degraded"
        assert result["execution_mode"] == "fixture"
        assert len(result["best_time"]["hourly"]) == 1
        assert result["best_time"]["recommendation_hour"] == 8
        assert result["best_time"]["hourly"][0]["metric"]["unit"] == "C"
        assert result["best_time"]["hourly"][0]["metric"]["label"] == "noaa_heat_index"
        assert result["best_time"]["temporal_evidence"] == "inconsistent"
        assert result["best_time"]["provenance"]["provider"] == "fortyguard"
        assert result["routes"]["routing_provenance"]["provider"] == "fossgis-osrm"
        assert len(result["hotels"]["ranked"]) == 6
        assert result["routes"]["route_set_state"] == "single_route"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_trip_analysis_endpoint_returns_unavailable_for_unmatched_window() -> None:
    server = create_fixture_server(
        Path("fixtures/heatmap-historical.json"),
        trip_adapter=FixtureTripAnalysisAdapter(Path("fixtures/trips/menger-alamo.trip.json")),
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
                "date": "2024-07-15",
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
        trip_adapter=FixtureTripAnalysisAdapter(
            Path("fixtures/trips/briscoe-tower-unavailable.trip.json")
        ),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "mode": "exploratory",
                "execution_mode": "fixture",
                "origin_latitude": 29.4228983,
                "origin_longitude": -98.4888465,
                "destination_latitude": 29.4190825,
                "destination_longitude": -98.4835734,
                "landmark_name": "Tower of the Americas",
                "district_name": "Downtown San Antonio",
                "date": "2024-07-15",
                "start_hour": 10,
                "end_hour": 17,
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
        assert result["unavailable"]["code"] == "provider_data_missing"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_trip_analysis_rejects_untrusted_metric_and_provenance_fields() -> None:
    server = create_fixture_server(
        Path("fixtures/heatmap-historical.json"),
        trip_adapter=FixtureTripAnalysisAdapter(Path("fixtures/trips/menger-alamo.trip.json")),
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
                "date": "2024-07-15",
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
