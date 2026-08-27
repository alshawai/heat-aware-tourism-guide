"""Application settings loaded from the process environment and an optional .env file."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

DEFAULT_BASE_URL = "https://api.fortyguard.com"
DEFAULT_LEDGER_PATH = Path("data/ledger.jsonl")
_DEFAULT_ENV_FILE = Path(".env")


class SettingsError(RuntimeError):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class FortyGuardPollingSettings:
    """Bounded polling configuration (ADR 0003)."""

    interval_seconds: float = 5.0
    max_polls: int = 24
    timeout_seconds: float = 30.0
    status_404_grace_checks: int = 3


@dataclass(frozen=True)
class FortyGuardAreaSettings:
    """Area heatmap corridor configuration."""

    buffer_m: float = 25.0
    granularity: int = 100
    use_bounding_box: bool = True
    max_vertices: int = 200


@dataclass(frozen=True)
class AppSettings:
    allow_live: bool
    fortyguard_api_key: str | None
    fortyguard_base_url: str
    polling: FortyGuardPollingSettings = FortyGuardPollingSettings()
    area: FortyGuardAreaSettings = FortyGuardAreaSettings()
    call_budget: int | None = None
    ledger_path: Path | None = DEFAULT_LEDGER_PATH


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse a minimal KEY=VALUE env file; skip comments, blanks, and malformed lines."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _area_from_env(merged: Mapping[str, str]) -> FortyGuardAreaSettings:
    def positive_int(name: str, default: int) -> int:
        raw = merged.get(name, "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            raise SettingsError(f"{name} must be an integer") from None
        if value < 1:
            raise SettingsError(f"{name} must be a positive integer")
        return value

    def positive_float(name: str, default: float) -> float:
        raw = merged.get(name, "").strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            raise SettingsError(f"{name} must be a number") from None
        if not value > 0:
            raise SettingsError(f"{name} must be a positive number")
        return value

    bbox_raw = merged.get("FORTYGUARD_AREA_USE_BOUNDING_BOX", "true").strip().lower()
    if bbox_raw not in {"true", "false"}:
        raise SettingsError("FORTYGUARD_AREA_USE_BOUNDING_BOX must be true or false")

    return FortyGuardAreaSettings(
        buffer_m=positive_float("FORTYGUARD_AREA_BUFFER_M", 25.0),
        granularity=positive_int("FORTYGUARD_AREA_GRANULARITY", 100),
        use_bounding_box=(bbox_raw == "true"),
        max_vertices=positive_int("FORTYGUARD_AREA_MAX_VERTICES", 200),
    )


def _polling_from_env(merged: Mapping[str, str]) -> FortyGuardPollingSettings:
    def positive_int(name: str, default: int) -> int:
        raw = merged.get(name, "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            raise SettingsError(f"{name} must be an integer") from None
        if value < 1:
            raise SettingsError(f"{name} must be a positive integer")
        return value

    def positive_float(name: str, default: float) -> float:
        raw = merged.get(name, "").strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            raise SettingsError(f"{name} must be a number") from None
        if not value > 0:
            raise SettingsError(f"{name} must be a positive number")
        return value

    return FortyGuardPollingSettings(
        interval_seconds=positive_float("FORTYGUARD_POLL_INTERVAL_SECONDS", 5.0),
        max_polls=positive_int("FORTYGUARD_MAX_POLLS", 24),
        timeout_seconds=positive_float("FORTYGUARD_TIMEOUT_SECONDS", 30.0),
        status_404_grace_checks=positive_int("FORTYGUARD_404_GRACE_CHECKS", 3),
    )


def load_settings(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = None,
    polling: FortyGuardPollingSettings | None = None,
    area: FortyGuardAreaSettings | None = None,
) -> AppSettings:
    """Load settings; the process environment always wins over the .env file.

    The default `.env` file is consulted only when reading the real process
    environment (environ=None); an explicit environ mapping fully controls the
    inputs, which keeps tests isolated from local files.
    """
    process_env = dict(os.environ) if environ is None else dict(environ)
    if env_file is None and environ is None:
        env_file = _DEFAULT_ENV_FILE
    file_values = load_dotenv(env_file) if env_file is not None else {}
    # An explicitly set process variable overrides the env file even when empty:
    # an empty value unsets whatever the file provided.
    overrides = {key: value for key, value in process_env.items() if key in file_values or value != ""}
    merged = {key: value for key, value in {**file_values, **overrides}.items() if value != ""}
    allow_live_raw = merged.get("ALLOW_LIVE", "false").strip().lower()
    if allow_live_raw not in {"true", "false"}:
        raise SettingsError("ALLOW_LIVE must be true or false")
    allow_live = allow_live_raw == "true"
    api_key = merged.get("FORTYGUARD_API_KEY", "")
    if allow_live and not api_key.strip():
        raise SettingsError("ALLOW_LIVE=true requires FORTYGUARD_API_KEY to be set")
    base_url = merged.get("FORTYGUARD_BASE_URL", "").strip() or DEFAULT_BASE_URL
    return AppSettings(
        allow_live=allow_live,
        fortyguard_api_key=api_key or None,
        fortyguard_base_url=base_url,
        polling=polling or _polling_from_env(merged),
        area=area or _area_from_env(merged),
        call_budget=_call_budget_from_env(merged),
        ledger_path=_ledger_path_from_env(process_env, file_values),
    )


def _call_budget_from_env(merged: Mapping[str, str]) -> int | None:
    raw = merged.get("FORTYGUARD_CALL_BUDGET", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError("FORTYGUARD_CALL_BUDGET must be an integer") from None
    if value < 0:
        raise SettingsError("FORTYGUARD_CALL_BUDGET must be non-negative")
    return value


def _ledger_path_from_env(
    process_env: Mapping[str, str], file_values: Mapping[str, str]
) -> Path | None:
    """Resolve the ledger path; an explicit empty value selects in-memory only."""
    key = "FORTYGUARD_LEDGER_PATH"
    if key not in process_env and key not in file_values:
        return DEFAULT_LEDGER_PATH
    raw = process_env.get(key, file_values.get(key, "")).strip()
    return Path(raw) if raw else None
