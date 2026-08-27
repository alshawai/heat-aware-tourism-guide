"""Shared sanitization policy for provider payloads and operational events."""

from __future__ import annotations

import re
from typing import Any, Mapping


def sanitize_payload(value: object) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]"
            if re.search(r"(?i)(api[_ -]?key|authorization|token)", str(key))
            else sanitize_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value
