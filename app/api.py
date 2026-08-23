"""Minimal product-facing HTTP boundary for fixture-backed analysis."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.execution import HeatmapExecution
from app.fortyguard import AnalyticType, HeatmapRequest


def _result_json(result: Any) -> dict[str, object]:
    return {
        "tiles": [asdict(tile) for tile in result.tiles],
        "provenance": asdict(result.provenance),
    }


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def create_fixture_server(fixture_path: Path) -> ThreadingHTTPServer:
    execution = HeatmapExecution(fixture_path=fixture_path)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/heatmap":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                request = HeatmapRequest(
                    AnalyticType(body["analytic_type"]),
                    float(body["latitude"]),
                    float(body["longitude"]),
                    date.fromisoformat(body["start_date"]),
                    bool(body.get("forecast", True)),
                    body.get("threshold_celsius"),
                    body.get("direction"),
                )
                response = json.dumps(_result_json(execution.run(request)), default=_json_default).encode()
                self.send_response(200)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                response = json.dumps({"error": str(error), "status": "unavailable"}).encode()
                self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)
