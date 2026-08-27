"""Operational credit accounting without credentials or raw provider payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence


@dataclass(frozen=True)
class UsageRecord:
    activity_id: str
    endpoint: str
    credits_used: int
    completed_at: datetime
    status: str


class BudgetExceededError(Exception):
    """Raised when recording actual usage would exceed the all-time credit budget."""


class CreditLedger:
    def __init__(
        self,
        budget: int | None = None,
        *,
        initial_records: Sequence[UsageRecord] = (),
        on_record: Callable[[UsageRecord], None] | None = None,
    ) -> None:
        if budget is not None and budget < 0:
            raise ValueError("budget must be non-negative")
        self.budget = budget
        self.records: list[UsageRecord] = list(initial_records)
        self.planned_optional: dict[str, int] = {}
        self._on_record = on_record

    @property
    def total_used(self) -> int:
        return sum(record.credits_used for record in self.records)

    @property
    def remaining(self) -> int:
        if self.budget is None:
            raise RuntimeError("record-only ledger has no budget")
        return self.budget - self.total_used

    def plan_optional(self, subject: str, credits: int) -> None:
        if credits < 0:
            raise ValueError("planned credits must be non-negative")
        self.planned_optional[subject] = credits

    def record(self, usage: UsageRecord) -> None:
        if any(record.activity_id == usage.activity_id for record in self.records):
            return
        if usage.credits_used < 0:
            raise ValueError("actual credits must be non-negative")
        if self.budget is not None and usage.credits_used > self.remaining:
            raise BudgetExceededError("credit budget exceeded")
        self.records.append(usage)
        if self._on_record is not None:
            self._on_record(usage)
