from datetime import date
import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from app.api import create_fixture_server


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


def test_invalid_boolean_and_missing_fixture_return_unavailable() -> None:
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
            urlopen(Request(f"http://127.0.0.1:{server.server_port}/api/heatmap", data=body, method="POST"))
        except HTTPError as error:
            assert error.code == 400
            assert json.load(error)["status"] == "unavailable"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
