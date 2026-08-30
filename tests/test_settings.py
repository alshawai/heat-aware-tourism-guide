from pathlib import Path

import pytest

from app.settings import (
    AppSettings,
    FortyGuardAreaSettings,
    FortyGuardPollingSettings,
    OverpassSettings,
    ShadeSettings,
    SettingsError,
    load_settings,
)


def test_load_settings_reads_core_configuration_from_environment() -> None:
    settings = load_settings(
        environ={
            "ALLOW_LIVE": "true",
            "FORTYGUARD_API_KEY": "key-123",
            "FORTYGUARD_BASE_URL": "https://example.test",
        }
    )
    assert settings == AppSettings(
        allow_live=True,
        fortyguard_api_key="key-123",
        fortyguard_base_url="https://example.test",
        polling=FortyGuardPollingSettings(),
        area=FortyGuardAreaSettings(),
        overpass=OverpassSettings(),
    )


def test_load_settings_defaults_to_fixture_mode_and_documented_base_url() -> None:
    settings = load_settings(environ={})
    assert settings.allow_live is False
    assert settings.fortyguard_api_key is None
    assert settings.fortyguard_base_url == "https://api.fortyguard.com"


def test_process_environment_overrides_env_file_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ALLOW_LIVE=false\nFORTYGUARD_API_KEY=file-key\nFORTYGUARD_BASE_URL=https://file.example\n",
        encoding="utf-8",
    )
    settings = load_settings(
        environ={"FORTYGUARD_API_KEY": "process-key"},
        env_file=env_file,
    )
    assert settings.fortyguard_api_key == "process-key"
    assert settings.allow_live is False
    assert settings.fortyguard_base_url == "https://file.example"


def test_env_file_values_fill_unset_environment(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment line\n"
        "ALLOW_LIVE=true\n"
        'FORTYGUARD_API_KEY="quoted-key"\n'
        "\n"
        "NOT_RELEVANT=ignored\n",
        encoding="utf-8",
    )
    settings = load_settings(environ={}, env_file=env_file)
    assert settings.allow_live is True
    assert settings.fortyguard_api_key == "quoted-key"


def test_missing_env_file_is_skipped_silently(tmp_path: Path) -> None:
    settings = load_settings(environ={}, env_file=tmp_path / "absent.env")
    assert settings.allow_live is False


def test_allow_live_without_api_key_fails_fast() -> None:
    with pytest.raises(SettingsError, match="FORTYGUARD_API_KEY"):
        load_settings(environ={"ALLOW_LIVE": "true"})


def test_allow_live_with_blank_api_key_fails_fast() -> None:
    with pytest.raises(SettingsError, match="FORTYGUARD_API_KEY"):
        load_settings(environ={"ALLOW_LIVE": "true", "FORTYGUARD_API_KEY": "   "})


def test_invalid_allow_live_value_is_rejected() -> None:
    with pytest.raises(SettingsError, match="ALLOW_LIVE"):
        load_settings(environ={"ALLOW_LIVE": "yes"})


def test_polling_defaults_are_bounded() -> None:
    polling = FortyGuardPollingSettings()
    assert polling.interval_seconds == 5.0
    assert polling.max_polls == 24
    assert polling.timeout_seconds == 30.0
    assert polling.status_404_grace_checks == 3


def test_polling_bounds_are_overridable() -> None:
    polling = FortyGuardPollingSettings(
        interval_seconds=1.0, max_polls=3, timeout_seconds=5.0, status_404_grace_checks=1
    )
    assert polling == FortyGuardPollingSettings(1.0, 3, 5.0, 1)


def test_polling_overrides_are_read_from_environment() -> None:
    settings = load_settings(
        environ={
            "FORTYGUARD_POLL_INTERVAL_SECONDS": "2.5",
            "FORTYGUARD_MAX_POLLS": "9",
            "FORTYGUARD_TIMEOUT_SECONDS": "12.0",
            "FORTYGUARD_404_GRACE_CHECKS": "2",
        }
    )
    assert settings.polling == FortyGuardPollingSettings(
        interval_seconds=2.5, max_polls=9, timeout_seconds=12.0, status_404_grace_checks=2
    )


def test_invalid_polling_overrides_are_rejected() -> None:
    with pytest.raises(SettingsError, match="FORTYGUARD_MAX_POLLS"):
        load_settings(environ={"FORTYGUARD_MAX_POLLS": "0"})
    with pytest.raises(SettingsError, match="FORTYGUARD_POLL_INTERVAL_SECONDS"):
        load_settings(environ={"FORTYGUARD_POLL_INTERVAL_SECONDS": "fast"})


def test_empty_process_environment_value_still_overrides_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FORTYGUARD_API_KEY=file-key\nALLOW_LIVE=true\n", encoding="utf-8")
    settings = load_settings(
        environ={"FORTYGUARD_API_KEY": "", "ALLOW_LIVE": ""}, env_file=env_file
    )
    assert settings.fortyguard_api_key is None
    assert settings.allow_live is False


def test_area_settings_overrides_are_read_from_environment() -> None:
    settings = load_settings(
        environ={
            "FORTYGUARD_AREA_BUFFER_M": "50.0",
            "FORTYGUARD_AREA_GRANULARITY": "80",
            "FORTYGUARD_AREA_USE_BOUNDING_BOX": "false",
            "FORTYGUARD_AREA_MAX_VERTICES": "150",
        }
    )
    assert settings.area == FortyGuardAreaSettings(
        buffer_m=50.0,
        granularity=80,
        use_bounding_box=False,
        max_vertices=150,
    )


def test_overpass_defaults_are_bounded_and_use_configured_district() -> None:
    settings = load_settings(environ={}).overpass
    assert settings.endpoint == "https://overpass-api.de/api/interpreter"
    assert "contact" in settings.user_agent.lower()
    assert settings.timeout_seconds == 30.0
    assert settings.max_attempts == 2
    assert settings.retry_delay_seconds == 30.0
    assert settings.district_aoi.to_payload() == {
        "south": 29.421,
        "west": -98.49,
        "north": 29.429,
        "east": -98.482,
    }


def test_overpass_bounds_and_request_policy_are_configurable() -> None:
    settings = load_settings(
        environ={
            "OVERPASS_ENDPOINT": "https://overpass.example.test/interpreter",
            "OVERPASS_USER_AGENT": "Tour Guide/1.0 (contact: team@example.test)",
            "OVERPASS_TIMEOUT_SECONDS": "10",
            "OVERPASS_MAX_ATTEMPTS": "3",
            "OVERPASS_RETRY_DELAY_SECONDS": "4",
            "HOTEL_DISTRICT_BBOX": "29.4,-98.5,29.5,-98.4",
        }
    ).overpass
    assert settings == OverpassSettings(
        endpoint="https://overpass.example.test/interpreter",
        user_agent="Tour Guide/1.0 (contact: team@example.test)",
        timeout_seconds=10,
        max_attempts=3,
        retry_delay_seconds=4,
        district_aoi=settings.district_aoi,
    )
    assert settings.district_aoi.to_payload()["south"] == 29.4


def test_invalid_overpass_policy_or_district_bounds_are_rejected() -> None:
    with pytest.raises(SettingsError, match="OVERPASS_MAX_ATTEMPTS"):
        load_settings(environ={"OVERPASS_MAX_ATTEMPTS": "0"})
    with pytest.raises(SettingsError, match="OVERPASS_RETRY_DELAY_SECONDS"):
        load_settings(environ={"OVERPASS_RETRY_DELAY_SECONDS": "-1"})
    with pytest.raises(SettingsError, match="OVERPASS_RETRY_DELAY_SECONDS"):
        load_settings(environ={"OVERPASS_RETRY_DELAY_SECONDS": "inf"})
    with pytest.raises(SettingsError, match="HOTEL_DISTRICT_BBOX"):
        load_settings(environ={"HOTEL_DISTRICT_BBOX": "29.5,-98.5,29.4,-98.4"})


def test_shade_policy_defaults_and_overrides_are_validated() -> None:
    assert load_settings(environ={}).shade == ShadeSettings()
    settings = load_settings(
        environ={
            "SHADE_BUILDING_SEARCH_DISTANCE_M": "300",
            "SHADE_MINIMUM_BUILDING_HEIGHT_COVERAGE": "0.75",
            "SHADE_METRES_PER_LEVEL": "3.2",
            "TRIP_CANONICAL_TIMEZONE": "America/New_York",
        }
    ).shade
    assert settings.building_search_distance_m == 300.0
    assert settings.minimum_building_height_coverage == 0.75
    assert settings.metres_per_level == 3.2
    assert settings.canonical_timezone == "America/New_York"


def test_invalid_shade_policy_is_rejected() -> None:
    with pytest.raises(SettingsError, match="SHADE_BUILDING_SEARCH_DISTANCE_M"):
        load_settings(environ={"SHADE_BUILDING_SEARCH_DISTANCE_M": "0"})
    with pytest.raises(SettingsError, match="SHADE_MINIMUM_BUILDING_HEIGHT_COVERAGE"):
        load_settings(environ={"SHADE_MINIMUM_BUILDING_HEIGHT_COVERAGE": "1.1"})
    with pytest.raises(SettingsError, match="TRIP_CANONICAL_TIMEZONE"):
        load_settings(environ={"TRIP_CANONICAL_TIMEZONE": "Not/AZone"})


def test_call_budget_defaults_to_record_only_and_is_overridable() -> None:
    assert load_settings(environ={}).call_budget is None
    settings = load_settings(environ={"FORTYGUARD_CALL_BUDGET": "500"})
    assert settings.call_budget == 500


def test_invalid_call_budget_is_rejected() -> None:
    with pytest.raises(SettingsError, match="FORTYGUARD_CALL_BUDGET"):
        load_settings(environ={"FORTYGUARD_CALL_BUDGET": "-1"})
    with pytest.raises(SettingsError, match="FORTYGUARD_CALL_BUDGET"):
        load_settings(environ={"FORTYGUARD_CALL_BUDGET": "many"})


def test_ledger_path_defaults_to_data_ledger_and_empty_selects_memory(tmp_path: Path) -> None:
    assert load_settings(environ={}).ledger_path == Path("data/ledger.jsonl")
    env_file = tmp_path / ".env"
    env_file.write_text("FORTYGUARD_LEDGER_PATH=/tmp/custom.jsonl\n", encoding="utf-8")
    assert load_settings(environ={}, env_file=env_file).ledger_path == Path("/tmp/custom.jsonl")
    empty_process = load_settings(environ={"FORTYGUARD_LEDGER_PATH": ""}, env_file=env_file)
    assert empty_process.ledger_path is None
