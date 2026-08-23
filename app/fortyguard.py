"""Offline-safe contracts for the asynchronous FortyGuard API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
import math
import re
import json
from time import sleep as default_sleep
from typing import Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.domain import Provenance
from app.ledger import CreditLedger, UsageRecord
from app.security import sanitize_payload


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
            if (
                isinstance(self.threshold_celsius, bool)
                or not isinstance(self.threshold_celsius, (int, float))
                or not math.isfinite(self.threshold_celsius)
            ):
                raise ValueError("threshold is required for this analytic type")
            if self.direction not in ("above", "below"):
                raise ValueError("direction must be above or below")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "analytic_type": self.analytic_type.value,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "start_date": self.start_date.isoformat(),
            "forecast": self.forecast,
        }
        if self.threshold_celsius is not None:
            payload["threshold_celsius"] = self.threshold_celsius
        if self.direction is not None:
            payload["direction"] = self.direction
        return payload


@dataclass(frozen=True)
class EnvParamsRequest:
    latitude: float
    longitude: float
    start_date: date
    temperature_anchor_celsius: float | None
    is_real_forecast: bool = False

    def __post_init__(self) -> None:
        if not 24 <= self.latitude <= 50 or not -125 <= self.longitude <= -66:
            raise ValueError("coordinates must be within the supported US extent")
        if self.temperature_anchor_celsius is None:
            raise ValueError("caller-supplied temperature anchor is required")

    def to_payload(self) -> dict[str, object]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "start_date": self.start_date.isoformat(),
            "temperature_anchor_celsius": self.temperature_anchor_celsius,
            "forecast": False,
            "warning": "fixed temperature anchor; not a real 24-hour forecast",
        }


@dataclass(frozen=True)
class AreaHeatmapRequest:
    geometry: Mapping[str, object]
    analytic_types: tuple[AnalyticType, ...]
    context: str
    unit: str
    unit_source: str

    def __post_init__(self) -> None:
        if self.geometry.get("type") not in {"Polygon", "MultiPolygon"} or not self.geometry.get("coordinates"):
            raise ValueError("area heatmap requires polygon geometry")
        if not self.analytic_types:
            raise ValueError("at least one analytic type is required")
        if self.context not in {"district", "corridor"}:
            raise ValueError("area context must be district or corridor")
        if self.unit != "C" or self.unit_source not in {"explicit", "inferred"}:
            raise ValueError("area request requires Celsius with explicit or inferred unit source")

    def to_payload(self) -> dict[str, object]:
        return {
            "geometry": self.geometry,
            "analytic_types": [analytic_type.value for analytic_type in self.analytic_types],
            "context": self.context,
            "unit": self.unit,
            "unit_source": self.unit_source,
        }


@dataclass(frozen=True)
class EnvParamsResult:
    heat_index_celsius: float | None
    humidity_percent: float | None
    valid_time: datetime
    forecast: bool
    warning: str


def normalize_env_params_response(
    payload: Mapping[str, object], *, request: EnvParamsRequest
) -> EnvParamsResult:
    heat_index = payload.get("heat_index_celsius")
    humidity = payload.get("humidity_percent")
    valid_time = payload.get("valid_time")
    if isinstance(heat_index, bool) or (heat_index is not None and not isinstance(heat_index, (int, float))):
        raise ValueError("invalid heat index")
    if isinstance(humidity, bool) or (humidity is not None and not isinstance(humidity, (int, float))):
        raise ValueError("invalid humidity")
    if not isinstance(valid_time, str):
        raise ValueError("missing freshness metadata")
    parsed_time = _parse_datetime(valid_time)
    if payload.get("forecast") is True:
        raise ValueError("fixed-anchor env_params response cannot be a real forecast")
    return EnvParamsResult(
        float(heat_index) if heat_index is not None else None,
        float(humidity) if humidity is not None else None,
        parsed_time,
        False,
        "caller-supplied temperature anchor; not a real 24-hour forecast",
    )


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


class HttpFortyGuardTransport:
    class HttpError(Exception):
        def __init__(self, response: object) -> None:
            self.response = response

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 15,
        opener: Callable[[Request, float], object] = urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def post(self, endpoint: str, payload: Mapping[str, object], api_key: str) -> Mapping[str, object]:
        return self._request(endpoint, api_key, payload)

    def get(self, endpoint: str, api_key: str) -> Mapping[str, object]:
        return self._request(endpoint, api_key)

    def _request(
        self, endpoint: str, api_key: str, payload: Mapping[str, object] | None = None
    ) -> Mapping[str, object]:
        request = Request(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with self._opener(request, self.timeout_seconds) as response:  # type: ignore[attr-defined]
                parsed = json.loads(response.read())
        except self.HttpError as error:
            status = getattr(error.response, "status", None)
            if payload is None and (status in (404, 429) or isinstance(status, int) and status >= 500):
                return {"status_code": status}
            raise classify_provider_error(status, "provider HTTP request failed") from None
        except HTTPError as error:
            if payload is None and (error.code in (404, 429) or error.code >= 500):
                return {"status_code": error.code}
            raise classify_provider_error(error.code, "provider HTTP request failed") from None
        except (TimeoutError, URLError, OSError) as error:
            kind = ProviderErrorKind.TIMEOUT if isinstance(error, TimeoutError) else ProviderErrorKind.SERVER
            raise ProviderError(kind, detail=type(error).__name__) from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="invalid JSON response") from None
        if not isinstance(parsed, Mapping):
            raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="response must be an object")
        return parsed


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
        ledger: CreditLedger | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        self._transport = transport
        self._api_key = api_key
        self._clock = clock
        self._event_sink = event_sink
        self._ledger = ledger

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
            {"activity_id": activity_id, "endpoint": endpoint, "request": sanitize_payload(payload)},
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
        credits_used = result.get("credits_used")
        if self._ledger is not None and isinstance(credits_used, int) and not isinstance(credits_used, bool):
            self._ledger.record(UsageRecord(activity_id, endpoint, credits_used, self._clock(), "completed"))
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
            completed = dict(result)
            for key in ("credits_used", "request_id"):
                if key in response:
                    completed[key] = response[key]
            return completed
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
    value_celsius: float | None
    metric_value: float
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
        expected_unit = "C" if request.analytic_type is AnalyticType.TCM else "hours"
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or unit != expected_unit
        ):
            raise ValueError("mixed or unsupported units")
        valid_time = _parse_datetime(properties.get("valid_time"))
        units.add(unit)
        numeric_value = float(value)
        tiles.append(Tile(str(properties.get("id", index)), geometry, request.analytic_type, numeric_value if request.analytic_type is AnalyticType.TCM else None, numeric_value, unit, source, valid_time, request.forecast, request.threshold_celsius, request.direction, activity_id))
    if len(units) != 1:
        raise ValueError("mixed or unsupported units")
    sanitized_payload = sanitize_payload(payload)
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
