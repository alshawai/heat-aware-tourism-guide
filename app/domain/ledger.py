"""Operational call accounting without credentials or raw provider payloads.

The provider does not report per-activity credit costs (ADR 0004 §5), so this
ledger records two distinct facts: one *call record* per submitted provider
call keyed by activity ID, and *reconciliation records* holding authoritative
account-level credit totals for an explicit date window. A call's
``credits_used`` is ``None`` when the provider did not report one — never a
guess. The enforced budget unit is therefore calls, not credits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from threading import Lock
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True)
class UsageRecord:
    """One submitted provider call. ``credits_used`` is ``None`` if unreported."""

    activity_id: str
    endpoint: str
    credits_used: int | None
    completed_at: datetime
    status: str
    scope: str = "core"


@dataclass(frozen=True)
class ReconciliationRecord:
    """An authoritative account-level credit total for a closed date window."""

    window_start: date
    window_end: date
    total_credits_used: int
    reconciled_at: datetime
    activity_breakdown: tuple[Mapping[str, object], ...] = field(default=())

    @property
    def window(self) -> tuple[date, date]:
        return self.window_start, self.window_end


class BudgetExceededError(Exception):
    """Raised when a provider call would exceed the all-time call budget."""


class CreditLedger:
    """Append-only call log with optional all-time call-count enforcement."""

    def __init__(
        self,
        budget: int | None = None,
        enrichment_budget: int | None = None,
        *,
        initial_records: Sequence[UsageRecord] = (),
        initial_reconciliations: Sequence[ReconciliationRecord] = (),
        on_record: Callable[[UsageRecord], None] | None = None,
        on_reconcile: Callable[[ReconciliationRecord], None] | None = None,
    ) -> None:
        if budget is not None and budget < 0:
            raise ValueError("budget must be non-negative")
        if enrichment_budget is not None and enrichment_budget < 0:
            raise ValueError("enrichment budget must be non-negative")
        self.budget = budget
        self.enrichment_budget = enrichment_budget
        self.records: list[UsageRecord] = list(initial_records)
        self.reconciliations: list[ReconciliationRecord] = list(initial_reconciliations)
        self.planned_optional: dict[str, int] = {}
        self._on_record = on_record
        self._on_reconcile = on_reconcile
        self._reservations: dict[int, tuple[str, date | None]] = {}
        self._next_reservation = 0
        self._lock = Lock()

    def _count(self, *, scope: str, day: date | None = None) -> int:
        return sum(
            1
            for record in self.records
            if record.scope == scope
            and (day is None or record.completed_at.astimezone(timezone.utc).date() == day)
        )

    def authorize_enrichment(self, *, now: datetime | None = None) -> int:
        """Reserve one UTC-day enrichment call before provider submission."""
        if self.enrichment_budget is None:
            raise BudgetExceededError("enrichment call budget is not configured")
        day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
        with self._lock:
            used = self._count(scope="enrichment", day=day)
            reserved = sum(
                1
                for scope, reserved_day in self._reservations.values()
                if scope == "enrichment" and reserved_day == day
            )
            if self.enrichment_budget - used - reserved <= 0:
                raise BudgetExceededError("daily enrichment call budget exhausted")
            self._next_reservation += 1
            self._reservations[self._next_reservation] = ("enrichment", day)
            return self._next_reservation

    def remaining_enrichment(self, *, now: datetime | None = None) -> int:
        """Return remaining enrichment submissions in the current UTC day."""
        if self.enrichment_budget is None:
            return 0
        day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
        with self._lock:
            reserved = sum(
                1
                for scope, reserved_day in self._reservations.values()
                if scope == "enrichment" and reserved_day == day
            )
            return max(
                0,
                self.enrichment_budget - self._count(scope="enrichment", day=day) - reserved,
            )

    @property
    def call_count(self) -> int:
        """Calls made all-time. This is the enforced unit."""
        return len(self.records)

    @property
    def reported_credits(self) -> int:
        """Credits the provider actually attributed to individual calls.

        Usually 0: the provider reports cost per account window, not per call.
        Use :attr:`reconciled_credits` for the authoritative figure.
        """
        return sum(record.credits_used or 0 for record in self.records)

    @property
    def reconciled_credits(self) -> int | None:
        """Authoritative credits from the most recent reconciliation, if any."""
        if not self.reconciliations:
            return None
        latest = max(self.reconciliations, key=lambda entry: entry.reconciled_at)
        return latest.total_credits_used

    @property
    def remaining(self) -> int:
        if self.budget is None:
            raise RuntimeError("record-only ledger has no budget")
        with self._lock:
            reserved = sum(1 for scope, _ in self._reservations.values() if scope == "core")
            return self.budget - self._count(scope="core") - reserved

    def plan_optional(self, subject: str, credits: int) -> None:
        if credits < 0:
            raise ValueError("planned credits must be non-negative")
        self.planned_optional[subject] = credits

    def authorize_call(self) -> int | None:
        """Check the budget *before* spending. Raises if no call is left."""
        with self._lock:
            if self.budget is not None:
                core_used = self._count(scope="core")
                core_reserved = sum(
                    1 for scope, _ in self._reservations.values() if scope == "core"
                )
                if self.budget - core_used - core_reserved <= 0:
                    raise BudgetExceededError(
                        f"call budget exceeded: {core_used} of {self.budget} calls used"
                    )
                self._next_reservation += 1
                self._reservations[self._next_reservation] = ("core", None)
                return self._next_reservation
            return None

    def authorize(self, *, scope: str = "core", now: datetime | None = None) -> int | None:
        """Authorize a core or daily enrichment provider submission."""
        if scope == "enrichment":
            return self.authorize_enrichment(now=now)
        if scope != "core":
            raise ValueError("ledger scope must be core or enrichment")
        return self.authorize_call()

    def release_call(self, reservation: int | None = None) -> None:
        """Return a reserved slot only when no provider activity was accepted."""
        with self._lock:
            if reservation is not None:
                self._reservations.pop(reservation, None)
            elif self._reservations:
                self._reservations.pop(next(reversed(self._reservations)))

    def record(self, usage: UsageRecord, *, reservation: int | None = None) -> None:
        with self._lock:
            if any(record.activity_id == usage.activity_id for record in self.records):
                if reservation is not None:
                    self._reservations.pop(reservation, None)
                elif self._reservations:
                    self._reservations.pop(next(reversed(self._reservations)))
                return
            if usage.credits_used is not None and usage.credits_used < 0:
                raise ValueError("reported credits must be non-negative")
            self.records.append(usage)
            if reservation is not None:
                self._reservations.pop(reservation, None)
            elif self._reservations:
                self._reservations.pop(next(reversed(self._reservations)))
        if self._on_record is not None:
            self._on_record(usage)

    def reconcile(self, snapshot: ReconciliationRecord) -> None:
        if snapshot.total_credits_used < 0:
            raise ValueError("reconciled credits must be non-negative")
        if snapshot.window_end < snapshot.window_start:
            raise ValueError("reconciliation window end must not precede its start")
        if any(entry.window == snapshot.window for entry in self.reconciliations):
            return
        self.reconciliations.append(snapshot)
        if self._on_reconcile is not None:
            self._on_reconcile(snapshot)
