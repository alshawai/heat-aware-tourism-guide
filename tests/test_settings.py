from pathlib import Path

import pytest

from app.settings import (
    AppSettings,
    FortyGuardAreaSettings,
    FortyGuardPollingSettings,
    SettingsError,
    load_settings,
)


def test_load_settings_reads_core_configuration_from_environment() -> None:
    settings = load_settings(
        environ={"ALLOW_LIVE": "true", "FORTYGUARD_API_KEY": "key-123", "FORTYGUARD_BASE_URL": "https://example.test"}
    )
    assert settings == AppSettings(
        allow_live=True,
        fortyguard_api_key="key-123",
        fortyguard_base_url="https://example.test",
        polling=FortyGuardPollingSettings(),
        area=FortyGuardAreaSettings(),
    )


def test_load_settings_defaults_to_fixture_mode_and_documented_base_url() -> None:
    settings = load_settings(environ={})
    assert settings.allow_live is False
    assert settings.fortyguard_api_key is None
    assert settings.fortyguard_base_url == "https://api.fortyguard.com"


def test_process_environment_overrides_env_file_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ALLOW_LIVE=false\n"
        "FORTYGUARD_API_KEY=file-key\n"
        "FORTYGUARD_BASE_URL=https://file.example\n",
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
    polling = FortyGuardPollingSettings(interval_seconds=1.0, max_polls=3, timeout_seconds=5.0, status_404_grace_checks=1)
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
    settings = load_settings(environ={"FORTYGUARD_API_KEY": "", "ALLOW_LIVE": ""}, env_file=env_file)
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



def test_credit_budget_defaults_to_record_only_and_is_overridable() -> None:

    assert load_settings(environ={}).credit_budget is None
    settings = load_settings(environ={"FORTYGUARD_CREDIT_BUDGET": "500"})
    assert settings.credit_budget == 500


def test_invalid_credit_budget_is_rejected() -> None:
    with pytest.raises(SettingsError, match="FORTYGUARD_CREDIT_BUDGET"):
        load_settings(environ={"FORTYGUARD_CREDIT_BUDGET": "-1"})
    with pytest.raises(SettingsError, match="FORTYGUARD_CREDIT_BUDGET"):
        load_settings(environ={"FORTYGUARD_CREDIT_BUDGET": "many"})


def test_ledger_path_defaults_to_data_ledger_and_empty_selects_memory(tmp_path: Path) -> None:
    assert load_settings(environ={}).ledger_path == Path("data/ledger.jsonl")
    env_file = tmp_path / ".env"
    env_file.write_text("FORTYGUARD_LEDGER_PATH=/tmp/custom.jsonl\n", encoding="utf-8")
    assert load_settings(environ={}, env_file=env_file).ledger_path == Path("/tmp/custom.jsonl")
    empty_process = load_settings(environ={"FORTYGUARD_LEDGER_PATH": ""}, env_file=env_file)
    assert empty_process.ledger_path is None
