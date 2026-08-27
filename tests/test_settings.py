from pathlib import Path

import pytest

from app.settings import (
    AppSettings,
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
