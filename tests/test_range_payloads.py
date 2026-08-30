"""Offline tests for the hour-range (filter_type 2) provider payloads (issue #44).

Both the heatmap and env-params requests grow an optional ``start_hour`` /
``end_hour`` window. When set, the documented provider payloads must carry
``filter_type: 2`` with identical ``start_date``, ``start_time``, and
``end_time`` for both requests, so the chained trip flow issues one billable
heatmap call and one billable env-params call over the exact window the
traveler selected. Existing full-day (filter 3) and single-hour (filter 1)
behaviour is preserved.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, cast

import pytest

from app.domain.environment import MAX_WINDOW_HOURS, select_anchor_celsius
from app.integrations.fortyguard.contracts import (
    AnalyticType,
    EnvParamsRequest,
    HeatmapRequest,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.errors import ProviderError, ProviderErrorKind
from app.integrations.fortyguard.live import (
    build_documented_env_params_payload,
    build_documented_heatmap_payload,
    translate_heatmap_response,
)
from app.services.execution import env_params_request_payload, heatmap_request_payload


def _raw_tcm_map_data() -> dict[str, object]:
    """A completed live tcm result: the provider stamps no per-feature time."""
    return {
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-98.5, 29.4],
                                [-98.4, 29.4],
                                [-98.4, 29.5],
                                [-98.5, 29.5],
                                [-98.5, 29.4],
                            ]
                        ],
                    },
                    "properties": {
                        "average_temperature": 36.5,
                        "min_temperature": 28.1,
                        "max_temperature": 41.2,
                    },
                }
            ],
        },
        "stats_data": {"units": "celsius", "analytic_type": "tcm"},
    }


def _tcm_request(**overrides: object) -> HeatmapRequest:
    defaults: dict[str, object] = {
        "analytic_type": AnalyticType.TCM,
        "latitude": 29.4241,
        "longitude": -98.4936,
        "start_date": date.today(),
        "forecast": True,
    }
    defaults.update(overrides)
    return HeatmapRequest(**defaults)  # type: ignore[arg-type]


def _env_request(**overrides: object) -> EnvParamsRequest:
    defaults: dict[str, object] = {
        "latitude": 29.4241,
        "longitude": -98.4936,
        "start_date": date(2026, 8, 24),
        "temperature_anchor_celsius": 35.0,
    }
    defaults.update(overrides)
    return EnvParamsRequest(**defaults)  # type: ignore[arg-type]


# --- HeatmapRequest window fields --- #


class TestHeatmapRequestWindow:
    def test_accepts_a_valid_window(self) -> None:
        request = _tcm_request(start_hour=8, end_hour=20)
        assert request.start_hour == 8
        assert request.end_hour == 20

    def test_window_may_span_exactly_twelve_hours(self) -> None:
        request = _tcm_request(start_hour=10, end_hour=10 + MAX_WINDOW_HOURS)
        assert request.hours is not None

    def test_rejects_only_one_bound_set(self) -> None:
        with pytest.raises(ValueError, match="together"):
            _tcm_request(start_hour=8)
        with pytest.raises(ValueError, match="together"):
            _tcm_request(end_hour=20)

    def test_rejects_window_longer_than_twelve_hours(self) -> None:
        with pytest.raises(ValueError, match="at most 12 hours"):
            _tcm_request(start_hour=0, end_hour=13)

    def test_rejects_start_not_before_end(self) -> None:
        with pytest.raises(ValueError, match="before end_hour"):
            _tcm_request(start_hour=9, end_hour=9)
        with pytest.raises(ValueError, match="before end_hour"):
            _tcm_request(start_hour=10, end_hour=9)

    def test_rejects_non_whole_hour_bounds(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 23"):
            _tcm_request(start_hour=-1, end_hour=20)
        with pytest.raises(ValueError, match="between 0 and 23"):
            _tcm_request(start_hour=8, end_hour=24)
        with pytest.raises(ValueError, match="between 0 and 23"):
            _tcm_request(start_hour=8.0, end_hour=20)
        with pytest.raises(ValueError, match="between 0 and 23"):
            _tcm_request(start_hour=True, end_hour=20)


# --- EnvParamsRequest window fields --- #


class TestEnvParamsRequestWindow:
    def test_accepts_a_valid_window(self) -> None:
        request = _env_request(start_hour=8, end_hour=20)
        assert request.start_hour == 8
        assert request.end_hour == 20

    def test_rejects_only_one_bound_set(self) -> None:
        with pytest.raises(ValueError, match="together"):
            _env_request(start_hour=8)
        with pytest.raises(ValueError, match="together"):
            _env_request(end_hour=20)

    def test_rejects_window_longer_than_twelve_hours(self) -> None:
        with pytest.raises(ValueError, match="at most 12 hours"):
            _env_request(start_hour=0, end_hour=13)

    def test_rejects_start_not_before_end(self) -> None:
        with pytest.raises(ValueError, match="before end_hour"):
            _env_request(start_hour=9, end_hour=9)

    def test_rejects_non_whole_hour_bounds(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 23"):
            _env_request(start_hour=8, end_hour="20")


# --- Documented heatmap payload: filter_type 2 --- #


class TestHeatmapRangePayload:
    def test_range_request_emits_filter_type_two_with_window(self) -> None:
        payload = build_documented_heatmap_payload(
            _tcm_request(start_hour=8, end_hour=20), today=date.today()
        )
        assert payload["date_time"] == {
            "start_date": date.today().isoformat(),
            "filter_type": 2,
            "start_time": "08:00",
            "end_time": "19:00",
        }

    def test_full_day_request_still_emits_filter_type_three(self) -> None:
        payload = build_documented_heatmap_payload(_tcm_request(), today=date.today())
        assert payload["date_time"] == {"start_date": date.today().isoformat(), "filter_type": 3}

    def test_one_hour_window_emits_the_documented_single_hour_filter(self) -> None:
        """A one-hour window is filter 1, not a range whose bounds are equal.

        The provider range is inclusive, so rendering a one-hour window as
        ``filter_type: 2`` would submit ``start_time == end_time`` — an
        undocumented degenerate range the provider rejects at submission. The
        per-hour heat fan-out sends nothing but one-hour windows.
        """
        payload = build_documented_heatmap_payload(
            _tcm_request(start_hour=8, end_hour=9), today=date.today()
        )
        assert payload["date_time"] == {
            "start_date": date.today().isoformat(),
            "filter_type": 1,
            "start_time": "08:00",
        }

    def test_two_hour_window_is_still_a_range(self) -> None:
        payload = build_documented_heatmap_payload(
            _tcm_request(start_hour=8, end_hour=10), today=date.today()
        )
        assert payload["date_time"] == {
            "start_date": date.today().isoformat(),
            "filter_type": 2,
            "start_time": "08:00",
            "end_time": "09:00",
        }

    def test_one_hour_window_keeps_heatmap_and_env_params_identical(self) -> None:
        """Issue #44's invariant survives the single-hour collapse."""
        heatmap = build_documented_heatmap_payload(
            _historical_tcm_request(start_date=date(2026, 8, 24), start_hour=8, end_hour=9),
            today=date.today(),
        )
        env_params = build_documented_env_params_payload(_env_request(start_hour=8, end_hour=9))
        assert heatmap["date_time"] == env_params["date_time"]

    def test_historical_range_request_is_valid(self) -> None:
        request = _historical_tcm_request(start_hour=8, end_hour=20)
        payload = build_documented_heatmap_payload(request, today=date.today())
        date_time = cast("dict[str, object]", payload["date_time"])
        assert date_time["filter_type"] == 2

    def test_range_forecast_beyond_documented_window_rejected(self) -> None:
        request = _tcm_request(
            start_date=date.today() + timedelta(days=1), start_hour=8, end_hour=20
        )
        with pytest.raises(ProviderError) as error:
            build_documented_heatmap_payload(request, today=date.today())
        assert error.value.kind is ProviderErrorKind.VALIDATION


def _historical_tcm_request(**overrides: object) -> HeatmapRequest:
    defaults: dict[str, object] = {
        "analytic_type": AnalyticType.TCM,
        "latitude": 29.4241,
        "longitude": -98.4936,
        "start_date": date(2026, 8, 20),
        "forecast": False,
        "start_hour": 8,
        "end_hour": 20,
    }
    defaults.update(overrides)
    return HeatmapRequest(**defaults)  # type: ignore[arg-type]


# --- Documented env-params payload: filter_type 2 --- #


class TestEnvParamsRangePayload:
    def test_range_request_emits_filter_type_two_with_window(self) -> None:
        payload = build_documented_env_params_payload(_env_request(start_hour=8, end_hour=20))
        assert payload["date_time"] == {
            "start_date": "2026-08-24",
            "filter_type": 2,
            "start_time": "08:00",
            "end_time": "19:00",
        }

    def test_inclusive_range_asks_for_exactly_the_in_window_hours(self) -> None:
        """The provider range is inclusive, so the bounds must be in-window hours.

        A live call for 08:00-14:00 returned seven hourly readings. Sending the
        exclusive ``end_hour`` would bill for one hour the traveler is not
        present for and hand the series an entry ``contains_hour`` rejects.
        """
        request = _env_request(start_hour=8, end_hour=20)
        window = request.window
        assert window is not None
        date_time = cast(
            "dict[str, str]", build_documented_env_params_payload(request)["date_time"]
        )

        first = int(date_time["start_time"][:2])
        last = int(date_time["end_time"][:2])
        assert [*range(first, last + 1)] == [*window.hours]
        assert last - first + 1 <= MAX_WINDOW_HOURS

    def test_full_day_request_still_emits_filter_type_three(self) -> None:
        payload = build_documented_env_params_payload(_env_request())
        assert payload["date_time"] == {"start_date": "2026-08-24", "filter_type": 3}

    def test_single_hour_request_still_emits_filter_type_one(self) -> None:
        payload = build_documented_env_params_payload(_env_request(hour=13))
        assert payload["date_time"] == {
            "start_date": "2026-08-24",
            "filter_type": 1,
            "start_time": "13:00",
        }

    def test_range_and_hour_are_mutually_exclusive(self) -> None:
        with pytest.raises(ValueError, match="together"):
            _env_request(start_hour=8, end_hour=20, hour=13)


# --- Request identity for cache keys and fixture matching --- #


class TestRequestIdentityPayloads:
    def test_heatmap_identity_includes_the_window(self) -> None:
        identity = heatmap_request_payload(_tcm_request(start_hour=8, end_hour=20))
        assert identity["start_hour"] == 8
        assert identity["end_hour"] == 20

    def test_heatmap_identity_without_window_omits_window_fields(self) -> None:
        identity = heatmap_request_payload(_tcm_request())
        assert "start_hour" not in identity
        assert "end_hour" not in identity

    def test_env_params_identity_includes_the_window(self) -> None:
        identity = env_params_request_payload(_env_request(start_hour=8, end_hour=20))
        assert identity["start_hour"] == 8
        assert identity["end_hour"] == 20

    def test_env_params_identity_without_window_omits_window_fields(self) -> None:
        identity = env_params_request_payload(_env_request())
        assert "start_hour" not in identity
        assert "end_hour" not in identity


# --- Translated tile timestamps: the anchor contract --- #


class TestWindowedTileValidTime:
    """A windowed request must produce tiles the anchor policy accepts.

    The provider echoes no per-feature timestamp, so the translator stamps one
    from the request. Stamping midnight put every tile outside the traveler
    window, which made ``select_anchor_celsius`` reject live readings for any
    daytime window and reported the trip as ``unavailable``.
    """

    def test_range_request_stamps_tiles_with_the_window_start_hour(self) -> None:
        request = _tcm_request(start_hour=8, end_hour=14)
        translated = translate_heatmap_response(_raw_tcm_map_data(), request=request)
        feature = cast(list[dict[str, Any]], translated["features"])[0]
        properties = cast(dict[str, Any], feature["properties"])
        assert properties["valid_time"] == f"{date.today().isoformat()}T08:00:00+00:00"

    def test_full_day_request_still_stamps_midnight(self) -> None:
        translated = translate_heatmap_response(_raw_tcm_map_data(), request=_tcm_request())
        feature = cast(list[dict[str, Any]], translated["features"])[0]
        properties = cast(dict[str, Any], feature["properties"])
        assert properties["valid_time"] == f"{date.today().isoformat()}T00:00:00+00:00"

    def test_windowed_tiles_anchor_inside_the_traveler_window(self) -> None:
        request = _tcm_request(start_hour=8, end_hour=14)
        window = request.window
        assert window is not None
        result = normalize_heatmap_response(
            translate_heatmap_response(_raw_tcm_map_data(), request=request),
            request=request,
            retrieved_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )
        assert select_anchor_celsius(result.tiles, window) == 36.5

    def test_late_window_also_anchors(self) -> None:
        request = _tcm_request(start_hour=15, end_hour=21)
        window = request.window
        assert window is not None
        result = normalize_heatmap_response(
            translate_heatmap_response(_raw_tcm_map_data(), request=request),
            request=request,
            retrieved_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )
        assert select_anchor_celsius(result.tiles, window) == 36.5
