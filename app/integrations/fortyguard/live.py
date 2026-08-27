"""Live FortyGuard adapter: documented payload construction, envelope handling, and translation.

This module is the only place that knows the documented live provider shapes
(ADR 0001). The neutral client, poller, and contracts modules stay untouched.
"""

from __future__ import annotations

from typing import Mapping

from app.integrations.fortyguard.errors import ProviderError, ProviderErrorKind
from app.integrations.fortyguard.transport import HttpFortyGuardTransport


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
            raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, detail="response data envelope must be an object")
        unwrapped: dict[str, object] = {key: value for key, value in parsed.items() if key != "data"}
        unwrapped.update(dict(data))
        return unwrapped
