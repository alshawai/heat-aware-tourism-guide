from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

import pytest

from app.integrations.fortyguard.contracts import (
    EnvParamsRequest,
    normalize_env_params_response,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REQUEST = EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 24), 35.0)


def _flat_payload() -> dict[str, Any]:
    return {
        "timestamp": "2026-08-24T13:00:00-07:00",
        "timezone": "GMT-7",
        "offset": -7,
        "interval": "1h",
        "count": 1,
        "heat_index_celsius": [33.2],
        "apparent_temperature_celsius": [40.5],
        "relative_humidity_percent": [21.5],
        "precipitation_mm": [0.0],
        "cloud_cover_octas": [8.0],
        "wet_bulb_temperature_celsius": [22.3],
    }


def _docs_payload() -> dict[str, Any]:
    return {
        "metadata": {
            "timezone": "America/Chicago",
            "timezone_offset_hours": -5,
            "time_range": {
                "start": "2026-08-24T13:00:00-05:00",
                "end": "2026-08-24T14:00:00-05:00",
                "interval": "1h",
                "count": 2,
            },
            "timestamps": ["2026-08-24T13:00:00-05:00", "2026-08-24T14:00:00-05:00"],
        },
        "locations": [
            {
                "lat": 29.4241,
                "lon": -98.4936,
                "elevation": 198,
                "temperature": 35.0,
                "parameters": {
                    "heat_index_celsius": [38.1, None],
                    "relative_humidity_percent": [55, -999],
                },
            }
        ],
    }


def test_documented_locations_shape_normalizes_to_series() -> None:
    result = normalize_env_params_response(_docs_payload(), request=REQUEST)
    assert len(result.entries) == 2
    assert result.entries[0].valid_time == datetime.fromisoformat("2026-08-24T13:00:00-05:00")
    assert result.entries[0].heat_index_celsius == 38.1
    assert result.entries[0].humidity_percent == 55
    assert result.entries[1].heat_index_celsius is None
    assert result.entries[1].humidity_percent is None
    assert result.timezone == "America/Chicago"
    assert result.forecast is False
    assert "not a real 24-hour forecast" in result.warning


def test_observed_flat_shape_normalizes_to_series() -> None:
    result = normalize_env_params_response(_flat_payload(), request=REQUEST)
    assert len(result.entries) == 1
    assert result.entries[0].valid_time == datetime.fromisoformat("2026-08-24T13:00:00-07:00")
    assert result.entries[0].heat_index_celsius == 33.2
    assert result.entries[0].humidity_percent == 21.5
    assert result.timezone == "GMT-7"
    assert result.forecast is False
    assert "not a real 24-hour forecast" in result.warning


def test_committed_fixture_normalizes_with_anchor_warning() -> None:
    payload = json.loads((FIXTURES / "env-params.json").read_text(encoding="utf-8"))
    result = normalize_env_params_response(payload, request=REQUEST)
    assert result.entries[0].heat_index_celsius == 33.2
    assert result.entries[0].humidity_percent == 21.5
    assert result.forecast is False
    assert "not a real 24-hour forecast" in result.warning


def test_null_and_legacy_missing_values_are_preserved_as_none() -> None:
    payload = _docs_payload()
    parameters = payload["locations"][0]["parameters"]
    parameters["heat_index_celsius"] = [None, 38.1]
    parameters["relative_humidity_percent"] = [-999, None]
    result = normalize_env_params_response(payload, request=REQUEST)
    assert result.entries[0].heat_index_celsius is None
    assert result.entries[0].humidity_percent is None
    assert result.entries[1].heat_index_celsius == 38.1
    assert result.entries[1].humidity_percent is None


def test_series_length_mismatch_is_rejected() -> None:
    payload = _docs_payload()
    payload["locations"][0]["parameters"]["heat_index_celsius"] = [38.1]
    with pytest.raises(ValueError, match="aligned"):
        normalize_env_params_response(payload, request=REQUEST)


def test_missing_timestamps_is_rejected_as_missing_freshness() -> None:
    payload = _docs_payload()
    del payload["metadata"]["timestamps"]
    with pytest.raises(ValueError, match="freshness"):
        normalize_env_params_response(payload, request=REQUEST)


def test_missing_timezone_is_rejected() -> None:
    payload = _docs_payload()
    del payload["metadata"]["timezone"]
    with pytest.raises(ValueError, match="timezone"):
        normalize_env_params_response(payload, request=REQUEST)


def test_empty_series_is_rejected() -> None:
    payload = _docs_payload()
    payload["metadata"]["timestamps"] = []
    payload["locations"][0]["parameters"]["heat_index_celsius"] = []
    payload["locations"][0]["parameters"]["relative_humidity_percent"] = []
    with pytest.raises(ValueError, match="no entries"):
        normalize_env_params_response(payload, request=REQUEST)


def test_response_claiming_real_forecast_is_rejected() -> None:
    payload = _flat_payload()
    payload["forecast"] = True
    with pytest.raises(ValueError, match="real forecast"):
        normalize_env_params_response(payload, request=REQUEST)


def test_multiple_locations_are_rejected_for_single_point_request() -> None:
    payload = _docs_payload()
    payload["locations"] = [payload["locations"][0], dict(payload["locations"][0])]
    with pytest.raises(ValueError, match="exactly one location"):
        normalize_env_params_response(payload, request=REQUEST)


def test_non_numeric_series_values_are_rejected() -> None:
    payload = _docs_payload()
    payload["locations"][0]["parameters"]["heat_index_celsius"] = [True, 38.1]
    with pytest.raises(ValueError, match="heat index"):
        normalize_env_params_response(payload, request=REQUEST)
    payload["locations"][0]["parameters"]["heat_index_celsius"] = ["hot", 38.1]
    with pytest.raises(ValueError, match="heat index"):
        normalize_env_params_response(payload, request=REQUEST)


def test_missing_series_fields_are_rejected() -> None:
    payload = _docs_payload()
    del payload["locations"][0]["parameters"]["relative_humidity_percent"]
    with pytest.raises(ValueError, match="humidity"):
        normalize_env_params_response(payload, request=REQUEST)


def test_request_accepts_optional_hour_and_defaults_to_full_day() -> None:
    full_day = EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 24), 35.0)
    assert full_day.hour is None
    assert "hour" not in full_day.to_payload()
    with pytest.raises(ValueError, match="hour"):
        EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 24), 35.0, hour=24)
    with pytest.raises(ValueError, match="hour"):
        EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 24), 35.0, hour=True)
    hourly = EnvParamsRequest(29.4241, -98.4936, date(2026, 8, 24), 35.0, hour=13)
    assert hourly.hour == 13
    assert hourly.to_payload()["hour"] == 13
