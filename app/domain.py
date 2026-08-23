"""Product-domain contracts shared by live and fixture execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Sequence

from app.ledger import CreditLedger, UsageRecord


@dataclass(frozen=True)
class CacheKey:
    value: str

    @classmethod
    def create(cls, endpoint: str, schema_version: str, payload: dict[str, Any]) -> "CacheKey":
        canonical = json.dumps(
            {"endpoint": endpoint, "schema_version": schema_version, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        return cls(digest)


@dataclass(frozen=True)
class Provenance:
    source: str
    retrieved_at: datetime
    data_date: str
    stale: bool
    forecast: bool
    activity_id: str | None = None
    raw_payload: dict[str, Any] | None = None

    @classmethod
    def cached(
        cls,
        *,
        retrieved_at: datetime,
        data_date: str,
        activity_id: str | None = None,
        raw_payload: dict[str, Any] | None = None,
        forecast: bool = False,
    ) -> "Provenance":
        return cls("cache", retrieved_at, data_date, True, forecast, activity_id, raw_payload)


@dataclass(frozen=True)
class EnrichmentRequest:
    top_n: int
    credits_per_item: int


@dataclass(frozen=True)
class EnrichmentPlan:
    selected: tuple[str, ...]
    remaining_credits: int
    base_result_preserved: bool


@dataclass(frozen=True)
class EnrichmentResult:
    base_ranking: tuple[str, ...]
    enriched: dict[str, Any]
    failures: dict[str, str]
    remaining_credits: int


@dataclass(frozen=True)
class EnrichmentOutcome:
    payload: Any
    activity_id: str
    credits_used: int
    endpoint: str


class EnrichmentPlanner:
    def __init__(self, credits: int) -> None:
        self.credits = max(0, credits)

    def plan(self, candidates: Sequence[str], request: EnrichmentRequest) -> EnrichmentPlan:
        if request.top_n < 0 or request.credits_per_item < 0:
            raise ValueError("enrichment limits must be non-negative")
        if request.credits_per_item == 0:
            count = min(request.top_n, len(candidates))
        else:
            count = min(request.top_n, len(candidates), self.credits // request.credits_per_item)
        used = count * request.credits_per_item
        return EnrichmentPlan(tuple(candidates[:count]), self.credits - used, True)

    def execute(
        self,
        candidates: Sequence[str],
        request: EnrichmentRequest,
        loader: Callable[[str], Any],
        ledger: CreditLedger | None = None,
    ) -> EnrichmentResult:
        plan = self.plan(candidates, request)
        enriched: dict[str, Any] = {}
        failures: dict[str, str] = {}
        for candidate in plan.selected:
            if ledger is not None:
                ledger.plan_optional(candidate, request.credits_per_item)
            try:
                outcome = loader(candidate)
                if isinstance(outcome, EnrichmentOutcome):
                    enriched[candidate] = outcome.payload
                    if ledger is not None:
                        ledger.record(
                            UsageRecord(
                                outcome.activity_id,
                                outcome.endpoint,
                                outcome.credits_used,
                                datetime.now(timezone.utc),
                                "completed",
                            )
                        )
                else:
                    enriched[candidate] = outcome
            except Exception as error:
                failures[candidate] = str(error)
        self.credits = plan.remaining_credits
        return EnrichmentResult(tuple(candidates), enriched, failures, self.credits)


@dataclass(frozen=True)
class ReadinessInput:
    heat_celsius: float
    threshold_celsius: float
    coverage: float
    forecast: bool


@dataclass(frozen=True)
class ReadinessResult:
    priority: str
    reason_codes: tuple[str, ...]


def readiness(value: ReadinessInput) -> ReadinessResult:
    reasons: list[str] = []
    if value.heat_celsius > value.threshold_celsius:
        reasons.append("HEAT_THRESHOLD_EXCEEDED")
    if value.coverage < 0.7:
        reasons.append("LOW_DATA_COVERAGE")
    if not value.forecast:
        reasons.append("HISTORICAL_CONTEXT")
    priority = "high" if "HEAT_THRESHOLD_EXCEEDED" in reasons else "medium" if reasons else "low"
    return ReadinessResult(priority, tuple(reasons))
