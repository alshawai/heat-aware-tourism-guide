from datetime import date
import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

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
