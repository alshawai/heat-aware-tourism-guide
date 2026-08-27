"""Acquisition machinery: real provider runs become raw fixtures + sidecars (ADR 0004)."""

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from app.domain.ledger import CreditLedger
from app.domain.provenance import AcquisitionRecord
from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.errors import ProviderError
from app.services.acquisition import (
    ENV_PARAMS_SCENARIOS,
    HEATMAP_SCENARIOS,
    acquire_env_params_fixture,
    acquire_heatmap_fixture,
)
from app.services.execution import HeatmapExecution

CLOCK = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)

RAW_TCM_RESULT: dict[str, object] = {
    "map_data": {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[-98.50, 29.42], [-98.49, 29.42], [-98.49, 29.43], [-98.50, 29.43], [-98.50, 29.42]]
                    ],
                },
                "properties": {"id": "tile-1", "average_temperature": 36.7},
            }
        ],
    },
    "stats_data": {"average": 36.7},
}

ENV_RESULT: dict[str, object] = {
    "timestamp": "2026-08-28T13:00:00-07:00",
    "timezone": "GMT-7",
    "offset": -7,
    "interval": "1h",
    "count": 1,
    "heat_index_celsius": [33.2],
    "relative_humidity_percent": [21.5],
}


class FakeTransport:
    def __init__(self, result: dict[str, object]) -> None:
        self._result = result

    def post(self, endpoint: str, payload: object, api_key: str) -> dict[str, object]:
        return {"activity_id": "activity-acq-1"}

    def get(self, endpoint: str, api_key: str) -> dict[str, object]:
        return {
            "status": "Completed",
            "result": self._result,
            "credits_used": 2,
            "request_id": "req-1",
        }


def _client(result: dict[str, object], ledger: CreditLedger | None = None) -> FortyGuardClient:
    return FortyGuardClient(
        FakeTransport(result), "secret", clock=lambda: CLOCK, ledger=ledger
    )


def test_heatmap_acquisition_writes_raw_fixture_and_sidecar(tmp_path: Path) -> None:
    outcome = acquire_heatmap_fixture(
        HEATMAP_SCENARIOS["tcm-historical"], _client(RAW_TCM_RESULT), out_dir=tmp_path
    )
    fixture_path = tmp_path / "heatmap-tcm-historical.json"
    assert outcome.fixture_path == fixture_path

    committed = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert committed == RAW_TCM_RESULT  # raw provider shape, no credit metadata
    assert "credits_used" not in committed
    assert "request_id" not in committed

    record = AcquisitionRecord.from_payload(
        json.loads(
            (tmp_path / "heatmap-tcm-historical.acquisition.json").read_text(encoding="utf-8")
        )
    )
    assert record == outcome.record
    assert record.source == "provider"
    assert record.endpoint == "/v1/heatmap"
    assert record.status == "ok"
    assert record.activity_id == "activity-acq-1"
    assert record.retrieved_at == CLOCK
    assert record.data_date == "2026-08-23"
    assert record.provider_config_version == "fortyguard-config-v1"
    assert record.request_configuration == {
        "analytic_type": "tcm",
        "latitude": 29.4241,
        "longitude": -98.4936,
        "start_date": "2026-08-23",
        "forecast": False,
        "threshold_celsius": None,
        "direction": None,
        "granularity": 60,
    }
    stamps = tuple((t.name, t.version) for t in record.transformations)
    assert stamps == (
        ("live_envelope_unwrapped", 1),
        ("point_to_aoi_expansion", 1),
        ("valid_time_from_request", 1),
        ("tcm_unit_celsius", 1),
    )


def test_acquired_heatmap_fixture_replays_through_execution(tmp_path: Path) -> None:
    outcome = acquire_heatmap_fixture(
        HEATMAP_SCENARIOS["tcm-historical"], _client(RAW_TCM_RESULT), out_dir=tmp_path
    )
    from app.integrations.fortyguard.contracts import AnalyticType, HeatmapRequest

    request = HeatmapRequest(
        AnalyticType.TCM, 29.4241, -98.4936, date(2026, 8, 23), forecast=False
    )
    result = HeatmapExecution(fixture_path=outcome.fixture_path).run(request)
    assert result.provenance.source == "fixture"
    assert result.provenance.activity_id == "activity-acq-1"
    assert result.tiles[0].value_celsius == 36.7


def test_heatmap_acquisition_rejects_invalid_provider_results(tmp_path: Path) -> None:
    with pytest.raises(ProviderError):
        acquire_heatmap_fixture(
            HEATMAP_SCENARIOS["tcm-historical"], _client({"map_data": {}}), out_dir=tmp_path
        )
    assert list(tmp_path.iterdir()) == []


def test_env_params_acquisition_writes_raw_fixture_and_sidecar(tmp_path: Path) -> None:
    outcome = acquire_env_params_fixture(
        ENV_PARAMS_SCENARIOS["env-params-anchor35"], _client(ENV_RESULT), out_dir=tmp_path
    )
    committed = json.loads(outcome.fixture_path.read_text(encoding="utf-8"))
    assert committed == ENV_RESULT

    record = outcome.record
    assert record.source == "provider"
    assert record.endpoint == "/v1/env_params"
    assert record.status == "ok"
    assert record.data_date == "2026-08-28"
    assert record.activity_id == "activity-acq-1"
    assert record.request_configuration == {
        "latitude": 29.4259,
        "longitude": -98.4861,
        # The scenario asks the provider for "today"; read the same ambient clock
        # the request builder used, so this holds in any timezone (see TODO below).
        "start_date": date.today().isoformat(),
        "temperature_anchor_celsius": 35.0,
        "hour": 13,
    }


def test_acquisition_records_actual_usage_in_ledger(tmp_path: Path) -> None:
    from app.services.ledger_store import JsonlLedgerStore

    store = JsonlLedgerStore(tmp_path / "ledger.jsonl")
    ledger = store.load(budget=100)
    acquire_heatmap_fixture(
        HEATMAP_SCENARIOS["tcm-historical"], _client(RAW_TCM_RESULT, ledger=ledger), out_dir=tmp_path
    )
    reloaded = JsonlLedgerStore(tmp_path / "ledger.jsonl").load()
    assert reloaded.call_count == 1
    assert reloaded.reported_credits == 2
    assert reloaded.records[0].activity_id == "activity-acq-1"
    assert reloaded.records[0].endpoint == "/v1/heatmap"


def test_scenario_registry_names_are_unique_and_canonical_scenario_is_san_antonio() -> None:
    all_names = [*HEATMAP_SCENARIOS, *ENV_PARAMS_SCENARIOS]
    assert len(all_names) == len(set(all_names))
    canonical = HEATMAP_SCENARIOS["tcm-historical"].build_request()
    assert (canonical.latitude, canonical.longitude) == (29.4241, -98.4936)
    assert canonical.forecast is False
    assert canonical.start_date == date(2026, 8, 23)


def test_acquire_script_requires_live_configuration() -> None:
    import os
    import subprocess
    import sys

    env = {key: value for key, value in os.environ.items() if not key.startswith("FORTYGUARD")}
    env["ALLOW_LIVE"] = "false"
    completed = subprocess.run(
        [sys.executable, "scripts/acquire_fixture.py", "--scenario", "tcm-historical"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 2
    assert "ALLOW_LIVE" in completed.stderr
