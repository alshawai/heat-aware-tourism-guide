"""Provider error taxonomy and classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class ProviderErrorKind(str, Enum):
    AUTHENTICATION = "authentication"
    VALIDATION = "validation_or_plan"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    MALFORMED_RESPONSE = "malformed_response"
    TASK_FAILURE = "task_failure"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ProviderError(Exception):
    kind: ProviderErrorKind
    status_code: int | None = None
    detail: str = "provider request failed"

    def __str__(self) -> str:
        return f"{self.kind.value}: {self.detail}"


def _sanitize_detail(detail: str) -> str:
    detail = re.sub(
        r"(?i)(api[_ -]?key|authorization|token)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", detail
    )
    return detail[:160]


def classify_provider_error(status_code: int | None, detail: str = "") -> ProviderError:
    if status_code == 408:
        kind = ProviderErrorKind.TIMEOUT
    elif status_code in (401, 403):
        kind = ProviderErrorKind.AUTHENTICATION
    elif status_code in (400, 404, 422):
        kind = ProviderErrorKind.VALIDATION
    elif status_code == 429:
        kind = ProviderErrorKind.RATE_LIMIT
    elif status_code is not None and status_code >= 500:
        kind = ProviderErrorKind.SERVER
    else:
        kind = ProviderErrorKind.MALFORMED_RESPONSE
    return ProviderError(kind, status_code, _sanitize_detail(detail) or "provider request failed")
