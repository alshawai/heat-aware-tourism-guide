"""Authenticated submit/poll client for asynchronous FortyGuard activities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from time import sleep as default_sleep
from typing import Callable, Mapping
from uuid import uuid4

from app.domain.ledger import CreditLedger, UsageRecord
from app.domain.security import sanitize_payload
from app.integrations.fortyguard.errors import (
    ProviderError,
    ProviderErrorKind,
    classify_provider_error,
)
from app.integrations.fortyguard.transport import FortyGuardTransport


@dataclass(frozen=True)
class ActivityMetadata:
    activity_id: str
    submitted_at: datetime
    endpoint: str
    request_fields: tuple[str, ...]
    status_transitions: tuple[str, ...] = ()
    response_metadata: Mapping[str, object] = field(default_factory=dict)


class FortyGuardClient:
    """Authenticated submit/poll boundary; billable work is submitted exactly once."""

    def __init__(
        self,
        transport: FortyGuardTransport,
        api_key: str,
        *,
        clock: Callable[[], datetime],
        event_sink: Callable[[Mapping[str, object]], None] | None = None,
        ledger: CreditLedger | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        self._transport = transport
        self._api_key = api_key
        self._clock = clock
        self._event_sink = event_sink
        self._ledger = ledger

    def submit_and_poll(
        self,
        endpoint: str,
        payload: Mapping[str, object],
        *,
        sleep: Callable[[float], None] = default_sleep,
        max_polls: int = 24,
        interval_seconds: float = 5.0,
        status_404_grace_checks: int = 3,
        scope: str = "core",
    ) -> tuple[Mapping[str, object], ActivityMetadata]:
        reservation: int | None = None
        submitted = False
        activity_id: str | None = None
        if self._ledger is not None:
            reservation = self._ledger.authorize(scope=scope, now=self._clock())
        try:
            response = self._transport.post(endpoint, payload, self._api_key)
            status_code = response.get("status_code")
            if isinstance(status_code, int) and status_code >= 400:
                raise classify_provider_error(status_code, "activity submission failed")
            # A successful POST is billable even if its response cannot be decoded.
            submitted = True
            candidate_activity_id = response.get("activity_id")
            activity_id = candidate_activity_id if isinstance(candidate_activity_id, str) else None
            if not isinstance(activity_id, str) or not activity_id:
                activity_id = f"unknown-{uuid4().hex}"
                raise ProviderError(
                    ProviderErrorKind.MALFORMED_RESPONSE, detail="missing activity id"
                )
            submitted_at = self._clock()
            self._emit(
                "fortyguard.submitted",
                {
                    "activity_id": activity_id,
                    "endpoint": endpoint,
                    "request": sanitize_payload(payload),
                },
            )
            transitions: list[str] = []

            def get_status(_: str) -> Mapping[str, object]:
                return self._transport.get(f"/v1/status/{activity_id}", self._api_key)

            result = poll_activity(
                activity_id,
                get_status=get_status,
                sleep=sleep,
                max_polls=max_polls,
                interval_seconds=interval_seconds,
                status_404_grace_checks=status_404_grace_checks,
                on_transition=transitions.append,
                on_event=self._emit,
            )
            metadata = ActivityMetadata(
                activity_id,
                submitted_at,
                endpoint,
                tuple(sorted(payload)),
                tuple(transitions),
                _response_metadata(result),
            )
            credits_used = result.get("credits_used")
            if credits_used is not None and (
                isinstance(credits_used, bool)
                or not isinstance(credits_used, int)
                or credits_used < 0
            ):
                raise ProviderError(
                    ProviderErrorKind.MALFORMED_RESPONSE, detail="invalid credit usage metadata"
                )
            if self._ledger is not None:
                # The call happened, so it is logged whether or not the provider
                # priced it. A silent provider means unknown cost, not zero cost
                # (ADR 0004 §5); credits are reconciled from the account endpoint.
                self._ledger.record(
                    UsageRecord(
                        activity_id, endpoint, credits_used, self._clock(), "completed", scope
                    ),
                    reservation=reservation,
                )
            self._emit(
                "fortyguard.completed", {"activity_id": activity_id, **_response_metadata(result)}
            )
            return result, metadata
        except Exception as error:
            if submitted and activity_id is not None and self._ledger is not None:
                self._ledger.record(
                    UsageRecord(activity_id, endpoint, None, self._clock(), "failed", scope),
                    reservation=reservation,
                )
                reservation = None
            if isinstance(error, ProviderError) and activity_id is not None:
                raise ProviderError(
                    error.kind,
                    error.status_code,
                    error.detail,
                    activity_id,
                ) from error
            raise
        finally:
            if reservation is not None and self._ledger is not None and not submitted:
                self._ledger.release_call(reservation)

    def _emit(self, event: str, fields: Mapping[str, object]) -> None:
        if self._event_sink is not None:
            self._event_sink({"event": event, "at": self._clock().isoformat(), **fields})


def poll_activity(
    activity_id: str,
    *,
    get_status: Callable[[str], Mapping[str, object]],
    sleep: Callable[[float], None] = default_sleep,
    max_polls: int = 24,
    interval_seconds: float = 5.0,
    status_404_grace_checks: int = 3,
    on_transition: Callable[[str], None] | None = None,
    on_event: Callable[[str, Mapping[str, object]], None] | None = None,
) -> Mapping[str, object]:
    """Poll one already-submitted billable activity with bounded status checks.

    Post-submit 404s are tolerated within the early grace window — the first
    ``status_404_grace_checks`` status checks, or until any non-404 status
    response is seen — because the provider documents activities as
    "temporarily unavailable immediately after submission". After the window a
    404 is terminal (the activity genuinely does not exist). 404s consume poll
    budget either way; the activity is never resubmitted (ADR 0003).
    """
    saw_non_404 = False
    for poll_number in range(1, max_polls + 1):
        response = get_status(activity_id)
        status_code = response.get("status_code")
        if status_code in (408, 429):
            saw_non_404 = True
            if on_transition is not None:
                on_transition("timed_out" if status_code == 408 else "rate_limited")
            if on_event is not None:
                on_event(
                    "fortyguard.status_transition",
                    {
                        "activity_id": activity_id,
                        "status": "timed_out" if status_code == 408 else "rate_limited",
                    },
                )
            if poll_number < max_polls:
                sleep(interval_seconds)
                continue
        if isinstance(status_code, int) and status_code >= 500:
            saw_non_404 = True
            if on_transition is not None:
                on_transition("server_error")
            if on_event is not None:
                on_event(
                    "fortyguard.status_transition",
                    {"activity_id": activity_id, "status": "server_error"},
                )
            if poll_number < max_polls:
                sleep(interval_seconds)
                continue
        if status_code == 404:
            if saw_non_404 or poll_number > status_404_grace_checks:
                raise classify_provider_error(404, "activity not found")
        else:
            saw_non_404 = True
        status = response.get("status")
        if isinstance(status, str) and on_transition is not None:
            on_transition(status)
        if isinstance(status, str) and on_event is not None:
            on_event("fortyguard.status_transition", {"activity_id": activity_id, "status": status})
        if status == "Completed":
            result = response.get("result")
            if not isinstance(result, Mapping):
                raise ProviderError(
                    ProviderErrorKind.MALFORMED_RESPONSE, detail="missing task result"
                )
            completed = dict(result)
            for key in ("credits_used", "request_id"):
                if key in response:
                    completed[key] = response[key]
            return completed
        if status == "Failed":
            raise ProviderError(ProviderErrorKind.TASK_FAILURE, detail="provider task failed")
        if status_code not in (None, 200, 202, 404):
            if not isinstance(status_code, int):
                raise ProviderError(
                    ProviderErrorKind.MALFORMED_RESPONSE, detail="invalid status code"
                )
            raise classify_provider_error(status_code, "status lookup failed")
        if poll_number < max_polls:
            sleep(interval_seconds)
    raise ProviderError(ProviderErrorKind.TIMEOUT, detail="activity polling timed out")


def _response_metadata(result: Mapping[str, object]) -> dict[str, object]:
    return {key: result[key] for key in ("credits_used", "request_id") if key in result}
