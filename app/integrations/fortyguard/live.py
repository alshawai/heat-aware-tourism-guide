"""Live FortyGuard adapter: documented payload construction, envelope handling, and translation.

This module is the only place that knows the documented live provider shapes
(ADR 0001). The neutral client, poller, and contracts modules stay untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import math
from time import sleep as default_sleep
from typing import Callable, Mapping, Sequence

from pyproj import CRS, Transformer
from shapely.geometry import LineString, Polygon, mapping as shapely_mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_ops_transform

from app.domain.environment import TimeWindow
from app.domain.enrichment import EnrichmentPayload
from app.domain.route_heat import SharedRouteHeatRequest
from app.domain.provenance import Transformation
from app.integrations.fortyguard.client import ActivityMetadata, FortyGuardClient
from app.integrations.fortyguard.contracts import (
    ENVIRONMENT_PARAMETERS,
    AnalyticType,
    EnvParamsRequest,
    HeatmapRequest,
)
from app.integrations.fortyguard.errors import ProviderError, ProviderErrorKind
from app.integrations.fortyguard.transport import HttpFortyGuardTransport
from app.settings import FortyGuardPollingSettings

logger = logging.getLogger(__name__)

HISTORICAL_EARLIEST = date(2019, 1, 1)
_DEGREES_PER_METER = 1.0 / 111320.0


@dataclass(frozen=True)
class LivePayload:
    """A completed live provider result with its activity identity and inference stamps."""

    payload: Mapping[str, object]
    activity_id: str | None = None
    transformations: tuple[Transformation, ...] = ()
    activity: ActivityMetadata | None = None
    inferred_unit: str | None = None


# The heatmap and env-params loaders share one payload shape; the two names
# keep call sites and type annotations honest about which path produced them.
LiveHeatmapPayload = LivePayload
LiveEnvParamsPayload = LivePayload


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
            raise ProviderError(
                ProviderErrorKind.MALFORMED_RESPONSE,
                detail="response data envelope must be an object",
            )
        unwrapped: dict[str, object] = {
            key: value for key, value in parsed.items() if key != "data"
        }
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

    A request carrying a validated traveler window (``start_hour``/``end_hour``)
    is submitted as the documented range-of-hours filter (``filter_type`` 2 with
    ``start_time``/``end_time``); without one it stays a full-day request
    (``filter_type`` 3), preserving every existing caller.
    """
    current = date.today() if today is None else today
    _validate_documented_window(
        start_date=request.start_date, forecast=request.forecast, today=current
    )
    payload: dict[str, object] = {
        "polygon_aoi": _point_square_feature_collection(
            request.latitude, request.longitude, side_m=request.granularity
        ),
        "date_time": _date_time_filter(start_date=request.start_date, window=request.window),
        "granularity": request.granularity,
        "analytic_type": request.analytic_type.value,
    }
    if request.threshold_celsius is not None:
        payload["threshold"] = request.threshold_celsius
    if request.direction is not None:
        payload["direction"] = request.direction
    return payload


def _date_time_filter(*, start_date: date, window: TimeWindow | None) -> dict[str, object]:
    """Render the documented ``date_time`` filter block for a request.

    A traveler window becomes the documented range filter (``filter_type`` 2
    with ``start_time``/``end_time`` as ``"HH:00"`` strings); without one the
    request keeps its full-day shape (``filter_type`` 3), which is how
    full-day heatmap and env-params calls are made today (ADR 0001).

    The provider treats the range as inclusive of ``end_time``, so
    :meth:`TimeWindow.end_time` renders the window's last in-window hour rather
    than its exclusive bound. Heatmap and env-params share this helper so a
    chained trip asks both endpoints for the identical set of hours.
    """
    date_time: dict[str, object] = {
        "start_date": start_date.isoformat(),
        "filter_type": 2 if window is not None else 3,
    }
    if window is not None:
        date_time["start_time"] = window.start_time()
        date_time["end_time"] = window.end_time()
    return date_time


def _validate_documented_window(*, start_date: date, forecast: bool, today: date) -> None:
    """Shape-independent date/forecast validation shared by point and area paths."""
    if forecast:
        if start_date != today:
            raise ProviderError(
                ProviderErrorKind.VALIDATION,
                detail="documented forecast window ends 12 hours ahead; full-day forecast heatmaps are limited to today",
            )
    else:
        _validate_documented_date(start_date, today=today)


def _validate_documented_date(start_date: date, *, today: date) -> None:
    if not HISTORICAL_EARLIEST <= start_date <= today:
        raise ProviderError(
            ProviderErrorKind.VALIDATION,
            detail="historical start date must be between 2019-01-01 and today",
        )


def _point_square_feature_collection(
    latitude: float, longitude: float, *, side_m: float
) -> dict[str, object]:
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
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }


def _tile_valid_time(request: HeatmapRequest) -> str:
    """Stamp tiles with the hour the readings were actually requested for.

    A windowed request is submitted as the range filter (``filter_type`` 2 with
    ``start_time``/``end_time``), so the readings that come back describe that
    window rather than midnight. Stamping the window start keeps the tile inside
    the traveler window that :func:`app.domain.environment.select_anchor_celsius`
    tests, which midnight would fall outside of for every daytime window.
    Full-day requests (``filter_type`` 3) carry no hour and keep midnight.
    """
    window = request.window
    hour = 0 if window is None else window.start_hour
    return f"{request.start_date.isoformat()}T{hour:02d}:00:00+00:00"


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
        raise ProviderError(
            ProviderErrorKind.MALFORMED_RESPONSE, detail="missing map_data in completed result"
        )
    features = map_data.get("features")
    if not isinstance(features, Sequence) or isinstance(features, (str, bytes)) or not features:
        raise ProviderError(
            ProviderErrorKind.MALFORMED_RESPONSE, detail="map_data contains no features"
        )
    valid_time = _tile_valid_time(request)
    unit = "C" if request.analytic_type is AnalyticType.TCM else "hours"
    internal_features: list[dict[str, object]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, Mapping):
            raise ProviderError(
                ProviderErrorKind.MALFORMED_RESPONSE, detail="malformed map_data feature"
            )
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry, Mapping) or not isinstance(properties, Mapping):
            raise ProviderError(
                ProviderErrorKind.MALFORMED_RESPONSE, detail="malformed map_data feature"
            )
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
    candidates = (
        ("average_temperature", "temperature") if analytic_type is AnalyticType.TCM else ("value",)
    )
    for name in candidates:
        value = properties.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
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
    """The inference stamps every live point heatmap result carries (ADR 0002).

    ``valid_time_from_request`` is version 2: the rule now derives the tile hour
    from the requested window's start rather than always stamping midnight, so
    consumers can tell window-derived valid times from the date-only rule (ADR
    0002 §3). The area path still applies version 1 — it submits no window.
    """
    stamps = [
        Transformation("live_envelope_unwrapped", 1),
        Transformation("point_to_aoi_expansion", 1),
        Transformation("valid_time_from_request", 2),
    ]
    if request.analytic_type is AnalyticType.TCM:
        stamps.append(Transformation("tcm_unit_celsius", 1))
    return tuple(stamps)


def env_params_transformations() -> tuple[Transformation, ...]:
    """The inference stamps every live env-params result carries (ADR 0002)."""
    return (Transformation("live_envelope_unwrapped", 1),)


class LiveHeatmapAdapter:
    """Owns the live heatmap path: documented payload, submission, and translation."""

    def __init__(
        self,
        client: FortyGuardClient,
        *,
        today: Callable[[], date] = date.today,
        polling: FortyGuardPollingSettings | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._client = client
        self._today = today
        self._polling = polling or FortyGuardPollingSettings()
        self._sleep = sleep

    def load(self, request: HeatmapRequest) -> LiveHeatmapPayload:
        payload = build_documented_heatmap_payload(request, today=self._today())
        result, metadata = self._client.submit_and_poll(
            "/v1/heatmap",
            payload,
            sleep=self._sleep or default_sleep,
            max_polls=self._polling.max_polls,
            interval_seconds=self._polling.interval_seconds,
            status_404_grace_checks=self._polling.status_404_grace_checks,
        )
        translated = translate_heatmap_response(result, request=request)
        return LiveHeatmapPayload(
            translated,
            metadata.activity_id,
            request_transformations(request),
            metadata,
        )


# --- Area (route/polygon) heatmap path  --- #


_DEFAULT_AREA_GRANULARITY = 100
_DEFAULT_BUFFER_M = 25.0
_DEFAULT_MAX_VERTICES = 200
_SIMPLIFICATION_SAFETY_FACTOR = 0.5
_MAX_SIMPLIFICATION_ATTEMPTS = 8


def _local_utm_crs(latitude: float, longitude: float) -> CRS:
    """Choose a local UTM CRS for metre-accurate buffering."""
    zone = int((longitude + 180) // 6) + 1
    epsg = (32600 if latitude >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def _project_to_utm(geometry: BaseGeometry, crs: CRS) -> BaseGeometry:
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return shapely_ops_transform(transformer.transform, geometry)


def _project_to_wgs84(geometry: BaseGeometry, crs: CRS) -> BaseGeometry:
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return shapely_ops_transform(transformer.transform, geometry)


def _polygon_vertex_count(geometry: BaseGeometry) -> int:
    if isinstance(geometry, Polygon):
        return len(geometry.exterior.coords)
    if hasattr(geometry, "geoms"):
        return sum(len(g.exterior.coords) for g in geometry.geoms if isinstance(g, Polygon))
    return 0


def build_route_corridor_polygon(
    route: Sequence[tuple[float, float]],
    *,
    buffer_m: float = _DEFAULT_BUFFER_M,
    max_vertices: int = _DEFAULT_MAX_VERTICES,
    use_bounding_box: bool = False,
) -> BaseGeometry:
    """Buffer a route polyline into a corridor or bounding-box polygon for ``polygon_aoi``.

    Parameters
    ----------
    route:
        Sequence of ``(latitude, longitude)`` coordinate pairs along the route.
    buffer_m:
        Half-width of the corridor buffer in metres (default 25 m).
    max_vertices:
        Hard upper bound on polygon vertex count.  If the buffered polygon
        exceeds this, Douglas-Peucker simplification is applied with
        increasing tolerance (up to ``_MAX_SIMPLIFICATION_ATTEMPTS`` rounds).
    use_bounding_box:
        If True, buffers the route's full rectangular envelope instead of a thin
        corridor polyline, ensuring complete tile grid coverage from FortyGuard.

    Raises
    ------
    ValueError
        If the polygon cannot be simplified to ``max_vertices`` within the
        bounded number of attempts.

    Returns
    -------
    A Shapely Polygon in WGS 84 (lng, lat) order, ready for GeoJSON export.
    """
    if len(route) < 2:
        raise ValueError("route must contain at least two coordinate pairs")
    if buffer_m <= 0:
        raise ValueError("buffer_m must be positive")
    if max_vertices < 4:
        raise ValueError("max_vertices must be at least 4 for a valid polygon")

    # LineString expects (x, y) = (lng, lat)
    line = LineString([(lng, lat) for lat, lng in route])
    centroid = line.centroid
    crs = _local_utm_crs(centroid.y, centroid.x)

    projected = _project_to_utm(line, crs)
    base_geom = projected.envelope if use_bounding_box else projected
    buffered = base_geom.buffer(
        buffer_m,
        cap_style="square" if use_bounding_box else "round",
        join_style="mitre" if use_bounding_box else "round",
    )

    # Simplify with increasing tolerance until vertex count is within the hard limit.
    tolerance = buffer_m * _SIMPLIFICATION_SAFETY_FACTOR
    for _ in range(_MAX_SIMPLIFICATION_ATTEMPTS):
        if _polygon_vertex_count(buffered) <= max_vertices:
            break
        buffered = buffered.simplify(tolerance, preserve_topology=True)
        tolerance *= 2.0
    else:
        count = _polygon_vertex_count(buffered)
        if count > max_vertices:
            raise ValueError(
                f"cannot simplify corridor polygon to {max_vertices} vertices "
                f"after {_MAX_SIMPLIFICATION_ATTEMPTS} attempts "
                f"(got {count})"
            )

    corridor = _project_to_wgs84(buffered, crs)
    if not corridor.is_valid:
        corridor = corridor.buffer(0)
    return corridor


def _geometry_to_feature_collection(geometry: BaseGeometry) -> dict[str, object]:
    """Wrap a Shapely geometry in the same FeatureCollection structure used by the point path."""
    geojson = shapely_mapping(geometry)
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": dict(geojson)}],
    }


def build_documented_area_heatmap_payload(
    route: Sequence[tuple[float, float]],
    *,
    analytic_type: AnalyticType,
    start_date: date,
    forecast: bool = True,
    threshold_celsius: float | None = None,
    direction: str | None = None,
    granularity: int = _DEFAULT_AREA_GRANULARITY,
    buffer_m: float = _DEFAULT_BUFFER_M,
    max_vertices: int = _DEFAULT_MAX_VERTICES,
    use_bounding_box: bool = False,
    today: date | None = None,
) -> dict[str, object]:
    """Build the documented live ``polygon_aoi`` payload for a route corridor.

    Parallel to ``build_documented_heatmap_payload`` for point requests but
    constructs the AOI from a buffered route polyline instead of a single-point
    expansion.  Date/forecast validation reuses the shape-independent rules.
    Granularity defaults to 100 m for area requests (ADR 0001).
    """
    current = date.today() if today is None else today
    _validate_documented_window(start_date=start_date, forecast=forecast, today=current)

    corridor = build_route_corridor_polygon(
        route,
        buffer_m=buffer_m,
        max_vertices=max_vertices,
        use_bounding_box=use_bounding_box,
    )
    payload: dict[str, object] = {
        "polygon_aoi": _geometry_to_feature_collection(corridor),
        "date_time": {"start_date": start_date.isoformat(), "filter_type": 3},
        "granularity": granularity,
        "analytic_type": analytic_type.value,
    }
    if threshold_celsius is not None:
        payload["threshold"] = threshold_celsius
    if direction is not None:
        payload["direction"] = direction
    return payload


def build_documented_shared_route_heat_payload(
    request: SharedRouteHeatRequest, *, today: date | None = None
) -> dict[str, object]:
    """Build one selected-hour TCM payload for a shared returned-route AOI."""
    current = date.today() if today is None else today
    _validate_documented_window(
        start_date=request.start_date, forecast=request.forecast, today=current
    )
    return {
        "polygon_aoi": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": dict(request.geometry),
                }
            ],
        },
        "date_time": {
            "start_date": request.start_date.isoformat(),
            "filter_type": 1,
            "start_time": f"{request.hour:02d}:00",
        },
        "granularity": request.granularity,
        "analytic_type": AnalyticType.TCM.value,
    }


def shared_route_request_transformations() -> tuple[Transformation, ...]:
    """Inference stamps for one selected-hour, multi-route bounding AOI."""
    return (
        Transformation("live_envelope_unwrapped", 1),
        Transformation("multi_route_bounding_aoi", 1),
        Transformation("valid_time_from_request", 2),
        Transformation("tcm_unit_celsius", 1),
    )


def area_request_transformations(analytic_type: AnalyticType) -> tuple[Transformation, ...]:
    """The inference stamps every live area heatmap result carries (ADR 0002).

    ``valid_time_from_request`` stays version 1 here: area requests submit no
    hour window (always ``filter_type`` 3), so the tile valid time is still
    midnight derived from the request date alone.
    """
    stamps = [
        Transformation("live_envelope_unwrapped", 1),
        Transformation("route_to_aoi_buffer", 1),
        Transformation("valid_time_from_request", 1),
    ]
    if analytic_type is AnalyticType.TCM:
        stamps.append(Transformation("tcm_unit_celsius", 1))
    return tuple(stamps)


class LiveSharedRouteHeatAdapter:
    """Submits exactly one selected-hour heat activity for a shared route AOI."""

    def __init__(
        self,
        client: FortyGuardClient,
        *,
        today: Callable[[], date] = date.today,
        polling: FortyGuardPollingSettings | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._client = client
        self._today = today
        self._polling = polling or FortyGuardPollingSettings()
        self._sleep = sleep

    def load(self, request: SharedRouteHeatRequest) -> LiveHeatmapPayload:
        payload = build_documented_shared_route_heat_payload(request, today=self._today())
        result, metadata = self._client.submit_and_poll(
            "/v1/heatmap",
            payload,
            sleep=self._sleep or default_sleep,
            max_polls=self._polling.max_polls,
            interval_seconds=self._polling.interval_seconds,
            status_404_grace_checks=self._polling.status_404_grace_checks,
        )
        centroid = shape(dict(request.geometry)).centroid
        translation_request = HeatmapRequest(
            analytic_type=AnalyticType.TCM,
            latitude=centroid.y,
            longitude=centroid.x,
            start_date=request.start_date,
            forecast=request.forecast,
            granularity=request.granularity,
            start_hour=request.hour,
            end_hour=request.hour + 1,
        )
        translated = translate_heatmap_response(result, request=translation_request)
        return LiveHeatmapPayload(
            translated,
            metadata.activity_id,
            shared_route_request_transformations(),
            metadata,
        )


class LiveAreaHeatmapAdapter:
    """Owns the live area heatmap path: route buffering, documented payload, submission, and translation."""

    def __init__(
        self,
        client: FortyGuardClient,
        *,
        today: Callable[[], date] = date.today,
        polling: FortyGuardPollingSettings | None = None,
        sleep: Callable[[float], None] | None = None,
        buffer_m: float = _DEFAULT_BUFFER_M,
        max_vertices: int = _DEFAULT_MAX_VERTICES,
        use_bounding_box: bool = False,
    ) -> None:
        self._client = client
        self._today = today
        self._polling = polling or FortyGuardPollingSettings()
        self._sleep = sleep
        self._buffer_m = buffer_m
        self._max_vertices = max_vertices
        self._use_bounding_box = use_bounding_box

    def load(
        self,
        route: Sequence[tuple[float, float]],
        *,
        analytic_type: AnalyticType,
        start_date: date,
        forecast: bool = True,
        threshold_celsius: float | None = None,
        direction: str | None = None,
        granularity: int = _DEFAULT_AREA_GRANULARITY,
        use_bounding_box: bool | None = None,
    ) -> LiveHeatmapPayload:
        bbox_setting = self._use_bounding_box if use_bounding_box is None else use_bounding_box
        payload = build_documented_area_heatmap_payload(
            route,
            analytic_type=analytic_type,
            start_date=start_date,
            forecast=forecast,
            threshold_celsius=threshold_celsius,
            direction=direction,
            granularity=granularity,
            buffer_m=self._buffer_m,
            max_vertices=self._max_vertices,
            use_bounding_box=bbox_setting,
            today=self._today(),
        )
        result, metadata = self._client.submit_and_poll(
            "/v1/heatmap",
            payload,
            sleep=self._sleep or default_sleep,
            max_polls=self._polling.max_polls,
            interval_seconds=self._polling.interval_seconds,
            status_404_grace_checks=self._polling.status_404_grace_checks,
        )
        # Build a temporary HeatmapRequest for translate_heatmap_response
        # which needs a request to determine mode, analytic type, etc.
        mid = route[len(route) // 2]
        request_for_translation = HeatmapRequest(
            analytic_type=analytic_type,
            latitude=mid[0],
            longitude=mid[1],
            start_date=start_date,
            forecast=forecast,
            threshold_celsius=threshold_celsius,
            direction=direction,
            granularity=granularity,
        )
        translated = translate_heatmap_response(result, request=request_for_translation)
        return LiveHeatmapPayload(
            translated,
            metadata.activity_id,
            area_request_transformations(analytic_type),
        )


# --- Route-to-tile segment mapping (consumer-side aggregation) --- #


@dataclass(frozen=True)
class RouteSegmentHeat:
    """Heat metric for one segment of a route, derived from tile overlap."""

    segment_index: int
    start: tuple[float, float]
    end: tuple[float, float]
    value: float | None
    coverage: float
    tile_count: int


def map_tiles_to_route_segments(
    route: Sequence[tuple[float, float]],
    tiles: Sequence[dict[str, object]],
    *,
    buffer_m: float = _DEFAULT_BUFFER_M,
) -> list[RouteSegmentHeat]:
    """Map heatmap tiles back to route segments for corridor analysis.

    For each consecutive pair of route points, builds a small buffered segment
    corridor in a projected CRS, intersects it with each tile's geometry, and
    computes an area-weighted average temperature/metric value.  Returns a list
    of per-segment results that the consumer can use to compute corridor-level
    summaries (e.g., "% of route above 35 °C").

    This function lives in the adapter module (not ``analysis.py``) because it
    operates on the raw translated tile dictionaries from the provider response,
    not on normalized ``Tile`` dataclasses.
    """
    from shapely.geometry import shape

    if len(route) < 2:
        raise ValueError("route must contain at least two points")

    segments: list[RouteSegmentHeat] = []
    mid = route[len(route) // 2]
    crs = _local_utm_crs(mid[0], mid[1])

    # Pre-project tile geometries
    projected_tiles: list[tuple[BaseGeometry, float]] = []
    for tile in tiles:
        props = tile.get("properties")
        geom = tile.get("geometry")
        if not isinstance(props, dict) or not isinstance(geom, dict):
            continue
        value = props.get("value")
        if not isinstance(value, (int, float)):
            continue
        tile_geom = shape(geom)
        if tile_geom.is_valid and not tile_geom.is_empty:
            projected_tiles.append((_project_to_utm(tile_geom, crs), float(value)))

    for i in range(len(route) - 1):
        start_pt = route[i]
        end_pt = route[i + 1]
        segment_line = LineString([(start_pt[1], start_pt[0]), (end_pt[1], end_pt[0])])
        projected_segment = _project_to_utm(segment_line, crs).buffer(buffer_m)

        segment_area = projected_segment.area
        weighted_sum = 0.0
        overlap_area = 0.0
        tile_count = 0

        for proj_tile_geom, tile_value in projected_tiles:
            intersection = projected_segment.intersection(proj_tile_geom)
            if intersection.area > 0:
                weighted_sum += tile_value * intersection.area
                overlap_area += intersection.area
                tile_count += 1

        coverage = min(1.0, overlap_area / segment_area) if segment_area > 0 else 0.0
        avg_value = weighted_sum / overlap_area if overlap_area > 0 else None

        segments.append(
            RouteSegmentHeat(
                segment_index=i,
                start=start_pt,
                end=end_pt,
                value=avg_value,
                coverage=coverage,
                tile_count=tile_count,
            )
        )

    return segments


def build_documented_env_params_payload(request: EnvParamsRequest) -> dict[str, object]:
    """Build the documented /v1/env_params payload for a single-point series request.

    The complete documented parameter set is requested by default. The caller-supplied
    Celsius anchor is the documented ``temperature`` input. Parameters are kept
    provider-shaped so newly added fields are not silently discarded. An optional
    hour selects the single-hour filter; the default is the full-day series.
    Out-of-contract dates are rejected before any billable submission, matching
    the heatmap path (ADR 0001 §3). Env-params dates are validated as anchored
    observations: between 2019-01-01 and today.

    The filter mirrors the request it was built from: a single ``hour`` stays
    the single-hour filter (``filter_type`` 1), a traveler window
    (``start_hour``/``end_hour``) becomes the range filter (``filter_type`` 2
    with ``start_time``/``end_time``), and neither is the full-day series
    (``filter_type`` 3). The window and the chained heatmap request therefore
    always carry an identical ``date_time`` block (issue #44).
    """
    _validate_documented_date(request.start_date, today=date.today())
    if request.hour is not None:
        date_time: dict[str, object] = {
            "start_date": request.start_date.isoformat(),
            "filter_type": 1,
            "start_time": f"{request.hour:02d}:00",
        }
    else:
        date_time = _date_time_filter(start_date=request.start_date, window=request.window)
    return {
        "latitude": request.latitude,
        "longitude": request.longitude,
        "temperature": request.temperature_anchor_celsius,
        "date_time": date_time,
        "analysis": list(ENVIRONMENT_PARAMETERS),
    }


class LiveEnvParamsAdapter:
    """Owns the live environmental-parameters path."""

    def __init__(
        self,
        client: FortyGuardClient,
        *,
        polling: FortyGuardPollingSettings | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._client = client
        self._polling = polling or FortyGuardPollingSettings()
        self._sleep = sleep

    def load(self, request: EnvParamsRequest) -> LiveEnvParamsPayload:
        payload = build_documented_env_params_payload(request)
        result, metadata = self._client.submit_and_poll(
            "/v1/env_params",
            payload,
            sleep=self._sleep or default_sleep,
            max_polls=self._polling.max_polls,
            interval_seconds=self._polling.interval_seconds,
            status_404_grace_checks=self._polling.status_404_grace_checks,
            scope="enrichment",
        )
        return LiveEnvParamsPayload(result, metadata.activity_id, env_params_transformations())


class LiveSegmentationAdapter:
    """Submit documented segmentation requests while preserving opaque classes."""

    def __init__(self, client: FortyGuardClient, endpoint: str, polling: FortyGuardPollingSettings):
        self._client = client
        self._endpoint = endpoint
        self._polling = polling

    def enrich(
        self,
        context: object,
        request: Mapping[str, object],
    ) -> EnrichmentPayload:
        from app.domain.enrichment import EnrichmentContext

        if not isinstance(context, EnrichmentContext):
            raise ValueError("invalid enrichment context")
        if context.coordinates is None:
            raise ValueError("missing spatial input")
        if self._endpoint == "/v1/satellite":
            payload = {
                "sat": {
                    "latitude": context.coordinates.latitude,
                    "longitude": context.coordinates.longitude,
                },
                "date_time": {
                    "start_date": request.get("date", date.today().isoformat()),
                    "filter_type": 3,
                },
                "granularity": 80,
            }
        else:
            point_value = request.get("point")
            point: Mapping[str, object] = (
                point_value
                if isinstance(point_value, Mapping)
                else {
                    "latitude": context.coordinates.latitude,
                    "longitude": context.coordinates.longitude,
                }
            )
            payload = {**point, "vertical_angle": 10.0, "horizontal_angle": 0.0, "back_view": False}
        result, metadata = self._client.submit_and_poll(
            self._endpoint,
            payload,
            max_polls=self._polling.max_polls,
            interval_seconds=self._polling.interval_seconds,
            status_404_grace_checks=self._polling.status_404_grace_checks,
            scope="enrichment",
        )
        return EnrichmentPayload(
            {"provider_result": dict(result), "segmentation": True},
            metadata.activity_id,
            "provider",
            "completed",
        )
