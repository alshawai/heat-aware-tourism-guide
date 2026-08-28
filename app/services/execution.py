"""Shared fixture/live execution path for normalized heatmap results.

Implements the degradation chain of ADR 0004: live → matching cache entry
(exact key) → matching fixture (sidecar identity; date-relaxed for forecast
mode) → explicit unavailable error. Fixture identity and provenance come from
acquisition sidecars when present; embedded request blocks are the legacy
fallback for sidecar-less fixtures.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence
from dataclasses import dataclass

from app.domain.provenance import AcquisitionRecord, CacheKey, Transformation
from app.integrations.fortyguard.contracts import (
    PROVIDER_CONFIG_VERSION,
    EnvParamsRequest,
    EnvParamsResult,
    HeatmapRequest,
    HeatmapResult,
    normalize_env_params_response,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.errors import ProviderError
from app.integrations.fortyguard.live import (
    LiveEnvParamsPayload,
    LiveHeatmapPayload,
    request_transformations,
    translate_heatmap_response,
)
from app.services.cache import CacheService
from app.services.sidecars import load_acquisition_record


class UnavailableError(RuntimeError):
    """Degradation chain exhausted: nothing replayable exists (ADR 0004)."""

    def __init__(self, detail: str, *, error_kind: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.error_kind = error_kind


def _provider_error_kind(error: BaseException) -> str | None:
    return error.kind.value if isinstance(error, ProviderError) else None


# A corrupt fixture payload or sidecar is a server-side data problem: the
# candidate is skipped and the scan continues — never a client error (ADR 0004 §6).
_FIXTURE_DATA_ERRORS = (ValueError, KeyError, ProviderError)


def _dedupe_fixture_paths(paths: Sequence[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


class HeatmapExecution:
    def __init__(
        self,
        *,
        fixture_path: Path,
        live_loader: Callable[[HeatmapRequest], Mapping[str, object] | LiveHeatmapPayload]
        | None = None,
        cache: CacheService | None = None,
        endpoint: str = "/v1/heatmap",
        schema_version: str = "v1",
        provider_config_version: str = PROVIDER_CONFIG_VERSION,
        additional_fixtures: Sequence[Path] = (),
    ) -> None:
        self.fixture_path = fixture_path
        self.live_loader = live_loader
        self.cache = cache
        self.endpoint = endpoint
        self.schema_version = schema_version
        self.provider_config_version = provider_config_version
        self.additional_fixtures = list(additional_fixtures)

    def run(self, request: HeatmapRequest, *, live: bool = False) -> HeatmapResult:
        if live:
            return self._run_live(request)
        result = self._match_fixture(request, stale=False)
        if result is None:
            raise UnavailableError("no matching fixture for the requested heatmap scenario")
        return result

    def _run_live(self, request: HeatmapRequest) -> HeatmapResult:
        if self.live_loader is None:
            raise UnavailableError("live execution is not configured")
        request_payload = heatmap_request_payload(request)
        try:
            loaded = self.live_loader(request)
            payload = loaded.payload if isinstance(loaded, LiveHeatmapPayload) else loaded
            activity_id = loaded.activity_id if isinstance(loaded, LiveHeatmapPayload) else None
            transformations = (
                loaded.transformations if isinstance(loaded, LiveHeatmapPayload) else ()
            )
            activity = loaded.activity if isinstance(loaded, LiveHeatmapPayload) else None
            inferred_unit = loaded.inferred_unit if isinstance(loaded, LiveHeatmapPayload) else None
            result = normalize_heatmap_response(
                payload,
                request=request,
                retrieved_at=datetime.now().astimezone(),
                activity_id=activity_id,
                activity=activity,
                inferred_unit=inferred_unit,
                source="provider",
                data_date=_fixture_data_date(payload),
                transformations=transformations,
            )
        except (ConnectionError, OSError, ProviderError, TimeoutError, ValueError) as error:
            fallback = self._fallback(request, request_payload)
            if fallback is not None:
                return fallback
            raise UnavailableError(
                "live heatmap request failed and no matching cache entry or fixture is available",
                error_kind=_provider_error_kind(error),
            ) from error
        if self.cache is not None:
            self.cache.put(
                self.endpoint,
                self.schema_version,
                request_payload,
                payload,
                retrieved_at=result.provenance.retrieved_at,
                data_date=result.provenance.data_date,
                activity_id=result.provenance.activity_id,
                activity=result.activity,
                inferred_unit=inferred_unit,
                forecast=request.forecast,
                provider_config_version=self.provider_config_version,
            )
        return result

    def _fallback(
        self, request: HeatmapRequest, request_payload: dict[str, object]
    ) -> HeatmapResult | None:
        if self.cache is not None:
            cached = self.cache.get(
                CacheKey.create(
                    self.endpoint,
                    self.schema_version,
                    request_payload,
                    self.provider_config_version,
                )
            )
            if cached is not None:
                return normalize_heatmap_response(
                    cached.payload,
                    request=request,
                    retrieved_at=cached.provenance.retrieved_at,
                    activity_id=cached.provenance.activity_id,
                    activity=cached.activity,
                    inferred_unit=cached.inferred_unit,
                    source="cache",
                    data_date=cached.provenance.data_date,
                )
        return self._match_fixture(request, stale=True)

    def _match_fixture(self, request: HeatmapRequest, *, stale: bool) -> HeatmapResult | None:
        request_payload = heatmap_request_payload(request)
        if request.forecast:
            # Forecast fixtures replay date-relaxed and are always labelled stale:
            # a committed forecast is never presented as a current forecast (ADR 0004).
            attempts: list[tuple[bool, bool]] = [(True, True)]
        else:
            attempts = [(False, stale)]
        for date_relaxed, attempt_stale in attempts:
            for path in _dedupe_fixture_paths([self.fixture_path, *self.additional_fixtures]):
                try:
                    replayed = self._try_replay_fixture(
                        path,
                        request,
                        request_payload=request_payload,
                        date_relaxed=date_relaxed,
                        stale=attempt_stale,
                    )
                except _FIXTURE_DATA_ERRORS:
                    continue
                if replayed is not None:
                    return replayed
        return None

    def _try_replay_fixture(
        self,
        path: Path,
        request: HeatmapRequest,
        *,
        request_payload: Mapping[str, object],
        date_relaxed: bool,
        stale: bool,
    ) -> HeatmapResult | None:
        record = load_acquisition_record(path)
        payload = _read_fixture(path)
        if payload is None:
            return None
        if record is not None:
            if not record.replayable:
                return None
            identity: Mapping[str, object] | None = record.request_configuration
        else:
            embedded = payload.get("request")
            identity = embedded if isinstance(embedded, Mapping) else None
        if identity is None:
            return None
        if not _request_identity_matches(identity, request_payload, date_relaxed=date_relaxed):
            return None
        return self._replay_fixture(payload, request=request, record=record, stale=stale)

    def _replay_fixture(
        self,
        payload: Mapping[str, object],
        *,
        request: HeatmapRequest,
        record: AcquisitionRecord | None,
        stale: bool,
    ) -> HeatmapResult:
        if "map_data" in payload:
            translated = translate_heatmap_response(payload, request=request)
            raw_data_date = translated.get("data_date")
            return normalize_heatmap_response(
                translated,
                request=request,
                retrieved_at=_retrieved_at(record),
                activity_id=record.activity_id if record is not None else None,
                source="fixture",
                data_date=record.data_date
                if record is not None
                else (raw_data_date if isinstance(raw_data_date, str) else None),
                # The sidecar records which transformation rule versions produced
                # the acquired data; a rule change never rewrites history (ADR 0002).
                transformations=(
                    record.transformations
                    if record is not None
                    else request_transformations(request)
                ),
                stale=stale,
            )
        return normalize_heatmap_response(
            payload,
            request=request,
            retrieved_at=_retrieved_at(record),
            activity_id=record.activity_id if record is not None else None,
            source="fixture",
            data_date=record.data_date if record is not None else _fixture_data_date(payload),
            stale=stale,
        )


def _retrieved_at(record: AcquisitionRecord | None) -> datetime:
    if record is not None and record.retrieved_at is not None:
        return record.retrieved_at
    return datetime.now().astimezone()


def _read_fixture(path: Path) -> Mapping[str, object] | None:
    try:
        with path.open(encoding="utf-8") as fixture:
            payload = json.load(fixture)
    except OSError:
        return None
    if not isinstance(payload, Mapping):
        return None
    return payload


def _request_identity_matches(
    identity: Mapping[str, object], request_payload: Mapping[str, object], *, date_relaxed: bool
) -> bool:
    for key, expected in request_payload.items():
        if key == "start_date" and date_relaxed:
            continue
        if identity.get(key) != expected:
            return False
    return True


def heatmap_request_payload(request: HeatmapRequest) -> dict[str, object]:
    """The complete request identity for heatmap cache keys and fixture matching."""
    return {
        "analytic_type": request.analytic_type.value,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "start_date": request.start_date.isoformat(),
        "forecast": request.forecast,
        "threshold_celsius": request.threshold_celsius,
        "direction": request.direction,
        "granularity": request.granularity,
    }


def _fixture_data_date(payload: Mapping[str, object]) -> str:
    data_date = payload.get("data_date")
    if isinstance(data_date, str):
        return data_date
    map_data = payload.get("map_data")
    feature_collection = map_data if isinstance(map_data, Mapping) else payload
    features = feature_collection.get("features")
    if isinstance(features, list) and features and isinstance(features[0], Mapping):
        properties = features[0].get("properties")
        if isinstance(properties, Mapping) and isinstance(properties.get("valid_time"), str):
            valid_time = properties["valid_time"]
            if isinstance(valid_time, str):
                return valid_time[:10]
    raise ValueError("fixture is missing data date freshness metadata")


@dataclass(frozen=True)
class EnvParamsOutcome:
    result: EnvParamsResult
    source: str
    activity_id: str | None = None
    transformations: tuple[Transformation, ...] = ()
    stale: bool = False
    retrieved_at: datetime | None = None
    data_date: str | None = None


class EnvParamsExecution:
    """Fixture/live execution for the environmental-parameters series."""

    def __init__(
        self,
        *,
        fixture_path: Path,
        live_loader: Callable[[EnvParamsRequest], Mapping[str, object] | LiveEnvParamsPayload]
        | None = None,
        cache: CacheService | None = None,
        endpoint: str = "/v1/env_params",
        schema_version: str = "v1",
        provider_config_version: str = PROVIDER_CONFIG_VERSION,
        additional_fixtures: Sequence[Path] = (),
    ) -> None:
        self.fixture_path = fixture_path
        self.live_loader = live_loader
        self.cache = cache
        self.endpoint = endpoint
        self.schema_version = schema_version
        self.provider_config_version = provider_config_version
        self.additional_fixtures = list(additional_fixtures)

    def run(self, request: EnvParamsRequest, *, live: bool = False) -> EnvParamsOutcome:
        if live:
            return self._run_live(request)
        outcome = self._match_fixture(request, stale=False)
        if outcome is None:
            raise UnavailableError(
                "no matching fixture for the requested environmental-parameters scenario"
            )
        return outcome

    def _run_live(self, request: EnvParamsRequest) -> EnvParamsOutcome:
        if self.live_loader is None:
            raise UnavailableError("live execution is not configured")
        request_payload = env_params_request_payload(request)
        try:
            loaded = self.live_loader(request)
            payload = loaded.payload if isinstance(loaded, LiveEnvParamsPayload) else loaded
            activity_id = loaded.activity_id if isinstance(loaded, LiveEnvParamsPayload) else None
            transformations = (
                loaded.transformations if isinstance(loaded, LiveEnvParamsPayload) else ()
            )
            result = normalize_env_params_response(payload, request=request)
        except (ConnectionError, OSError, ProviderError, TimeoutError, ValueError) as error:
            fallback = self._fallback(request, request_payload)
            if fallback is not None:
                return fallback
            raise UnavailableError(
                "live environmental-parameters request failed and no matching cache entry"
                " or fixture is available",
                error_kind=_provider_error_kind(error),
            ) from error
        retrieved_at = datetime.now().astimezone()
        data_date = _env_data_date(payload) or request.start_date.isoformat()
        if self.cache is not None:
            self.cache.put(
                self.endpoint,
                self.schema_version,
                request_payload,
                payload,
                retrieved_at=retrieved_at,
                data_date=data_date,
                activity_id=activity_id,
                forecast=False,
                provider_config_version=self.provider_config_version,
            )
        return EnvParamsOutcome(
            result,
            "provider",
            activity_id,
            transformations,
            retrieved_at=retrieved_at,
            data_date=data_date,
        )

    def _fallback(
        self, request: EnvParamsRequest, request_payload: dict[str, object]
    ) -> EnvParamsOutcome | None:
        if self.cache is not None:
            cached = self.cache.get(
                CacheKey.create(
                    self.endpoint,
                    self.schema_version,
                    request_payload,
                    self.provider_config_version,
                )
            )
            if cached is not None:
                return EnvParamsOutcome(
                    normalize_env_params_response(cached.payload, request=request),
                    "cache",
                    cached.provenance.activity_id,
                    stale=True,
                    retrieved_at=cached.provenance.retrieved_at,
                    data_date=cached.provenance.data_date,
                )
        return self._match_fixture(request, stale=True)

    def _match_fixture(self, request: EnvParamsRequest, *, stale: bool) -> EnvParamsOutcome | None:
        request_payload = env_params_request_payload(request)
        for path in _dedupe_fixture_paths([self.fixture_path, *self.additional_fixtures]):
            try:
                outcome = self._try_replay_fixture(
                    path, request, request_payload=request_payload, stale=stale
                )
            except _FIXTURE_DATA_ERRORS:
                continue
            if outcome is not None:
                return outcome
        return None

    def _try_replay_fixture(
        self,
        path: Path,
        request: EnvParamsRequest,
        *,
        request_payload: Mapping[str, object],
        stale: bool,
    ) -> EnvParamsOutcome | None:
        record = load_acquisition_record(path)
        if record is None or not record.replayable:
            return None
        payload = _read_fixture(path)
        if payload is None:
            return None
        if not _request_identity_matches(
            record.request_configuration, request_payload, date_relaxed=False
        ):
            return None
        return EnvParamsOutcome(
            normalize_env_params_response(payload, request=request),
            "fixture",
            record.activity_id,
            stale=stale,
            retrieved_at=record.retrieved_at,
            data_date=record.data_date,
        )


def env_params_request_payload(request: EnvParamsRequest) -> dict[str, object]:
    """The complete request identity for env-params cache keys and fixture matching."""
    return {
        "latitude": request.latitude,
        "longitude": request.longitude,
        "start_date": request.start_date.isoformat(),
        "temperature_anchor_celsius": request.temperature_anchor_celsius,
        "hour": request.hour,
    }


def _env_data_date(payload: Mapping[str, object]) -> str | None:
    timestamp = payload.get("timestamp")
    if isinstance(timestamp, str):
        return timestamp[:10]
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        timestamps = metadata.get("timestamps")
        if isinstance(timestamps, list) and timestamps and isinstance(timestamps[0], str):
            return timestamps[0][:10]
    return None
