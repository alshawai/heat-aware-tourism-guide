"""Shared fixture/live execution path for normalized heatmap results."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Callable, Mapping

from app.fortyguard import HeatmapRequest, HeatmapResult, normalize_heatmap_response


class HeatmapExecution:
    def __init__(
        self,
        *,
        fixture_path: Path,
        live_loader: Callable[[HeatmapRequest], Mapping[str, object]] | None = None,
    ) -> None:
        self.fixture_path = fixture_path
        self.live_loader = live_loader

    def run(self, request: HeatmapRequest, *, live: bool = False) -> HeatmapResult:
        if live:
            if self.live_loader is None:
                raise RuntimeError("live execution is not configured")
            payload = self.live_loader(request)
            return normalize_heatmap_response(
                payload, request=request, retrieved_at=datetime.now().astimezone(), source="provider"
            )
        with self.fixture_path.open(encoding="utf-8") as fixture:
            payload = json.load(fixture)
        if not isinstance(payload, Mapping):
            raise ValueError("fixture must contain a JSON object")
        return normalize_heatmap_response(
            payload, request=request, retrieved_at=datetime.now().astimezone(), source="fixture"
        )
