"""Shared fixture/live execution path for normalized heatmap results."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Callable, Mapping

from app.cache import CacheService
from app.domain import CacheKey
from app.fortyguard import HeatmapRequest, HeatmapResult, ProviderError, normalize_heatmap_response


class HeatmapExecution:
    def __init__(
        self,
        *,
        fixture_path: Path,
        live_loader: Callable[[HeatmapRequest], Mapping[str, object]] | None = None,
        cache: CacheService | None = None,
        endpoint: str = "/v1/heatmap",
        schema_version: str = "v1",
    ) -> None:
        self.fixture_path = fixture_path
        self.live_loader = live_loader
        self.cache = cache
        self.endpoint = endpoint
        self.schema_version = schema_version

    def run(self, request: HeatmapRequest, *, live: bool = False) -> HeatmapResult:
        if live:
            if self.live_loader is None:
                raise RuntimeError("live execution is not configured")
            request_payload = _request_payload(request)
            try:
                payload = self.live_loader(request)
            except (ConnectionError, OSError, ProviderError, TimeoutError):
                if self.cache is None:
                    raise
                cached = self.cache.get(CacheKey.create(self.endpoint, self.schema_version, request_payload))
                if cached is None:
                    raise
                return normalize_heatmap_response(
                    cached.payload,
                    request=request,
                    retrieved_at=cached.provenance.retrieved_at,
                    activity_id=cached.provenance.activity_id,
                    source="cache",
                    data_date=cached.provenance.data_date,
                )
            result = normalize_heatmap_response(
                payload, request=request, retrieved_at=datetime.now().astimezone(), source="provider"
            )
            if self.cache is not None:
                self.cache.put(
                    self.endpoint,
                    self.schema_version,
                    request_payload,
                    payload,
                    retrieved_at=result.provenance.retrieved_at,
                    data_date=result.provenance.data_date,
                    activity_id=result.provenance.activity_id,
                    forecast=request.forecast,
                )
            return result
        with self.fixture_path.open(encoding="utf-8") as fixture:
            payload = json.load(fixture)
        if not isinstance(payload, Mapping):
            raise ValueError("fixture must contain a JSON object")
        expected_mode = "forecast" if request.forecast else "historical"
        if payload.get("mode") != expected_mode:
            raise ValueError("fixture forecast/historical mode does not match request")
        return normalize_heatmap_response(
            payload, request=request, retrieved_at=datetime.now().astimezone(), source="fixture"
        )


def _request_payload(request: HeatmapRequest) -> dict[str, object]:
    return {
        "analytic_type": request.analytic_type.value,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "start_date": request.start_date.isoformat(),
        "forecast": request.forecast,
        "threshold_celsius": request.threshold_celsius,
        "direction": request.direction,
    }
