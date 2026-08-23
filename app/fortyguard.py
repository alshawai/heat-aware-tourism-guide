"""Offline-safe contracts for the asynchronous FortyGuard API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
import re
from time import sleep as default_sleep
from typing import Callable, Mapping, Protocol, Sequence

from app.domain import Provenance


class AnalyticType(str, Enum):
    TCM = "tcm"
    EXCEEDANCE = "exceedance"
    PERSISTENCE = "persistence"


@dataclass(frozen=True)
class HeatmapRequest:
    analytic_type: AnalyticType
    latitude: float
    longitude: float
    start_date: date
    forecast: bool = True
    threshold_celsius: float | None = None
    direction: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.analytic_type, AnalyticType):
            raise ValueError("unknown analytic type")
        if not 24 <= self.latitude <= 50 or not -125 <= self.longitude <= -66:
            raise ValueError("coordinates must be within the supported US extent")
        if self.forecast and not date.today() <= self.start_date <= date.today() + timedelta(days=1):
            raise ValueError("forecast start date must be today or tomorrow")
        if self.analytic_type in (AnalyticType.EXCEEDANCE, AnalyticType.PERSISTENCE):
            if self.threshold_celsius is None:
                raise ValueError("threshold is required for this analytic type")
            if self.direction not in ("above", "below"):
                raise ValueError("direction must be above or below")


class ProviderErrorKind(str, Enum):
    AUTHENTICATION = "authentication"
    VALIDATION = "validation_or_plan"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    MALFORMED_RESPONSE = "malformed_response"
    TASK_FAILURE = "task_failure"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ProviderError(Exception):
    kind: ProviderErrorKind
    status_code: int | None = None
    detail: str = "provider request failed"

    def __str__(self) -> str:
        return f"{self.kind.value}: {self.detail}"


def _sanitize_detail(detail: str) -> str:
    detail = re.sub(r"(?i)(api[_ -]?key|authorization|token)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", detail)
    return detail[:160]


def classify_provider_error(status_code: int | None, detail: str = "") -> ProviderError:
    if status_code in (401, 403):
        kind = ProviderErrorKind.AUTHENTICATION
    elif status_code in (400, 404, 422):
        kind = ProviderErrorKind.VALIDATION
    elif status_code == 429:
        kind = ProviderErrorKind.RATE_LIMIT
    elif status_code is not None and status_code >= 500:
        kind = ProviderErrorKind.SERVER
    else:
        kind = ProviderErrorKind.MALFORMED_RESPONSE
    return ProviderError(kind, status_code, _sanitize_detail(detail) or "provider request failed")


class FortyGuardTransport(Protocol):
    def post(self, endpoint: str, payload: Mapping[str, object], api_key: str) -> Mapping[str, object]: ...

    def get(self, endpoint: str, api_key: str) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class ActivityMetadata:
    activity_id: str
    submitted_at: datetime
    endpoint: str
    request_fields: tuple[str, ...]
    status_transitions: tuple[str, ...] = ()
    response_metadata: Mapping[str, object] = field(default_factory=dict)


class FortyGuardClient:
    """Authenticated submit/poll boundary; billable work is submitted exactly once."""

    def __init__(
        self,
        transport: FortyGuardTransport,
        api_key: str,
        *,
        clock: Callable[[], datetime],
        event_sink: Callable[[Mapping[str, object]], None] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        self._transport = transport
        self._api_key = api_key
        self._clock = clock
        self._event_sink = event_sink

    def submit_and_poll(
        self,
        endpoint: str,
        payload: Mapping[str, object],
        *,
        sleep: Callable[[float], None] = default_sleep,
        max_polls: int = 12,
    ) -> tuple[Mapping[str, object], ActivityMetadata]:
        response = self._transport.post(endpoint, payload, self._api_key)
        status_code = response.get("status_code")
        if isinstance(status_code, int) and status_code >= 400:
            raise classify_provider_error(status_code, "activity submission failed")
        activity_id = response.get("activity_id")
        if not isinstance(activity_id, str) or not activity_id:
            raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="missing activity id")
        submitted_at = self._clock()
        self._emit(
            "fortyguard.submitted",
            {"activity_id": activity_id, "endpoint": endpoint, "request": _sanitize_payload(payload)},
        )
        transitions: list[str] = []

        def get_status(_: str) -> Mapping[str, object]:
            return self._transport.get(f"/v1/status/{activity_id}", self._api_key)

        result = poll_activity(
            activity_id,
            get_status=get_status,
            sleep=sleep,
            max_polls=max_polls,
            on_transition=transitions.append,
            on_event=self._emit,
        )
        metadata = ActivityMetadata(
            activity_id,
            submitted_at,
            endpoint,
            tuple(sorted(payload)),
            tuple(transitions),
            _response_metadata(result),
        )
        self._emit("fortyguard.completed", {"activity_id": activity_id, **_response_metadata(result)})
        return result, metadata

    def _emit(self, event: str, fields: Mapping[str, object]) -> None:
        if self._event_sink is not None:
            self._event_sink({"event": event, "at": self._clock().isoformat(), **fields})


def poll_activity(
    activity_id: str,
    *,
    get_status: Callable[[str], Mapping[str, object]],
    sleep: Callable[[float], None] = default_sleep,
    max_polls: int = 12,
    interval_seconds: float = 1.0,
    on_transition: Callable[[str], None] | None = None,
    on_event: Callable[[str, Mapping[str, object]], None] | None = None,
) -> Mapping[str, object]:
    """Poll one already-submitted billable activity with bounded status checks."""
    saw_submission_404 = False
    for poll_number in range(1, max_polls + 1):
        response = get_status(activity_id)
        status_code = response.get("status_code")
        if status_code == 429:
            if on_transition is not None:
                on_transition("rate_limited")
            if on_event is not None:
                on_event("fortyguard.status_transition", {"activity_id": activity_id, "status": "rate_limited"})
            if poll_number < max_polls:
                sleep(interval_seconds)
                continue
        if isinstance(status_code, int) and status_code >= 500:
            if on_transition is not None:
                on_transition("server_error")
            if on_event is not None:
                on_event("fortyguard.status_transition", {"activity_id": activity_id, "status": "server_error"})
            if poll_number < max_polls:
                sleep(interval_seconds)
                continue
        if status_code == 404 and not saw_submission_404:
            saw_submission_404 = True
        elif status_code == 404:
            raise classify_provider_error(404, "activity not found")
        status = response.get("status")
        if isinstance(status, str) and on_transition is not None:
            on_transition(status)
        if isinstance(status, str) and on_event is not None:
            on_event("fortyguard.status_transition", {"activity_id": activity_id, "status": status})
        if status == "Completed":
            result = response.get("result")
            if not isinstance(result, Mapping):
                raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="missing task result")
            return result
        if status == "Failed":
            raise ProviderError(ProviderErrorKind.TASK_FAILURE, detail="provider task failed")
        if status_code not in (None, 200, 202, 404):
            if not isinstance(status_code, int):
                raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="invalid status code")
            raise classify_provider_error(status_code, "status lookup failed")
        if poll_number < max_polls:
            sleep(interval_seconds)
    raise ProviderError(ProviderErrorKind.TIMEOUT, detail="activity polling timed out")


def _response_metadata(result: Mapping[str, object]) -> dict[str, object]:
    return {key: result[key] for key in ("credits_used", "request_id") if key in result}


@dataclass(frozen=True)
class Tile:
    identity: str
    geometry: Mapping[str, object]
    metric: AnalyticType
    value_celsius: float
    unit: str
    source: str
    valid_time: datetime
    forecast: bool
    threshold_celsius: float | None = None
    direction: str | None = None
    activity_id: str | None = None


@dataclass(frozen=True)
class HeatmapResult:
    tiles: tuple[Tile, ...]
    provenance: Provenance


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing freshness metadata")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _sanitize_payload(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if re.search(r"(?i)(api[_ -]?key|authorization|token)", str(key)) else _sanitize_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    return value


def normalize_heatmap_response(
    payload: Mapping[str, object],
    *,
    request: HeatmapRequest,
    retrieved_at: datetime,
    activity_id: str | None = None,
    source: str = "provider",
    data_date: str | None = None,
) -> HeatmapResult:
    features = payload.get("features")
    if not isinstance(features, Sequence) or isinstance(features, (str, bytes)) or not features:
        raise ValueError("heatmap response contains no features")
    tiles: list[Tile] = []
    units: set[str] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, Mapping):
            raise ValueError("malformed heatmap feature")
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if (
            not isinstance(geometry, Mapping)
            or geometry.get("type") not in {"Point", "Polygon", "MultiPolygon"}
            or not geometry.get("coordinates")
        ):
            raise ValueError("missing geometry")
        if not isinstance(properties, Mapping):
            raise ValueError("malformed heatmap properties")
        metric = properties.get("metric", request.analytic_type.value)
        if metric != request.analytic_type.value:
            raise ValueError("unknown or mismatched metric")
        value = properties.get("value")
        unit = properties.get("unit")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or unit != "C":
            raise ValueError("mixed or unsupported units")
        valid_time = _parse_datetime(properties.get("valid_time"))
        units.add(unit)
        tiles.append(Tile(str(properties.get("id", index)), geometry, request.analytic_type, float(value), unit, source, valid_time, request.forecast, request.threshold_celsius, request.direction, activity_id))
    if len(units) != 1:
        raise ValueError("mixed or unsupported units")
    sanitized_payload = _sanitize_payload(payload)
    if not isinstance(sanitized_payload, dict):
        raise ValueError("malformed heatmap payload")
    return HeatmapResult(
        tuple(tiles),
        Provenance(
            source,
            retrieved_at,
            data_date or request.start_date.isoformat(),
            source == "cache",
            request.forecast,
            activity_id,
            sanitized_payload,
        ),
    )
