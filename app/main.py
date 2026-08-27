"""Production entry point: settings load and live-stack composition at import."""

from __future__ import annotations

from pathlib import Path

from app.wiring import create_production_app

ROOT = Path(__file__).resolve().parents[1]

app = create_production_app(frontend_dist=ROOT / "frontend" / "dist")
