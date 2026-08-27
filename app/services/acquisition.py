"""Fixture acquisition: real provider runs committed as raw fixtures + sidecars.

The acquisition path (ADR 0004) submits one documented request through the
live client, proves the result normalizes into the shared domain shape, then
writes the sanitized raw provider payload and an honest acquisition-record
sidecar. Actual credit usage lands in the caller's ledger via the client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Callable, Mapping

from app.domain.provenance import AcquisitionRecord
from app.domain.security import sanitize_payload
from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.contracts import (
    PROVIDER_CONFIG_VERSION,
    AnalyticType,
    EnvParamsRequest,
    HeatmapRequest,
    normalize_env_params_response,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.live import (
    build_documented_env_params_payload,
    build_documented_heatmap_payload,
    env_params_transformations,
    request_transformations,
    translate_heatmap_response,
)
from app.services.execution import env_params_request_payload, heatmap_request_payload
from app.services.sidecars import write_sidecar
from app.settings import FortyGuardPollingSettings

SAN_ANTONIO_LATITUDE = 29.4241
SAN_ANTONIO_LONGITUDE = -98.4936
ENV_OBSERVATION_LATITUDE = 29.4259
ENV_OBSERVATION_LONGITUDE = -98.4861
CANONICAL_DATA_DATE = date(2026, 8, 23)

_CREDIT_METADATA_KEYS = ("credits_used", "request_id")


@dataclass(frozen=True)
class HeatmapScenario:
    name: str
    filename: str
    build_request: Callable[[], HeatmapRequest]


@dataclass(frozen=True)
class EnvParamsScenario:
    name: str
    filename: str
    build_request: Callable[[], EnvParamsRequest]


@dataclass(frozen=True)
class AcquisitionOutcome:
    fixture_path: Path
    record: AcquisitionRecord


HEATMAP_SCENARIOS: dict[str, HeatmapScenario] = {
    "tcm-historical": HeatmapScenario(
        "tcm-historical",
        "heatmap-tcm-historical.json",
        lambda: HeatmapRequest(
            AnalyticType.TCM,
            SAN_ANTONIO_LATITUDE,
            SAN_ANTONIO_LONGITUDE,
            CANONICAL_DATA_DATE,
            forecast=False,
        ),
    ),
    "tcm-forecast": HeatmapScenario(
        "tcm-forecast",
        "heatmap-tcm-forecast.json",
        lambda: HeatmapRequest(
            AnalyticType.TCM,
            SAN_ANTONIO_LATITUDE,
            SAN_ANTONIO_LONGITUDE,
            date.today(),
            forecast=True,
        ),
    ),
    "exceedance-historical": HeatmapScenario(
        "exceedance-historical",
        "heatmap-exceedance-historical.json",
        lambda: HeatmapRequest(
            AnalyticType.EXCEEDANCE,
            SAN_ANTONIO_LATITUDE,
            SAN_ANTONIO_LONGITUDE,
            CANONICAL_DATA_DATE,
            forecast=False,
            threshold_celsius=35.0,
            direction="above",
        ),
    ),
}

ENV_PARAMS_SCENARIOS: dict[str, EnvParamsScenario] = {
    "env-params-anchor35": EnvParamsScenario(
        "env-params-anchor35",
        "env-params-anchor35.json",
        lambda: EnvParamsRequest(
            ENV_OBSERVATION_LATITUDE,
            ENV_OBSERVATION_LONGITUDE,
            date.today(),
            35.0,
            hour=13,
        ),
    ),
}


def acquire_heatmap_fixture(
    scenario: HeatmapScenario,
    client: FortyGuardClient,
    *,
    out_dir: Path,
    provider_config_version: str = PROVIDER_CONFIG_VERSION,
    schema_version: str = "v1",
    polling: FortyGuardPollingSettings | None = None,
) -> AcquisitionOutcome:
    """Run one documented heatmap request and commit the raw fixture + sidecar."""
    request = scenario.build_request()
    payload = build_documented_heatmap_payload(request)
    bounds = polling or FortyGuardPollingSettings()
    result, metadata = client.submit_and_poll(
        "/v1/heatmap",
        payload,
        max_polls=bounds.max_polls,
        interval_seconds=bounds.interval_seconds,
        status_404_grace_checks=bounds.status_404_grace_checks,
    )
    translated = translate_heatmap_response(result, request=request)
    normalize_heatmap_response(
        translated,
        request=request,
        retrieved_at=metadata.submitted_at,
        activity_id=metadata.activity_id,
    )
    record = AcquisitionRecord(
        source="provider",
        endpoint="/v1/heatmap",
        request_configuration=heatmap_request_payload(request),
        retrieved_at=metadata.submitted_at,
        data_date=str(translated["data_date"]),
        status="ok",
        schema_version=schema_version,
        provider_config_version=provider_config_version,
        activity_id=metadata.activity_id,
        transformations=request_transformations(request),
    )
    fixture_path = _write_fixture(out_dir, scenario.filename, result)
    write_sidecar(fixture_path, record)
    return AcquisitionOutcome(fixture_path, record)


def acquire_env_params_fixture(
    scenario: EnvParamsScenario,
    client: FortyGuardClient,
    *,
    out_dir: Path,
    provider_config_version: str = PROVIDER_CONFIG_VERSION,
    schema_version: str = "v1",
    polling: FortyGuardPollingSettings | None = None,
) -> AcquisitionOutcome:
    """Run one documented env-params request and commit the raw fixture + sidecar."""
    request = scenario.build_request()
    payload = build_documented_env_params_payload(request)
    bounds = polling or FortyGuardPollingSettings()
    result, metadata = client.submit_and_poll(
        "/v1/env_params",
        payload,
        max_polls=bounds.max_polls,
        interval_seconds=bounds.interval_seconds,
        status_404_grace_checks=bounds.status_404_grace_checks,
    )
    normalized = normalize_env_params_response(result, request=request)
    data_date = normalized.entries[0].valid_time.date().isoformat()
    record = AcquisitionRecord(
        source="provider",
        endpoint="/v1/env_params",
        request_configuration=env_params_request_payload(request),
        retrieved_at=metadata.submitted_at,
        data_date=data_date,
        status="ok",
        schema_version=schema_version,
        provider_config_version=provider_config_version,
        activity_id=metadata.activity_id,
        transformations=env_params_transformations(),
    )
    fixture_path = _write_fixture(out_dir, scenario.filename, result)
    write_sidecar(fixture_path, record)
    return AcquisitionOutcome(fixture_path, record)


def _write_fixture(out_dir: Path, filename: str, result: Mapping[str, object]) -> Path:
    payload = {
        key: value
        for key, value in dict(result).items()
        if key not in _CREDIT_METADATA_KEYS
    }
    sanitized = sanitize_payload(payload)
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = out_dir / filename
    fixture_path.write_text(json.dumps(sanitized, indent=2) + "\n", encoding="utf-8")
    return fixture_path
