"""Exact, maintainer-triggered FortyGuard acquisition plan for issue 23."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import hashlib
import json
from pathlib import Path
import os
from typing import Callable, Mapping, Protocol

from app.domain.environment import TimeWindow, select_anchor_celsius
from app.domain.hotels import BoundingBox
from app.domain.ledger import BudgetExceededError, CreditLedger, UsageRecord
from app.domain.provenance import AcquisitionRecord, Transformation, UpstreamAcquisitionReference
from app.domain.security import sanitize_payload
from app.integrations.fortyguard.client import (
    ActivityRecoveryMetadata,
)
from app.integrations.fortyguard.contracts import (
    PROVIDER_CONFIG_VERSION,
    AnalyticType,
    EnvParamsRequest,
    EnvParamsResult,
    HeatmapRequest,
    HeatmapResult,
    normalize_env_params_response,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.live import env_params_transformations, translate_heatmap_response
from app.services.acquisition import (
    AcquisitionClient,
    AcquisitionOutcome,
    EnvParamsScenario,
    HeatmapScenario,
    acquire_env_params_fixture,
    acquire_heatmap_fixture,
)
from app.services.sidecars import load_acquisition_record, replace_pair, sidecar_path
from app.services.execution import env_params_request_payload, heatmap_request_payload
from app.settings import FortyGuardPollingSettings

ISSUE23_DATE = date(2024, 7, 15)
CANONICAL_WINDOW = TimeWindow(8, 20)
ALTERNATE_WINDOW = TimeWindow(10, 17)
CANONICAL_TIMEZONE = "America/Chicago"
HOTEL_DISTRICT_AOI = BoundingBox(29.421, -98.490, 29.429, -98.482)
HOTEL_DISTRICT_ANCHOR = (29.425, -98.486)
FRAMING_THRESHOLD_CELSIUS = 35.0
DEFAULT_OUT_DIR = Path("fixtures/providers/fortyguard")
WEAK_SCENARIO_NAME = "cathedral-governors-palace-destination-tcm"


class RecoveryClient(Protocol):
    def poll_existing_activity(
        self,
        activity_id: str,
        *,
        sleep: Callable[[float], None] = ...,
        max_polls: int = ...,
        interval_seconds: float = ...,
        status_404_grace_checks: int = ...,
    ) -> tuple[Mapping[str, object], ActivityRecoveryMetadata]: ...


@dataclass(frozen=True)
class PlannedActivity:
    order: int
    name: str
    filename: str
    endpoint: str
    request: HeatmapRequest | None
    prerequisite_name: str | None = None
    declared_windows: tuple[TimeWindow, ...] = ()
    temporal_basis: str = "provider_range"
    caveat_code: str | None = None

    def public_payload(self, *, action: str) -> dict[str, object]:
        if self.request is not None:
            request = heatmap_request_payload(self.request)
        else:
            prerequisite = next(
                candidate
                for candidate in issue23_activities()
                if candidate.name == self.prerequisite_name
            )
            tcm = _required_heatmap_request(prerequisite)
            window = tcm.window
            if window is None:
                raise ValueError("env-params prerequisite must declare a traveler window")
            request = {
                "latitude": tcm.latitude,
                "longitude": tcm.longitude,
                "start_date": tcm.start_date.isoformat(),
                "temperature_anchor_celsius": "derived_at_execution",
                "forecast": False,
                "start_hour": window.start_hour,
                "end_hour": window.end_hour,
            }
        return {
            "order": self.order,
            "name": self.name,
            "filename": self.filename,
            "endpoint": self.endpoint,
            "action": action,
            "request": request,
            "prerequisite": self.prerequisite_name,
            "declared_windows": [
                {"start_hour": window.start_hour, "end_hour": window.end_hour}
                for window in self.declared_windows
            ],
            "timezone": CANONICAL_TIMEZONE,
            "temporal_basis": self.temporal_basis,
            "provider_window_validated": False if self.temporal_basis == "date_level_tcm" else True,
            "caveat_code": self.caveat_code,
        }


def issue23_activities() -> tuple[PlannedActivity, ...]:
    destinations = (
        ("menger-alamo", "The Alamo", 29.425833, -98.485833, CANONICAL_WINDOW),
        (
            "main-plaza-market-square",
            "Historic Market Square",
            29.4254009,
            -98.4994785,
            ALTERNATE_WINDOW,
        ),
        (
            "cathedral-governors-palace",
            "Spanish Governor's Palace",
            29.4248225,
            -98.4959872,
            ALTERNATE_WINDOW,
        ),
    )
    activities: list[PlannedActivity] = []
    for order, (slug, _name, latitude, longitude, window) in enumerate(destinations, 1):
        activities.append(
            PlannedActivity(
                order,
                f"{slug}-destination-tcm",
                f"{slug}-destination-tcm-2024-07-15.json",
                "/v1/heatmap",
                HeatmapRequest(
                    AnalyticType.TCM,
                    latitude,
                    longitude,
                    ISSUE23_DATE,
                    forecast=False,
                    start_hour=window.start_hour,
                    end_hour=window.end_hour,
                ),
                declared_windows=(window,),
            )
        )
    for order, (slug, _name, latitude, longitude, window) in enumerate(destinations, 4):
        activities.append(
            PlannedActivity(
                order,
                f"{slug}-destination-env-params",
                f"{slug}-destination-env-params-2024-07-15.json",
                "/v1/env_params",
                None,
                prerequisite_name=f"{slug}-destination-tcm",
                declared_windows=(window,),
            )
        )
    hotel_requests = (
        (AnalyticType.TCM, None, None, "canonical-district-anchor-date-tcm"),
        (AnalyticType.EXCEEDANCE, 35.0, "above", "canonical-district-anchor-exceedance-above-35c"),
        (
            AnalyticType.PERSISTENCE,
            35.0,
            "above",
            "canonical-district-anchor-persistence-above-35c",
        ),
    )
    for order, (analytic, threshold, direction, name) in enumerate(hotel_requests, 7):
        activities.append(
            PlannedActivity(
                order,
                name,
                f"{name}-2024-07-15.json",
                "/v1/heatmap",
                HeatmapRequest(
                    analytic,
                    HOTEL_DISTRICT_ANCHOR[0],
                    HOTEL_DISTRICT_ANCHOR[1],
                    ISSUE23_DATE,
                    forecast=False,
                    threshold_celsius=threshold,
                    direction=direction,
                    granularity=80,
                ),
                declared_windows=(TimeWindow(0, 5), TimeWindow(10, 17)),
                temporal_basis="date_level_tcm",
                caveat_code="date_level_not_interval_maximum",
            )
        )
    return tuple(activities)


def planned_requests(out_dir: Path = DEFAULT_OUT_DIR) -> list[dict[str, object]]:
    """Return the secret-free ordered plan without constructing a live client."""
    actions = _activity_actions(out_dir, validate_replays=True)
    return [activity.public_payload(action=action) for activity, action in actions]


def canonical_resume_activities() -> tuple[PlannedActivity, ...]:
    """Return the approved canonical replay plus four remaining submissions."""
    activities = issue23_activities()
    selected = (activities[0], activities[3], *activities[6:])
    return tuple(replace(activity, order=order) for order, activity in enumerate(selected, 1))


def planned_canonical_resume_requests(
    out_dir: Path = DEFAULT_OUT_DIR,
) -> list[dict[str, object]]:
    """Reject the superseded plan because its env action would duplicate a completed call."""
    del out_dir
    raise ValueError(
        "canonical resume is superseded by canonical env recovery and hotel-only resume"
    )


def planned_issue23_env_recovery(
    activity_id: str, out_dir: Path = DEFAULT_OUT_DIR
) -> dict[str, object]:
    """Preflight and describe status-only recovery without loading live settings."""
    if not activity_id:
        raise ValueError("activity id is required")
    prerequisite, env_activity = canonical_resume_activities()[:2]
    _canonical_recovery_prerequisite(out_dir, prerequisite)
    _preflight_targets(out_dir, (env_activity,))
    payload = env_activity.public_payload(action="recover_existing_activity")
    payload["activity_id"] = activity_id
    return payload


def hotel_resume_activities() -> tuple[PlannedActivity, ...]:
    """Return exactly the three independent canonical hotel activities."""
    return tuple(
        replace(activity, order=order) for order, activity in enumerate(issue23_activities()[6:], 1)
    )


def planned_issue23_hotels_resume(
    out_dir: Path = DEFAULT_OUT_DIR,
) -> list[dict[str, object]]:
    """Return the secret-free hotel-only plan after preflighting all six paths."""
    activities = hotel_resume_activities()
    _preflight_targets(out_dir, activities)
    return [activity.public_payload(action="submit") for activity in activities]


def recover_issue23_canonical_env(
    client: RecoveryClient,
    ledger: CreditLedger,
    activity_id: str,
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    polling: FortyGuardPollingSettings | None = None,
) -> AcquisitionOutcome:
    """Recover the canonical env result by status lookup only, preserving its mismatch."""
    bounds = polling or FortyGuardPollingSettings()
    _preflight_execution_settings(out_dir, bounds)
    prerequisite, env_activity = canonical_resume_activities()[:2]
    tcm = _canonical_recovery_prerequisite(out_dir, prerequisite)
    _preflight_targets(out_dir, (env_activity,))
    usage = _required_recovery_usage(ledger, activity_id)

    tcm_request, tcm_result, tcm_record, tcm_path = tcm
    window = tcm_request.window
    if window is None:
        raise ValueError("canonical TCM prerequisite must declare a traveler window")
    anchor = select_anchor_celsius(tcm_result.tiles, window)
    request = EnvParamsRequest(
        tcm_request.latitude,
        tcm_request.longitude,
        ISSUE23_DATE,
        anchor,
        start_hour=window.start_hour,
        end_hour=window.end_hour,
    )
    result, recovery = client.poll_existing_activity(
        activity_id,
        max_polls=bounds.max_polls,
        interval_seconds=bounds.interval_seconds,
        status_404_grace_checks=bounds.status_404_grace_checks,
    )
    normalized = normalize_env_params_response(result, request=request)
    _validate_recovered_env_window(normalized, window)
    config = {
        **env_params_request_payload(request),
        "anchor_derivation": "max_normalized_tcm_in_requested_range",
        "anchor_celsius": anchor,
        "anchor_source_activity_id": tcm_record.activity_id,
        "anchor_source_fixture": tcm_path.name,
        "observed_timezone": normalized.timezone,
        "expected_timezone": CANONICAL_TIMEZONE,
        "temporal_evidence": "inconsistent",
        "caveat_code": "provider_timezone_mismatch",
        "provider_date_and_hours_validated": True,
        "recovered_at": recovery.recovered_at.isoformat(),
    }
    record = AcquisitionRecord(
        source="provider",
        provider="fortyguard",
        endpoint="/v1/env_params",
        request_configuration=config,
        retrieved_at=usage.completed_at,
        data_date=ISSUE23_DATE.isoformat(),
        status="ok",
        schema_version="v1",
        provider_config_version=PROVIDER_CONFIG_VERSION,
        activity_id=activity_id,
        derived_from=(_upstream_reference(tcm_path, "temperature_anchor_tcm"),),
        transformations=env_params_transformations()
        + (Transformation("max_normalized_tcm_in_requested_range", 1),),
        response_metadata={},
    )
    fixture_path = out_dir / env_activity.filename
    raw = {key: value for key, value in result.items() if key not in {"credits_used", "request_id"}}
    fixture_path.write_text(json.dumps(sanitize_payload(raw), indent=2) + "\n", encoding="utf-8")
    _replace_sidecar(fixture_path, record)
    return AcquisitionOutcome(fixture_path, record)


def execute_issue23_hotels_resume(
    client: AcquisitionClient,
    ledger: CreditLedger,
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    polling: FortyGuardPollingSettings | None = None,
) -> tuple[AcquisitionOutcome, ...]:
    """Submit exactly the three independent hotel activities after full preflight."""
    bounds = polling or FortyGuardPollingSettings()
    _preflight_execution_settings(out_dir, bounds)
    activities = hotel_resume_activities()
    _preflight_targets(out_dir, activities)
    _preflight_budget(ledger, 3)
    return tuple(
        _acquire_hotel_activity(activity, client, out_dir, polling) for activity in activities
    )


def execute_issue23_plan(
    client: AcquisitionClient,
    ledger: CreditLedger,
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    polling: FortyGuardPollingSettings | None = None,
) -> tuple[AcquisitionOutcome, ...]:
    """Preflight and execute the exact staged plan; never replace provider records."""
    _preflight_execution_settings(out_dir, polling or FortyGuardPollingSettings())
    actions = _activity_actions(out_dir, validate_replays=True)
    submissions = sum(action == "submit" for _, action in actions)
    _preflight_budget(ledger, submissions)
    outcomes: list[AcquisitionOutcome] = []
    tcm_results: dict[str, tuple[HeatmapRequest, HeatmapResult, AcquisitionRecord, Path]] = {}

    for activity, action in actions[:3]:
        request = _required_heatmap_request(activity)
        if action == "replay_prerequisite":
            path = out_dir / activity.filename
            record = _required_record(path)
            result = _normalize_stored_tcm(path, request, record)
        else:
            outcome = acquire_heatmap_fixture(
                HeatmapScenario(activity.name, activity.filename, _heatmap_builder(request)),
                client,
                out_dir=out_dir,
                polling=polling,
            )
            outcomes.append(outcome)
            path, record = outcome.fixture_path, outcome.record
            result = _normalize_stored_tcm(path, request, record)
        tcm_results[activity.name] = (request, result, record, path)

    weak_request, weak_result, _, _ = tcm_results[WEAK_SCENARIO_NAME]
    weak_anchor = select_anchor_celsius(weak_result.tiles, weak_request.window or ALTERNATE_WINDOW)
    if weak_anchor < FRAMING_THRESHOLD_CELSIUS:
        raise ValueError(
            f"weak scenario gate not elevated: {weak_anchor} C; valid TCM was preserved and dependent acquisition stopped"
        )

    for activity, action in actions[3:6]:
        if action != "submit" or activity.prerequisite_name is None:
            raise ValueError("env-params activities cannot be replayed or lack a TCM prerequisite")
        outcomes.append(
            _acquire_env_activity(
                activity,
                tcm_results[activity.prerequisite_name],
                client,
                out_dir,
                polling,
            )
        )

    for activity, action in actions[6:]:
        if action != "submit":
            raise ValueError("hotel provider activities cannot be replayed")
        outcomes.append(_acquire_hotel_activity(activity, client, out_dir, polling))
    return tuple(outcomes)


def execute_issue23_canonical_resume(
    client: AcquisitionClient,
    ledger: CreditLedger,
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    polling: FortyGuardPollingSettings | None = None,
) -> tuple[AcquisitionOutcome, ...]:
    """Reject the superseded workflow before it can duplicate the completed env call."""
    del client, ledger, out_dir, polling
    raise ValueError(
        "canonical resume is superseded by canonical env recovery and hotel-only resume"
    )


def _activity_actions(
    out_dir: Path, *, validate_replays: bool
) -> list[tuple[PlannedActivity, str]]:
    activities = issue23_activities()
    actions: list[tuple[PlannedActivity, str]] = []
    for activity in activities:
        fixture = out_dir / activity.filename
        sidecar = sidecar_path(fixture)
        if activity.order <= 3 and fixture.is_file() and sidecar.is_file():
            if validate_replays:
                request = _required_heatmap_request(activity)
                _normalize_stored_tcm(fixture, request, _required_record(fixture))
            actions.append((activity, "replay_prerequisite"))
            continue
        if fixture.exists() or sidecar.exists():
            raise FileExistsError(f"partial or non-replayable target already exists: {fixture}")
        actions.append((activity, "submit"))
    return actions


def _canonical_resume_actions(out_dir: Path) -> list[tuple[PlannedActivity, str]]:
    activities = canonical_resume_activities()
    prerequisite = activities[0]
    fixture = out_dir / prerequisite.filename
    if not fixture.is_file() or not sidecar_path(fixture).is_file():
        raise ValueError(f"canonical TCM prerequisite pair is required: {fixture}")
    _normalize_stored_tcm(
        fixture,
        _required_heatmap_request(prerequisite),
        _required_record(fixture),
    )
    for activity in activities[1:]:
        target = out_dir / activity.filename
        if target.exists() or sidecar_path(target).exists():
            raise FileExistsError(f"refusing to overwrite canonical resume target: {target}")
    return [(prerequisite, "replay_prerequisite"), *[(item, "submit") for item in activities[1:]]]


def _canonical_recovery_prerequisite(
    out_dir: Path, prerequisite: PlannedActivity
) -> tuple[HeatmapRequest, HeatmapResult, AcquisitionRecord, Path]:
    path = out_dir / prerequisite.filename
    if not path.is_file() or not sidecar_path(path).is_file():
        raise ValueError(f"canonical TCM prerequisite pair is required: {path}")
    request = _required_heatmap_request(prerequisite)
    record = _required_record(path)
    return request, _normalize_stored_tcm(path, request, record), record, path


def _preflight_targets(out_dir: Path, activities: tuple[PlannedActivity, ...]) -> None:
    for activity in activities:
        target = out_dir / activity.filename
        if target.exists() or sidecar_path(target).exists():
            raise FileExistsError(f"refusing to overwrite issue 23 target: {target}")


def _required_recovery_usage(ledger: CreditLedger, activity_id: str) -> UsageRecord:
    matches = [record for record in ledger.records if record.activity_id == activity_id]
    if not matches:
        raise ValueError(f"activity {activity_id} is not present in the ledger")
    record = matches[0]
    if record.endpoint != "/v1/env_params":
        raise ValueError(
            f"activity {activity_id} is ledgered for {record.endpoint}, not /v1/env_params"
        )
    if record.status.lower() != "completed":
        raise ValueError(f"activity {activity_id} is not ledgered as completed")
    return record


def _acquire_env_activity(
    activity: PlannedActivity,
    tcm: tuple[HeatmapRequest, HeatmapResult, AcquisitionRecord, Path],
    client: AcquisitionClient,
    out_dir: Path,
    polling: FortyGuardPollingSettings | None,
) -> AcquisitionOutcome:
    tcm_request, tcm_result, tcm_record, tcm_path = tcm
    window = tcm_request.window
    if window is None:
        raise ValueError("destination TCM prerequisite must have a traveler window")
    anchor = select_anchor_celsius(tcm_result.tiles, window)
    request = EnvParamsRequest(
        tcm_request.latitude,
        tcm_request.longitude,
        ISSUE23_DATE,
        anchor,
        start_hour=window.start_hour,
        end_hour=window.end_hour,
    )
    outcome = acquire_env_params_fixture(
        EnvParamsScenario(activity.name, activity.filename, _env_builder(request)),
        client,
        out_dir=out_dir,
        polling=polling,
        validate=_env_validator(window),
    )
    enriched = replace(
        outcome.record,
        request_configuration={
            **outcome.record.request_configuration,
            "anchor_derivation": "max_normalized_tcm_in_requested_range",
            "anchor_celsius": anchor,
            "anchor_source_activity_id": tcm_record.activity_id,
            "anchor_source_fixture": tcm_path.name,
        },
        derived_from=(_upstream_reference(tcm_path, "temperature_anchor_tcm"),),
        transformations=outcome.record.transformations
        + (Transformation("max_normalized_tcm_in_requested_range", 1),),
    )
    _replace_sidecar(outcome.fixture_path, enriched)
    return AcquisitionOutcome(outcome.fixture_path, enriched)


def _acquire_hotel_activity(
    activity: PlannedActivity,
    client: AcquisitionClient,
    out_dir: Path,
    polling: FortyGuardPollingSettings | None,
) -> AcquisitionOutcome:
    request = _required_heatmap_request(activity)
    outcome = acquire_heatmap_fixture(
        HeatmapScenario(activity.name, activity.filename, _heatmap_builder(request)),
        client,
        out_dir=out_dir,
        polling=polling,
    )
    config = {
        **outcome.record.request_configuration,
        "request_scope": "canonical_district_anchor",
        "analysis_aoi": HOTEL_DISTRICT_AOI.to_payload(),
        "declared_windows": [
            {
                "label": "night",
                "start": "00:00",
                "end": "05:00",
                "timezone": CANONICAL_TIMEZONE,
                "interval": "[start,end)",
            },
            {
                "label": "day",
                "start": "10:00",
                "end": "17:00",
                "timezone": CANONICAL_TIMEZONE,
                "interval": "[start,end)",
            },
        ],
        "timezone": CANONICAL_TIMEZONE,
        "temporal_basis": "date_level_tcm",
        "provider_window_validated": False,
        "caveat_code": "date_level_not_interval_maximum",
    }
    if request.analytic_type is not AnalyticType.TCM:
        config["metric_semantics"] = "date_level_hours_above_threshold"
    else:
        config["reused_for_components"] = ["night", "day"]
    enriched = replace(outcome.record, request_configuration=config)
    _replace_sidecar(outcome.fixture_path, enriched)
    return AcquisitionOutcome(outcome.fixture_path, enriched)


def _preflight_budget(ledger: CreditLedger, submissions: int) -> None:
    if ledger.budget is not None and ledger.remaining < submissions:
        raise BudgetExceededError(
            f"issue 23 plan needs {submissions} calls but ledger has {ledger.remaining} remaining"
        )


def _preflight_execution_settings(out_dir: Path, polling: FortyGuardPollingSettings) -> None:
    if not out_dir.parent.is_dir():
        raise ValueError(f"output parent does not exist: {out_dir.parent}")
    out_dir.mkdir(exist_ok=True)
    if not out_dir.is_dir() or not os.access(out_dir, os.W_OK | os.X_OK):
        raise ValueError(f"output directory is not writable: {out_dir}")
    if (
        polling.max_polls < 1
        or polling.interval_seconds <= 0
        or polling.status_404_grace_checks < 1
    ):
        raise ValueError("polling settings must be positive")


def _required_heatmap_request(activity: PlannedActivity) -> HeatmapRequest:
    if activity.request is None:
        raise ValueError(f"{activity.name} has no static heatmap request")
    return activity.request


def _heatmap_builder(request: HeatmapRequest) -> Callable[[], HeatmapRequest]:
    def build() -> HeatmapRequest:
        return request

    return build


def _env_builder(request: EnvParamsRequest) -> Callable[[], EnvParamsRequest]:
    def build() -> EnvParamsRequest:
        return request

    return build


def _env_validator(window: TimeWindow) -> Callable[[EnvParamsResult], None]:
    def validate(result: EnvParamsResult) -> None:
        _validate_env_window(result, window)

    return validate


def _required_record(path: Path) -> AcquisitionRecord:
    record = load_acquisition_record(path)
    if record is None:
        raise ValueError(f"missing acquisition record for {path}")
    return record


def _normalize_stored_tcm(
    path: Path, request: HeatmapRequest, record: AcquisitionRecord
) -> HeatmapResult:
    if (
        record.source != "provider"
        or record.provider != "fortyguard"
        or record.endpoint != "/v1/heatmap"
    ):
        raise ValueError(f"TCM prerequisite has untruthful provider identity: {path}")
    expected = heatmap_request_payload(request)
    if record.request_configuration != expected or record.data_date != ISSUE23_DATE.isoformat():
        raise ValueError(f"TCM prerequisite does not match the exact issue 23 request: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"TCM prerequisite must contain an object: {path}")
    translated = translate_heatmap_response(payload, request=request)
    if record.retrieved_at is None:
        raise ValueError(f"TCM prerequisite lacks a provider retrieval time: {path}")
    return normalize_heatmap_response(
        translated,
        request=request,
        retrieved_at=record.retrieved_at,
        activity_id=record.activity_id,
        transformations=record.transformations,
    )


def _upstream_reference(path: Path, role: str) -> UpstreamAcquisitionReference:
    canonical = f"fixtures/providers/fortyguard/{path.name}"
    sidecar = sidecar_path(path)
    return UpstreamAcquisitionReference(
        canonical,
        role,
        hashlib.sha256(path.read_bytes()).hexdigest(),
        hashlib.sha256(sidecar.read_bytes()).hexdigest(),
    )


def _validate_env_window(result: EnvParamsResult, window: TimeWindow) -> None:
    if result.timezone not in {CANONICAL_TIMEZONE, "GMT-5", "UTC-05:00"}:
        raise ValueError(
            f"env-params timezone does not match canonical July offset: {result.timezone}"
        )
    observed = [(entry.valid_time.date(), entry.valid_time.hour) for entry in result.entries]
    expected = [(ISSUE23_DATE, hour) for hour in window.hours]
    if observed != expected:
        raise ValueError(
            f"env-params temporal mismatch: expected {expected!r}, received {observed!r}"
        )


def _validate_recovered_env_window(result: EnvParamsResult, window: TimeWindow) -> None:
    """Validate provider-established date/hours while retaining its timezone mismatch."""
    if result.timezone != "GMT-7":
        raise ValueError(
            f"recovered env-params timezone is not the observed GMT-7: {result.timezone}"
        )
    observed = [(entry.valid_time.date(), entry.valid_time.hour) for entry in result.entries]
    expected = [(ISSUE23_DATE, hour) for hour in window.hours]
    if observed != expected:
        raise ValueError(
            f"recovered env-params date/hour mismatch: expected {expected!r}, received {observed!r}"
        )


def _replace_sidecar(path: Path, record: AcquisitionRecord) -> None:
    replace_pair(path, path.read_bytes(), record)
