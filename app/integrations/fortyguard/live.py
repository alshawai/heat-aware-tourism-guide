"""Live FortyGuard adapter: documented payload construction, envelope handling, and translation.

This module is the only place that knows the documented live provider shapes
(ADR 0001). The neutral client, poller, and contracts modules stay untouched.
"""

from __future__ import annotations

from datetime import date
import math
from typing import Callable, Mapping, Sequence

from app.domain.provenance import Transformation
from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.contracts import AnalyticType, EnvParamsRequest, HeatmapRequest
from app.integrations.fortyguard.errors import ProviderError, ProviderErrorKind
from app.integrations.fortyguard.transport import HttpFortyGuardTransport
from app.services.execution import LiveEnvParamsPayload, LiveHeatmapPayload

HISTORICAL_EARLIEST = date(2019, 1, 1)
DEFAULT_AREA_GRANULARITY_M = 100
_DEGREES_PER_METER = 1.0 / 111320.0


class LiveFortyGuardTransport(HttpFortyGuardTransport):
    """Transport that hoists the documented ``data`` envelope of every response.

    Submission responses carry ``data.activity_id``; status responses carry
    ``data.status`` and, once completed, ``data.result``. Hoisting ``data``
    lets the shape-neutral client and poller operate unchanged.
    """

    def _request(
        self, endpoint: str, api_key: str, payload: Mapping[str, object] | None = None
    ) -> Mapping[str, object]:
        parsed = super()._request(endpoint, api_key, payload)
        if "data" not in parsed:
            return parsed
        data = parsed["data"]
        if not isinstance(data, Mapping):
            raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="response data envelope must be an object")
        unwrapped: dict[str, object] = {key: value for key, value in parsed.items() if key != "data"}
        unwrapped.update(dict(data))
        return unwrapped


def build_documented_heatmap_payload(
    request: HeatmapRequest, *, today: date | None = None
) -> dict[str, object]:
    """Build the documented live payload and reject out-of-contract dates first.

    The documented heatmap payload is polygon-only: point requests are expanded
    to a square AOI with sides of one granularity unit (ADR 0001). Forecast
    semantics are expressed purely by the date window, so full-day forecast
    requests are limited to today (the documented horizon is 12 hours ahead)
    and historical requests must fall between 2019-01-01 and today.
    """
    current = date.today() if today is None else today
    _validate_documented_window(request, today=current)
    payload: dict[str, object] = {
        "polygon_aoi": _point_square_feature_collection(
            request.latitude, request.longitude, side_m=request.granularity
        ),
        "date_time": {"start_date": request.start_date.isoformat(), "filter_type": 3},
        "granularity": request.granularity,
        "analytic_type": request.analytic_type.value,
    }
    if request.threshold_celsius is not None:
        payload["threshold"] = request.threshold_celsius
    if request.direction is not None:
        payload["direction"] = request.direction
    return payload


def _validate_documented_window(request: HeatmapRequest, *, today: date) -> None:
    if request.forecast:
        if request.start_date != today:
            raise ProviderError(
                ProviderErrorKind.VALIDATION,
                detail="documented forecast window ends 12 hours ahead; full-day forecast heatmaps are limited to today",
            )
    elif not HISTORICAL_EARLIEST <= request.start_date <= today:
        raise ProviderError(
            ProviderErrorKind.VALIDATION,
            detail="historical start date must be between 2019-01-01 and today",
        )


def _point_square_feature_collection(latitude: float, longitude: float, *, side_m: float) -> dict[str, object]:
    half_lat = side_m / 2.0 * _DEGREES_PER_METER
    half_lon = half_lat / math.cos(math.radians(latitude))
    west, east = longitude - half_lon, longitude + half_lon
    south, north = latitude - half_lat, latitude + half_lat
    ring = [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
    ]
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}}
        ],
    }


def translate_heatmap_response(
    result: Mapping[str, object], *, request: HeatmapRequest
) -> dict[str, object]:
    """Translate a completed live heatmap result into the internal tile payload.

    Full-day tcm tiles carry min/max/average_temperature in degrees Celsius and
    hour-based analytics carry properties.value in hours (quickstart-verified
    per-tile fields; the official docs leave them undocumented). The unit and
    the requested-date valid time are stamped as provenance transformations by
    the adapter, not silently assumed (ADR 0002).
    """
    map_data = result.get("map_data")
    if not isinstance(map_data, Mapping):
        raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="missing map_data in completed result")
    features = map_data.get("features")
    if not isinstance(features, Sequence) or isinstance(features, (str, bytes)) or not features:
        raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="map_data contains no features")
    valid_time = f"{request.start_date.isoformat()}T00:00:00+00:00"
    unit = "C" if request.analytic_type is AnalyticType.TCM else "hours"
    internal_features: list[dict[str, object]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, Mapping):
            raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="malformed map_data feature")
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry, Mapping) or not isinstance(properties, Mapping):
            raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="malformed map_data feature")
        value = _tile_value(properties, request.analytic_type)
        internal_features.append(
            {
                "geometry": dict(geometry),
                "properties": {
                    "id": str(properties.get("id", index)),
                    "metric": request.analytic_type.value,
                    "value": value,
                    "unit": unit,
                    "valid_time": valid_time,
                },
            }
        )
    translated: dict[str, object] = {
        "features": internal_features,
        "mode": "forecast" if request.forecast else "historical",
        "data_date": request.start_date.isoformat(),
    }
    stats_data = result.get("stats_data")
    if isinstance(stats_data, Mapping):
        translated["stats_data"] = dict(stats_data)
    return translated


def _tile_value(properties: Mapping[str, object], analytic_type: AnalyticType) -> float:
    candidates = ("average_temperature", "temperature") if analytic_type is AnalyticType.TCM else ("value",)
    for name in candidates:
        value = properties.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            if value is not None:
                raise ProviderError(
                    ProviderErrorKind.MALFORMED_RESPONSE,
                    detail=f"invalid {name} tile value",
                )
            continue
        return float(value)
    raise ProviderError(
        ProviderErrorKind.MALFORMED_RESPONSE,
        detail="tile properties do not match the documented value fields",
    )


def request_transformations(request: HeatmapRequest) -> tuple[Transformation, ...]:
    """The inference stamps every live heatmap result carries (ADR 0002)."""
    stamps = [
        Transformation("live_envelope_unwrapped", 1),
        Transformation("point_to_aoi_expansion", 1),
        Transformation("valid_time_from_request", 1),
    ]
    if request.analytic_type is AnalyticType.TCM:
        stamps.append(Transformation("tcm_unit_celsius", 1))
    return tuple(stamps)


class LiveHeatmapAdapter:
    """Owns the live heatmap path: documented payload, submission, and translation."""

    def __init__(
        self,
        client: FortyGuardClient,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._client = client
        self._today = today

    def load(self, request: HeatmapRequest) -> LiveHeatmapPayload:
        payload = build_documented_heatmap_payload(request, today=self._today())
        result, metadata = self._client.submit_and_poll("/v1/heatmap", payload)
        translated = translate_heatmap_response(result, request=request)
        return LiveHeatmapPayload(
            translated,
            metadata.activity_id,
            request_transformations(request),
        )


def build_documented_env_params_payload(request: EnvParamsRequest) -> dict[str, object]:
    """Build the documented /v1/env_params payload for a single-point series request.

    The caller-supplied Celsius anchor is the documented ``temperature`` input;
    ``analysis`` explicitly lists only the two consumed parameters so the
    request stays within the three-parameter plan limit (ADR 0001). An optional
    hour selects the single-hour filter; the default is the full-day series.
    """
    date_time: dict[str, object] = {"start_date": request.start_date.isoformat(), "filter_type": 1 if request.hour is not None else 3}
    if request.hour is not None:
        date_time["start_time"] = f"{request.hour:02d}:00"
    return {
        "latitude": request.latitude,
        "longitude": request.longitude,
        "temperature": request.temperature_anchor_celsius,
        "date_time": date_time,
        "analysis": ["heat_index_celsius", "relative_humidity_percent"],
    }


class LiveEnvParamsAdapter:
    """Owns the live environmental-parameters path."""

    def __init__(self, client: FortyGuardClient) -> None:
        self._client = client

    def load(self, request: EnvParamsRequest) -> LiveEnvParamsPayload:
        payload = build_documented_env_params_payload(request)
        result, metadata = self._client.submit_and_poll("/v1/env_params", payload)
        return LiveEnvParamsPayload(result, metadata.activity_id)
