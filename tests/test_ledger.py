from datetime import datetime, timezone

import pytest

from app.domain.ledger import BudgetExceededError, CreditLedger, UsageRecord


def test_ledger_records_actual_provider_usage_and_rejects_overspend() -> None:
    ledger = CreditLedger(budget=10)
    ledger.record(UsageRecord("activity-1", "/v1/heatmap", 4, datetime.now(timezone.utc), "completed"))
    assert ledger.remaining == 6
    assert ledger.total_used == 4
    with pytest.raises(BudgetExceededError, match="budget"):
        ledger.record(UsageRecord("activity-2", "/v1/env_params", 7, datetime.now(timezone.utc), "completed"))


def test_ledger_separates_planned_optional_usage_from_actual_usage() -> None:
    ledger = CreditLedger(budget=10)
    ledger.plan_optional("hotel-a", 3)
    ledger.record(UsageRecord("activity-1", "/v1/satellite", 2, datetime.now(timezone.utc), "completed"))
    assert ledger.planned_optional == {"hotel-a": 3}
    assert ledger.total_used == 2
    assert ledger.records[0].activity_id == "activity-1"


def test_ledger_does_not_double_count_replayed_activity_completion() -> None:
    ledger = CreditLedger(budget=5)
    usage = UsageRecord("activity-1", "/v1/heatmap", 4, datetime.now(timezone.utc), "completed")
    ledger.record(usage)
    ledger.record(usage)
    assert ledger.total_used == 4
    assert len(ledger.records) == 1


def test_ledger_without_budget_records_without_enforcing() -> None:
    ledger = CreditLedger()
    ledger.record(UsageRecord("activity-1", "/v1/heatmap", 10_000, datetime.now(timezone.utc), "completed"))
    ledger.record(UsageRecord("activity-2", "/v1/heatmap", 10_000, datetime.now(timezone.utc), "completed"))
    assert ledger.budget is None
    assert ledger.total_used == 20_000


def test_ledger_initial_records_load_without_enforcement_or_sink() -> None:
    over_budget = [
        UsageRecord("activity-1", "/v1/heatmap", 8, datetime.now(timezone.utc), "completed"),
        UsageRecord("activity-2", "/v1/heatmap", 8, datetime.now(timezone.utc), "completed"),
    ]
    seen: list[UsageRecord] = []
    ledger = CreditLedger(budget=10, initial_records=over_budget, on_record=seen.append)
    assert ledger.total_used == 16
    with pytest.raises(BudgetExceededError):
        ledger.record(UsageRecord("activity-3", "/v1/heatmap", 1, datetime.now(timezone.utc), "completed"))
    assert seen == []
    ledger.record(UsageRecord("activity-2", "/v1/heatmap", 1, datetime.now(timezone.utc), "completed"))
    assert seen == []


def test_ledger_on_record_sink_observes_only_new_accepted_records() -> None:
    seen: list[UsageRecord] = []
    ledger = CreditLedger(budget=10, on_record=seen.append)
    usage = UsageRecord("activity-1", "/v1/heatmap", 4, datetime.now(timezone.utc), "completed")
    ledger.record(usage)
    ledger.record(usage)
    assert seen == [usage]
