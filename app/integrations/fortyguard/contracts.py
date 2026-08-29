"""Offline-safe request and response contracts for the FortyGuard API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
import math
from typing import Literal, Mapping, Sequence

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from app.conversion import normalize_temperature
from app.domain.analysis import (
    PointMatch,
    SpatialMatch,
    SpatialMetadata,
    TileGeometry,
    join_point_to_tiles,
    join_polygon_to_tiles,
)
from app.domain.environment import TimeWindow
from app.domain.provenance import Provenance, Transformation
from app.domain.security import sanitize_payload
from app.integrations.fortyguard.client import ActivityMetadata

PROVIDER_CONFIG_VERSION = "fortyguard-config-v1"
"""Provider/request-construction semantics a response was produced under (ADR 0004)."""


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
    start_hour: int | None = None
    end_hour: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.analytic_type, AnalyticType):
            raise ValueError("unknown analytic type")
        if not isinstance(self.forecast, bool):
            raise ValueError("forecast must be a boolean")
        _validate_us_coordinates(self.latitude, self.longitude)
        if self.forecast and not date.today() <= self.start_date <= date.today() + timedelta(
            days=1
        ):
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
        if (
            isinstance(self.granularity, bool)
            or not isinstance(self.granularity, int)
            or self.granularity not in (60, 80, 100)
        ):
            raise ValueError("granularity must be 60, 80, or 100 meters")
        _validate_hour_window(self.start_hour, self.end_hour)

    @property
    def window(self) -> TimeWindow | None:
        """The validated traveler window, or ``None`` for a full-day request.

        Re-deriving from the validated hours hands callers the domain type (with
        its ``start_time``/``end_time`` rendering) instead of raw integers.
        """
        return _validate_hour_window(self.start_hour, self.end_hour)

    @property
    def hours(self) -> range | None:
        """The hours covered by the window, or ``None`` for a full-day request."""
        window = self.window
        return window.hours if window is not None else None

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
        if self.start_hour is not None and self.end_hour is not None:
            payload["start_hour"] = self.start_hour
            payload["end_hour"] = self.end_hour
        return payload


def _validate_hour_window(start_hour: int | None, end_hour: int | None) -> TimeWindow | None:
    """Validate an optional whole-hour window by delegating to the domain rule.

    The one-day / whole-hours / at-most-twelve-hours rule lives in
    :class:`app.domain.environment.TimeWindow`; this helper only maps the
    all-or-nothing field contract onto it. Both bounds must be set together or
    neither — a single bound is a caller mistake, not a full-day request.
    """
    if start_hour is None and end_hour is None:
        return None
    if (start_hour is None) != (end_hour is None):
        raise ValueError("start_hour and end_hour must be set together")
    return TimeWindow(start_hour or 0, end_hour or 0)


@dataclass(frozen=True)
class EnvParamsRequest:
    latitude: float
    longitude: float
    start_date: date
    temperature_anchor_celsius: float | None
    is_real_forecast: bool = False
    hour: int | None = None
    start_hour: int | None = None
    end_hour: int | None = None

    def __post_init__(self) -> None:
        _validate_us_coordinates(self.latitude, self.longitude)
        if (
            self.temperature_anchor_celsius is None
            or isinstance(self.temperature_anchor_celsius, bool)
            or not isinstance(self.temperature_anchor_celsius, (int, float))
            or not math.isfinite(self.temperature_anchor_celsius)
        ):
            raise ValueError("caller-supplied temperature anchor is required")
        if self.is_real_forecast:
            raise ValueError("fixed-anchor env_params cannot be a real forecast")
        if self.hour is not None:
            if (
                isinstance(self.hour, bool)
                or not isinstance(self.hour, int)
                or not 0 <= self.hour <= 23
            ):
                raise ValueError("hour must be an integer between 0 and 23")
        if self.hour is not None and (self.start_hour is not None or self.end_hour is not None):
            raise ValueError("hour and start_hour/end_hour must not be set together")
        _validate_hour_window(self.start_hour, self.end_hour)

    @property
    def window(self) -> TimeWindow | None:
        """The validated traveler window, or ``None`` for full-day/single-hour requests."""
        return _validate_hour_window(self.start_hour, self.end_hour)

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
        if self.start_hour is not None and self.end_hour is not None:
            payload["start_hour"] = self.start_hour
            payload["end_hour"] = self.end_hour
        return payload


@dataclass(frozen=True)
class AreaHeatmapRequest:
    geometry: Mapping[str, object]
    analytic_types: tuple[AnalyticType, ...]
    context: str
    unit: str
    unit_source: str

    def __post_init__(self) -> None:
        if self.geometry.get("type") not in {
            "Polygon",
            "MultiPolygon",
        } or not _valid_geometry_coordinates(self.geometry):
            raise ValueError("area heatmap requires polygon geometry")
        if not self.analytic_types:
            raise ValueError("at least one analytic type is required")
        if any(
            not isinstance(analytic_type, AnalyticType) for analytic_type in self.analytic_types
        ):
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


ENVIRONMENT_PARAMETERS = (
    "heat_index_celsius",
    "apparent_temperature_celsius",
    "wet_bulb_temperature_celsius",
    "relative_humidity_percent",
    "precipitation_mm",
    "cloud_cover_octas",
    "elevation",
    "air_quality:idx",
    "air_quality_pm2p5:idx",
    "air_quality_pm10:idx",
    "air_quality_no2:idx",
    "aqi_us_co",
    "air_quality_o3:idx",
    "air_quality_so2:idx",
    "methane_ppb",
    "co2_ppm",
    "solar_irradiance",
)


@dataclass(frozen=True)
class EnvParamsEntry:
    """One hour of all returned environmental parameters."""

    valid_time: datetime
    heat_index_celsius: float | None
    humidity_percent: float | None
    parameters: Mapping[str, float | None] = field(default_factory=dict)


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


_FLAT_METADATA_KEYS = frozenset(
    {"timestamps", "timestamp", "timezone", "count", "forecast", "mode"}
)


def _is_series(value: object) -> bool:
    """Report whether a flat-shape value is a parameter series rather than metadata.

    The flat shape mixes scalar metadata (``offset``, ``interval``) in among the
    parameter arrays, so shape decides what is a series instead of a fixed name
    list. That keeps every real environmental parameter without having to
    enumerate metadata the provider may add later.

    Known limitation: a genuine parameter that is scalar-shaped is
    indistinguishable from metadata here and is dropped silently. A live call on
    2026-08-29 returned 15 of the 17 requested parameters, with ``elevation``
    and ``solar_irradiance`` absent; whether the provider omitted them or sent
    them as scalars is undetermined, and ``elevation`` is time-invariant so the
    scalar case is plausible. Resolving it needs the raw payload.
    """
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def normalize_env_params_response(
    payload: Mapping[str, object], *, request: EnvParamsRequest
) -> EnvParamsResult:
    if payload.get("forecast") is True:
        raise ValueError("fixed-anchor env_params response cannot be a real forecast")
    timestamps, timezone, series = _env_params_series(payload)
    entries = tuple(
        EnvParamsEntry(
            valid_time=_parse_datetime(timestamp),
            heat_index_celsius=series["heat_index_celsius"][index],
            humidity_percent=series["relative_humidity_percent"][index],
            parameters={name: values[index] for name, values in series.items()},
        )
        for index, timestamp in enumerate(timestamps)
    )
    if not entries:
        raise ValueError("env params response contains no entries")
    return EnvParamsResult(
        entries,
        timezone,
        False,
        "caller-supplied temperature anchor; not a real 24-hour forecast",
    )


def _env_params_series(
    payload: Mapping[str, object],
) -> tuple[Sequence[object], str, dict[str, list[float | None]]]:
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
) -> tuple[Sequence[object], str, dict[str, list[float | None]]]:
    timestamps = metadata.get("timestamps")
    if not isinstance(timestamps, Sequence) or isinstance(timestamps, (str, bytes)):
        raise ValueError("missing freshness metadata")
    timezone = metadata.get("timezone")
    if not isinstance(timezone, str) or not timezone:
        raise ValueError("missing timezone metadata")
    locations = payload.get("locations")
    if (
        not isinstance(locations, Sequence)
        or isinstance(locations, (str, bytes))
        or len(locations) != 1
    ):
        raise ValueError("single-point env params requires exactly one location")
    location = locations[0]
    if not isinstance(location, Mapping):
        raise ValueError("malformed env params location")
    parameters = location.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("malformed env params parameters")
    series = {
        name: [_series_value(value, _series_error_name(name)) for value in _series_list(raw, name)]
        for name, raw in parameters.items()
    }
    for name in ("heat_index_celsius", "relative_humidity_percent"):
        if name not in series:
            raise ValueError(f"missing {_series_error_name(name)} series")
    _ensure_legacy_series(series, timestamps)
    return timestamps, timezone, series


def _flat_series(
    payload: Mapping[str, object],
) -> tuple[Sequence[object], str, dict[str, list[float | None]]]:
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
        name: [
            _series_value(value, _series_error_name(name)) for value in _series_list(values, name)
        ]
        for name, values in payload.items()
        if name not in _FLAT_METADATA_KEYS and _is_series(values)
    }
    for name in ("heat_index_celsius", "relative_humidity_percent"):
        if name not in series:
            raise ValueError(f"missing {_series_error_name(name)} series")
    _ensure_legacy_series(series, timestamps)
    return timestamps, timezone, series


def _series_error_name(name: str) -> str:
    return {
        "heat_index_celsius": "heat index",
        "relative_humidity_percent": "humidity",
    }.get(name, name)


def _ensure_legacy_series(
    series: dict[str, list[float | None]], timestamps: Sequence[object]
) -> None:
    length = len(timestamps)
    for name in ("heat_index_celsius", "relative_humidity_percent"):
        series.setdefault(name, [None] * length)
    _require_aligned(series, timestamps)


def _require_aligned(series: dict[str, list[float | None]], timestamps: Sequence[object]) -> None:
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
    unit_source: Literal["explicit", "inferred"] = "explicit"
    source_value: float | None = None
    source_unit: str | None = None
    converted: bool = False


@dataclass(frozen=True)
class HeatmapResult:
    tiles: tuple[Tile, ...]
    provenance: Provenance
    activity: ActivityMetadata | None = None

    def _spatial_tiles(self) -> list[TileGeometry]:
        return [
            TileGeometry(
                tile.identity,
                _tile_shape(tile),
                tile.metric_value,
                SpatialMetadata(
                    metric=tile.metric.value,
                    unit=tile.unit,
                    source=tile.source,
                    valid_time=tile.valid_time.isoformat(),
                    forecast=tile.forecast,
                    threshold_celsius=tile.threshold_celsius,
                    direction=tile.direction,
                    activity_id=tile.activity_id,
                    unit_source=tile.unit_source,
                    source_value=tile.source_value,
                    source_unit=tile.source_unit,
                    converted=tile.converted,
                ),
            )
            for tile in self.tiles
        ]

    def point_lookup(
        self,
        point: Point,
        *,
        aoi: BaseGeometry,
        nearest_max_distance_m: float | None = None,
    ) -> PointMatch:
        """Look up one point without making another provider request."""
        return join_point_to_tiles(
            point,
            self._spatial_tiles(),
            aoi=aoi,
            nearest_max_distance_m=nearest_max_distance_m,
        )

    def polygon_lookup(self, target: BaseGeometry) -> SpatialMatch:
        """Return an area-weighted lookup for a polygon in a local projected CRS."""
        return join_polygon_to_tiles(target, self._spatial_tiles())


def _tile_shape(tile: Tile) -> BaseGeometry:
    try:
        return shape(tile.geometry)
    except (TypeError, ValueError):
        raise ValueError(f"tile {tile.identity} geometry is invalid") from None


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing freshness metadata")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("malformed freshness metadata") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("malformed freshness metadata")
    return parsed


def normalize_heatmap_response(
    payload: Mapping[str, object],
    *,
    request: HeatmapRequest,
    retrieved_at: datetime,
    activity_id: str | None = None,
    activity: ActivityMetadata | None = None,
    inferred_unit: str | None = None,
    source: str = "provider",
    data_date: str | None = None,
    transformations: tuple[Transformation, ...] = (),
    stale: bool | None = None,
) -> HeatmapResult:
    """Normalize any heatmap payload shape into the shared validated tile schema.

    ``stale`` defaults to True only for cache replays; callers override it for
    stale-labelled fixture fallbacks and date-relaxed forecast replays
    (ADR 0004).
    """
    if activity is not None:
        if activity_id is not None and activity_id != activity.activity_id:
            raise ValueError("activity metadata does not match activity id")
        activity_id = activity.activity_id
    map_data = payload.get("map_data")
    if map_data is not None and not isinstance(map_data, Mapping):
        raise ValueError("malformed heatmap map data")
    feature_collection = map_data if isinstance(map_data, Mapping) else payload
    if map_data is not None:
        if feature_collection.get("type") != "FeatureCollection":
            raise ValueError("malformed heatmap feature collection")
    elif feature_collection.get("type") not in (None, "FeatureCollection"):
        raise ValueError("malformed heatmap feature collection")
    features = feature_collection.get("features")
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
        if map_data is not None and feature.get("type") != "Feature":
            raise ValueError("malformed heatmap feature")
        if map_data is None and "type" in feature and feature.get("type") != "Feature":
            raise ValueError("malformed heatmap feature")
        if (
            feature_collection.get("type") == "FeatureCollection"
            and feature.get("type") != "Feature"
        ):
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
        valid_time = _parse_datetime(properties.get("valid_time"))
        value, unit, unit_source = _metric_value(properties, request.analytic_type, inferred_unit)
        expected_unit = "C" if request.analytic_type is AnalyticType.TCM else "hours"
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("mixed or unsupported units")
        numeric_value = float(value)
        source_value = numeric_value
        source_unit = _canonical_unit(unit, request.analytic_type)
        converted = False
        if request.analytic_type is AnalyticType.TCM and source_unit == "F":
            conversion = normalize_temperature(
                numeric_value,
                source_unit=source_unit,
                unit_provenance=unit_source,
            )
            numeric_value = conversion.normalized_value
            converted = conversion.converted
        elif source_unit != expected_unit:
            raise ValueError("mixed or unsupported units")
        units.add(source_unit)
        tiles.append(
            Tile(
                str(properties.get("id", index)),
                geometry,
                request.analytic_type,
                numeric_value if request.analytic_type is AnalyticType.TCM else None,
                numeric_value,
                expected_unit,
                source,
                valid_time,
                request.forecast,
                request.threshold_celsius,
                request.direction,
                activity_id,
                unit_source,
                source_value,
                source_unit,
                converted,
            )
        )
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
            source == "cache" if stale is None else stale,
            request.forecast,
            activity_id,
            sanitized_payload,
            transformations,
        ),
        activity,
    )


def _metric_value(
    properties: Mapping[str, object],
    analytic_type: AnalyticType,
    inferred_unit: str | None,
) -> tuple[object, object, Literal["explicit", "inferred"]]:
    value = properties.get("value")
    temperature_present = analytic_type is AnalyticType.TCM and "temperature" in properties
    temperature = properties.get("temperature") if temperature_present else None
    if temperature_present and (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(temperature)
    ):
        raise ValueError("malformed properties.temperature")
    if value is not None and temperature_present:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("conflicting properties.value and properties.temperature")
        if value != temperature:
            raise ValueError("conflicting properties.value and properties.temperature")
    if value is None and temperature_present:
        value = temperature
    if value is None:
        raise ValueError("malformed heatmap metric")
    temperature_unit = properties.get("temperature_unit")
    ordinary_unit = properties.get("unit")
    if temperature_unit is not None and ordinary_unit is not None:
        if _canonical_unit(temperature_unit, analytic_type) != _canonical_unit(
            ordinary_unit, analytic_type
        ):
            raise ValueError("conflicting metric units")
    unit = temperature_unit if temperature_unit is not None else ordinary_unit
    if unit is None:
        if inferred_unit is None:
            raise ValueError("missing metric unit")
        return value, inferred_unit, "inferred"
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("mixed or unsupported units")
    return value, unit, "explicit"


def _canonical_unit(unit: object, analytic_type: AnalyticType) -> str:
    if not isinstance(unit, str):
        raise ValueError("mixed or unsupported units")
    normalized = unit.strip().lower().replace("°", "")
    if analytic_type is AnalyticType.TCM and normalized in {"c", "celsius"}:
        return "C"
    if analytic_type is AnalyticType.TCM and normalized in {"f", "fahrenheit"}:
        return "F"
    if analytic_type is not AnalyticType.TCM and normalized == "hours":
        return "hours"
    raise ValueError("mixed or unsupported units")


def _valid_geometry_coordinates(geometry: Mapping[str, object]) -> bool:
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Point":
        return (
            isinstance(coordinates, list)
            and len(coordinates) == 2
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in coordinates
            )
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
        else all(
            isinstance(polygon, list) and polygon and all(valid_ring(ring) for ring in polygon)
            for polygon in coordinates
        )
    )
    if not structurally_valid:
        return False
    try:
        return bool(shape(dict(geometry)).is_valid)
    except (TypeError, ValueError):
        return False


def _validate_us_coordinates(latitude: float, longitude: float) -> None:
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not 24 <= latitude <= 50
        or not -125 <= longitude <= -66
    ):
        raise ValueError("coordinates must be within the supported US extent")
