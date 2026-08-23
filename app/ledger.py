"""Operational credit accounting without credentials or raw provider payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UsageRecord:
    activity_id: str
    endpoint: str
    credits_used: int
    completed_at: datetime
    status: str


class CreditLedger:
    def __init__(self, budget: int) -> None:
        if budget < 0:
            raise ValueError("budget must be non-negative")
        self.budget = budget
        self.records: list[UsageRecord] = []
        self.planned_optional: dict[str, int] = {}

    @property
    def total_used(self) -> int:
        return sum(record.credits_used for record in self.records)

    @property
    def remaining(self) -> int:
        return self.budget - self.total_used

    def plan_optional(self, subject: str, credits: int) -> None:
        if credits < 0:
            raise ValueError("planned credits must be non-negative")
        self.planned_optional[subject] = credits

    def record(self, usage: UsageRecord) -> None:
        if usage.credits_used < 0:
            raise ValueError("actual credits must be non-negative")
        if usage.credits_used > self.remaining:
            raise ValueError("credit budget exceeded")
        self.records.append(usage)
