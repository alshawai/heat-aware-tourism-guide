"""Application settings loaded from the process environment and an optional .env file."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

DEFAULT_BASE_URL = "https://api.fortyguard.com"
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
class AppSettings:
    allow_live: bool
    fortyguard_api_key: str | None
    fortyguard_base_url: str
    polling: FortyGuardPollingSettings = FortyGuardPollingSettings()


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


def load_settings(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = None,
    polling: FortyGuardPollingSettings | None = None,
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
    merged = {**file_values, **{key: value for key, value in process_env.items() if value != ""}}
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
        polling=polling or FortyGuardPollingSettings(),
    )
