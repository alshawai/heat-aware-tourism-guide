"""Offline-safe request and response contracts for the FortyGuard API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
import math
from typing import Mapping, Sequence

from shapely.geometry import shape

from app.domain.provenance import Provenance, Transformation
from app.domain.security import sanitize_payload


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
    granularity: int = 60

    def __post_init__(self) -> None:
        if not isinstance(self.analytic_type, AnalyticType):
            raise ValueError("unknown analytic type")
        if not isinstance(self.forecast, bool):
            raise ValueError("forecast must be a boolean")
        _validate_us_coordinates(self.latitude, self.longitude)
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
        if isinstance(self.granularity, bool) or not isinstance(self.granularity, int) or self.granularity not in (60, 80, 100):
            raise ValueError("granularity must be 60, 80, or 100 meters")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "analytic_type": self.analytic_type.value,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "start_date": self.start_date.isoformat(),
            "forecast": self.forecast,
            "granularity": self.granularity,
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
    hour: int | None = None

    def __post_init__(self) -> None:
        _validate_us_coordinates(self.latitude, self.longitude)
        if self.temperature_anchor_celsius is None or isinstance(self.temperature_anchor_celsius, bool) or not isinstance(self.temperature_anchor_celsius, (int, float)) or not math.isfinite(self.temperature_anchor_celsius):
            raise ValueError("caller-supplied temperature anchor is required")
        if self.is_real_forecast:
            raise ValueError("fixed-anchor env_params cannot be a real forecast")
        if self.hour is not None:
            if isinstance(self.hour, bool) or not isinstance(self.hour, int) or not 0 <= self.hour <= 23:
                raise ValueError("hour must be an integer between 0 and 23")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "start_date": self.start_date.isoformat(),
            "temperature_anchor_celsius": self.temperature_anchor_celsius,
            "forecast": False,
            "warning": "fixed temperature anchor; not a real 24-hour forecast",
        }
        if self.hour is not None:
            payload["hour"] = self.hour
        return payload


@dataclass(frozen=True)
class AreaHeatmapRequest:
    geometry: Mapping[str, object]
    analytic_types: tuple[AnalyticType, ...]
    context: str
    unit: str
    unit_source: str

    def __post_init__(self) -> None:
        if self.geometry.get("type") not in {"Polygon", "MultiPolygon"} or not _valid_geometry_coordinates(self.geometry):
            raise ValueError("area heatmap requires polygon geometry")
        if not self.analytic_types:
            raise ValueError("at least one analytic type is required")
        if any(not isinstance(analytic_type, AnalyticType) for analytic_type in self.analytic_types):
            raise ValueError("area analytic types must be known")
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
class EnvParamsEntry:
    """One hour of the environmental series; missing values stay None, never zero."""

    valid_time: datetime
    heat_index_celsius: float | None
    humidity_percent: float | None


@dataclass(frozen=True)
class EnvParamsResult:
    entries: tuple[EnvParamsEntry, ...]
    timezone: str
    forecast: bool
    warning: str


def _series_value(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"invalid {field} series value")
    numeric = float(value)
    return None if numeric == -999 else numeric


def _series_list(series: object, field: str) -> list[object]:
    if not isinstance(series, Sequence) or isinstance(series, (str, bytes)):
        raise ValueError(f"missing {field} series")
    return list(series)


def normalize_env_params_response(
    payload: Mapping[str, object], *, request: EnvParamsRequest
) -> EnvParamsResult:
    if payload.get("forecast") is True:
        raise ValueError("fixed-anchor env_params response cannot be a real forecast")
    timestamps, timezone, series = _env_params_series(payload)
    entries = tuple(
        EnvParamsEntry(
            _parse_datetime(timestamp),
            _series_value(heat, "heat index"),
            _series_value(humidity, "humidity"),
        )
        for timestamp, heat, humidity in zip(timestamps, series["heat"], series["humidity"], strict=True)
    )
    if not entries:
        raise ValueError("env params response contains no entries")
    return EnvParamsResult(
        entries,
        timezone,
        False,
        "caller-supplied temperature anchor; not a real 24-hour forecast",
    )


def _env_params_series(payload: Mapping[str, object]) -> tuple[Sequence[object], str, dict[str, list[object]]]:
    """Extract timestamps, timezone, and the consumed series from either provider shape.

    Two provider shapes are reality: the documented ``metadata`` + ``locations``
    envelope and the flat series observed live during issue #7 validation
    (``timestamp``/``timezone``/``count`` with top-level arrays). Both are
    normalized into the same internal series.
    """
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        return _documented_series(payload, metadata)
    return _flat_series(payload)


def _documented_series(
    payload: Mapping[str, object], metadata: Mapping[str, object]
) -> tuple[Sequence[object], str, dict[str, list[object]]]:
    timestamps = metadata.get("timestamps")
    if not isinstance(timestamps, Sequence) or isinstance(timestamps, (str, bytes)):
        raise ValueError("missing freshness metadata")
    timezone = metadata.get("timezone")
    if not isinstance(timezone, str) or not timezone:
        raise ValueError("missing timezone metadata")
    locations = payload.get("locations")
    if not isinstance(locations, Sequence) or isinstance(locations, (str, bytes)) or len(locations) != 1:
        raise ValueError("single-point env params requires exactly one location")
    location = locations[0]
    if not isinstance(location, Mapping):
        raise ValueError("malformed env params location")
    parameters = location.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("malformed env params parameters")
    series = {
        "heat": _series_list(parameters.get("heat_index_celsius"), "heat index"),
        "humidity": _series_list(parameters.get("relative_humidity_percent"), "humidity"),
    }
    _require_aligned(series, timestamps)
    return timestamps, timezone, series


def _flat_series(payload: Mapping[str, object]) -> tuple[Sequence[object], str, dict[str, list[object]]]:
    timezone = payload.get("timezone")
    if not isinstance(timezone, str) or not timezone:
        raise ValueError("missing timezone metadata")
    raw_timestamps = payload.get("timestamps")
    timestamps: Sequence[object] | None = None
    if isinstance(raw_timestamps, Sequence) and not isinstance(raw_timestamps, (str, bytes)):
        timestamps = raw_timestamps
    if timestamps is None:
        single = payload.get("timestamp")
        count = payload.get("count")
        if isinstance(single, str) and count == 1:
            timestamps = [single]
        else:
            raise ValueError("missing freshness metadata")
    series = {
        "heat": _series_list(payload.get("heat_index_celsius"), "heat index"),
        "humidity": _series_list(payload.get("relative_humidity_percent"), "humidity"),
    }
    _require_aligned(series, timestamps)
    return timestamps, timezone, series


def _require_aligned(series: dict[str, list[object]], timestamps: Sequence[object]) -> None:
    if any(len(values) != len(timestamps) for values in series.values()):
        raise ValueError("env params series must be time-aligned with timestamps")


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
    transformations: tuple[Transformation, ...] = (),
) -> HeatmapResult:
    features = payload.get("features")
    if not isinstance(features, Sequence) or isinstance(features, (str, bytes)) or not features:
        raise ValueError("heatmap response contains no features")
    payload_mode = payload.get("mode")
    if payload_mode is not None:
        expected_mode = "forecast" if request.forecast else "historical"
        if payload_mode != expected_mode:
            raise ValueError("provider forecast/historical mode does not match request")
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
            or not _valid_geometry_coordinates(geometry)
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
            transformations,
        ),
    )


def _valid_geometry_coordinates(geometry: Mapping[str, object]) -> bool:
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Point":
        return isinstance(coordinates, list) and len(coordinates) == 2 and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            for value in coordinates
        )
    if not isinstance(coordinates, list) or not coordinates:
        return False

    def valid_ring(ring: object) -> bool:
        return (
            isinstance(ring, list)
            and len(ring) >= 4
            and ring[0] == ring[-1]
            and all(
                isinstance(position, list)
                and len(position) >= 2
                and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    for value in position[:2]
                )
                for position in ring
            )
        )

    structurally_valid = (
        all(valid_ring(ring) for ring in coordinates)
        if geometry.get("type") == "Polygon"
        else all(isinstance(polygon, list) and polygon and all(valid_ring(ring) for ring in polygon) for polygon in coordinates)
    )
    if not structurally_valid:
        return False
    try:
        return bool(shape(dict(geometry)).is_valid)
    except (TypeError, ValueError):
        return False


def _validate_us_coordinates(latitude: float, longitude: float) -> None:
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not 24 <= latitude <= 50 or not -125 <= longitude <= -66:
        raise ValueError("coordinates must be within the supported US extent")
