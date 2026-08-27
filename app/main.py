"""Run the fixture-backed Heat-Aware Tourism Guide API."""

import os
from pathlib import Path

import uvicorn

from app.api import create_app
from app.trip_adapters import FixtureTripAnalysisAdapter


ROOT = Path(__file__).resolve().parent.parent

app = create_app(
    ROOT / "fixtures/heatmap-historical.json",
    allow_live=os.getenv("ALLOW_LIVE", "false").lower() == "true",
    frontend_dist=ROOT / "frontend/dist",
    trip_adapter=FixtureTripAnalysisAdapter(ROOT / "fixtures/trip-analysis.json"),
)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
