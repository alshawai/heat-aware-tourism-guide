"""Strict product snapshot codec for the complete modern trip contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import Field, fields, is_dataclass
from datetime import datetime
from enum import Enum
import math
from types import UnionType
from typing import Any, Literal, TypeVar, Union, cast, get_args, get_origin, get_type_hints

from app.domain.best_time import HourlyConcernProfile, ParameterConcern
from app.domain.contracts import (
    BestTimeResult,
    ExecutionMode,
    HotelRankingResult,
    ResultState,
    RouteComparisonResult,
    TripAnalysisRequest,
    TripAnalysisResponse,
    UnavailableResult,
)

SCHEMA_VERSION = "trip-contract-v2"
_SNAPSHOT_KEYS = {
    "schema_version",
    "state",
    "best_time",
    "hotels",
    "routes",
    "unavailable",
    "degraded_reasons",
}
_TYPE_LOCALNS = {
    "HourlyConcernProfile": HourlyConcernProfile,
    "ParameterConcern": ParameterConcern,
}
_T = TypeVar("_T")


def encode_trip_analysis_v2(
    response: TripAnalysisResponse, *, envelope: Literal["snapshot", "api"] = "snapshot"
) -> dict[str, object]:
    """Encode a validated response as a snapshot or frontend API envelope."""
    if not isinstance(response, TripAnalysisResponse):
        raise ValueError("response must be a TripAnalysisResponse")
    if response.state not in {ResultState.SUCCESS, ResultState.DEGRADED, ResultState.UNAVAILABLE}:
        raise ValueError("trip-contract-v2 supports success, degraded, and unavailable states")
    if envelope not in {"snapshot", "api"}:
        raise ValueError("envelope must be snapshot or api")

    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "state": response.state.value,
        "best_time": _encode_value(response.best_time),
        "hotels": _encode_value(response.hotels),
        "routes": _encode_value(response.routes),
        "unavailable": _encode_value(response.unavailable),
        "degraded_reasons": _encode_value(response.degraded_reasons),
    }
    if envelope == "api":
        payload.update(
            request_identity=response.request_identity,
            mode=response.mode.value,
            execution_mode=response.execution_mode.value,
        )
    return payload


def decode_trip_analysis_v2(
    payload: Mapping[str, object],
    request: TripAnalysisRequest,
    execution_mode: ExecutionMode,
) -> TripAnalysisResponse:
    """Decode a strict snapshot using adapter-owned request and execution identity."""
    if not isinstance(payload, Mapping):
        raise ValueError("trip-contract-v2 payload must be an object")
    _require_exact_keys(payload, _SNAPSHOT_KEYS, "trip-contract-v2 payload")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    state = _decode_value(ResultState, payload["state"], "state")
    if state not in {ResultState.SUCCESS, ResultState.DEGRADED, ResultState.UNAVAILABLE}:
        raise ValueError("trip-contract-v2 state must be success, degraded, or unavailable")

    response = TripAnalysisResponse(
        request_identity=_request_identity(request),
        mode=request.mode,
        execution_mode=execution_mode,
        state=state,
        best_time=_decode_optional_dataclass(BestTimeResult, payload["best_time"], "best_time"),
        hotels=_decode_optional_dataclass(HotelRankingResult, payload["hotels"], "hotels"),
        routes=_decode_optional_dataclass(RouteComparisonResult, payload["routes"], "routes"),
        unavailable=_decode_optional_dataclass(
            UnavailableResult, payload["unavailable"], "unavailable"
        ),
        degraded_reasons=_decode_value(
            dict[str, str] | None, payload["degraded_reasons"], "degraded_reasons"
        ),
    )
    _validate_request_alignment(response, request)
    return response


def _encode_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("trip-contract-v2 numbers must be finite")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _encode_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("trip-contract-v2 mapping keys must be strings")
        return {key: _encode_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode_value(item) for item in value]
    raise ValueError(f"unsupported trip-contract-v2 value: {type(value).__name__}")


def _decode_optional_dataclass(cls: type[_T], value: object, field_name: str) -> _T | None:
    if value is None:
        return None
    return _decode_dataclass(cls, value, field_name)


def _decode_dataclass(cls: type[_T], value: object, field_name: str) -> _T:
    mapping = _mapping(value, field_name)
    hints = get_type_hints(cls, localns=_TYPE_LOCALNS)
    dataclass_fields: tuple[Field[Any], ...] = fields(cast(Any, cls))
    expected = {field.name for field in dataclass_fields}
    _require_exact_keys(mapping, expected, field_name)
    decoded = {
        field.name: _decode_value(
            hints[field.name], mapping[field.name], f"{field_name}.{field.name}"
        )
        for field in dataclass_fields
    }
    return cls(**decoded)


def _decode_value(annotation: object, value: object, field_name: str) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, UnionType):
        if value is None and type(None) in args:
            return None
        variants = tuple(item for item in args if item is not type(None))
        errors: list[ValueError] = []
        for variant in variants:
            try:
                return _decode_value(variant, value, field_name)
            except ValueError as error:
                errors.append(error)
        raise errors[-1] if errors else ValueError(f"{field_name} has an invalid value")
    if origin is tuple:
        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be a list")
        item_type = args[0]
        return tuple(
            _decode_value(item_type, item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        )
    if origin in (dict, Mapping):
        mapping = _mapping(value, field_name)
        key_type, item_type = args
        if key_type is not str or any(not isinstance(key, str) for key in mapping):
            raise ValueError(f"{field_name} keys must be strings")
        return {
            key: _decode_value(item_type, item, f"{field_name}.{key}")
            for key, item in mapping.items()
        }
    if annotation is Any or annotation is object:
        return _decode_json_value(value, field_name)
    if annotation is datetime:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be an ISO datetime")
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{field_name} must be an ISO datetime") from error
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        try:
            return annotation(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field_name} has an invalid enum value") from error
    if isinstance(annotation, type) and is_dataclass(annotation):
        return _decode_dataclass(annotation, value, field_name)
    if annotation is str:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")
        return value
    if annotation is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{field_name} must be a boolean")
        return value
    if annotation is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field_name} must be an integer")
        return value
    if annotation is float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{field_name} must be a finite number")
        return float(value)
    raise ValueError(f"unsupported type for {field_name}")


def _decode_json_value(value: object, field_name: str) -> object:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must contain finite numbers")
        return value
    if isinstance(value, list):
        return [_decode_json_value(item, f"{field_name}[]") for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{field_name} keys must be strings")
        return {key: _decode_json_value(item, f"{field_name}.{key}") for key, item in value.items()}
    raise ValueError(f"{field_name} must contain JSON-safe values")


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_exact_keys(payload: Mapping[str, object], expected: set[str], field_name: str) -> None:
    actual = set(payload)
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        raise ValueError(f"{field_name} contains unknown keys: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{field_name} is missing keys: {sorted(missing)}")


def _request_identity(request: TripAnalysisRequest) -> str:
    return f"{request.mode.value}:{request.date}:{request.start_hour}-{request.end_hour}"


def _validate_request_alignment(
    response: TripAnalysisResponse, request: TripAnalysisRequest
) -> None:
    for section_name, section in (
        ("best_time", response.best_time),
        ("hotels", response.hotels),
        ("routes", response.routes),
    ):
        if section is not None and section.provenance.data_date != request.date:
            raise ValueError(f"{section_name} provenance date does not match request")
    best_time = response.best_time
    if best_time is None or best_time.temporal_evidence.value != "exact":
        return
    recommendation_time = best_time.recommendation_time
    if recommendation_time is None:
        raise ValueError("exact best-time evidence requires recommendation_time")
    if (
        recommendation_time.date().isoformat() != request.date
        or recommendation_time.hour != best_time.recommendation_hour
    ):
        raise ValueError("recommendation_time does not match the requested date and hour")
