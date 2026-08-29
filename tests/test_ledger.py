"""Call ledger: honest call accounting with call-count budget enforcement (ADR 0004 §5)."""

from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.domain.ledger import (
    BudgetExceededError,
    CreditLedger,
    ReconciliationRecord,
    UsageRecord,
)

NOW = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)


def _call(
    activity_id: str, credits: int | None = None, endpoint: str = "/v1/heatmap"
) -> UsageRecord:
    return UsageRecord(activity_id, endpoint, credits, NOW, "completed")


def test_ledger_counts_calls_and_authorizes_against_the_call_budget() -> None:
    ledger = CreditLedger(budget=2)
    ledger.authorize_call()
    ledger.record(_call("activity-1"))
    assert ledger.remaining == 1
    assert ledger.call_count == 1

    ledger.authorize_call()
    ledger.record(_call("activity-2", endpoint="/v1/env_params"))
    assert ledger.remaining == 0
    with pytest.raises(BudgetExceededError, match="call budget exceeded"):
        ledger.authorize_call()


def test_ledger_reserves_budget_slots_for_concurrent_calls() -> None:
    ledger = CreditLedger(budget=1)

    def authorize() -> str:
        try:
            ledger.authorize_call()
        except BudgetExceededError:
            return "rejected"
        return "reserved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: authorize(), range(2)))

    assert sorted(results) == ["rejected", "reserved"]
    assert ledger.remaining == 0
    ledger.release_call()
    assert ledger.remaining == 1


def test_ledger_records_calls_the_provider_did_not_price() -> None:
    """The real provider omits credits_used; an unpriced call is still a call."""
    ledger = CreditLedger(budget=10)
    ledger.record(_call("activity-1", credits=None))
    assert ledger.call_count == 1
    assert ledger.records[0].credits_used is None
    assert ledger.reported_credits == 0
    assert ledger.reconciled_credits is None


def test_ledger_keeps_provider_reported_credits_when_present() -> None:
    ledger = CreditLedger()
    ledger.record(_call("activity-1", credits=4))
    ledger.record(_call("activity-2", credits=None))
    assert ledger.reported_credits == 4
    assert ledger.call_count == 2


def test_ledger_rejects_negative_reported_credits() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        CreditLedger().record(_call("activity-1", credits=-1))


def test_ledger_separates_planned_optional_usage_from_actual_calls() -> None:
    ledger = CreditLedger(budget=10)
    ledger.plan_optional("hotel-a", 3)
    ledger.record(_call("activity-1", endpoint="/v1/satellite"))
    assert ledger.planned_optional == {"hotel-a": 3}
    assert ledger.call_count == 1
    assert ledger.records[0].activity_id == "activity-1"


def test_ledger_does_not_double_count_replayed_activity_completion() -> None:
    ledger = CreditLedger(budget=5)
    usage = _call("activity-1", credits=4)
    ledger.record(usage)
    ledger.record(usage)
    assert ledger.call_count == 1


def test_ledger_without_budget_records_without_enforcing() -> None:
    ledger = CreditLedger()
    for index in range(50):
        ledger.record(_call(f"activity-{index}"))
    ledger.authorize_call()
    assert ledger.budget is None
    assert ledger.call_count == 50


def test_loaded_records_count_toward_the_budget_without_retroactive_raising() -> None:
    seen: list[UsageRecord] = []
    ledger = CreditLedger(
        budget=2,
        initial_records=[_call("activity-1"), _call("activity-2"), _call("activity-3")],
        on_record=seen.append,
    )
    assert ledger.call_count == 3
    assert seen == []
    with pytest.raises(BudgetExceededError):
        ledger.authorize_call()


def test_ledger_on_record_sink_observes_only_new_accepted_records() -> None:
    seen: list[UsageRecord] = []
    ledger = CreditLedger(budget=10, on_record=seen.append)
    usage = _call("activity-1", credits=4)
    ledger.record(usage)
    ledger.record(usage)
    assert seen == [usage]


def _snapshot(total: int = 42, start: date = date(2026, 8, 1)) -> ReconciliationRecord:
    return ReconciliationRecord(
        window_start=start,
        window_end=date(2026, 8, 28),
        total_credits_used=total,
        reconciled_at=NOW,
        activity_breakdown=({"name": "Thermal Comfort Map", "credits": 42, "count": 7},),
    )


def test_reconciliation_supplies_the_authoritative_credit_total() -> None:
    seen: list[ReconciliationRecord] = []
    ledger = CreditLedger(on_reconcile=seen.append)
    ledger.record(_call("activity-1"))
    assert ledger.reconciled_credits is None

    ledger.reconcile(_snapshot())
    assert ledger.reconciled_credits == 42
    assert seen == [_snapshot()]


def test_reconciling_the_same_window_twice_is_idempotent() -> None:
    seen: list[ReconciliationRecord] = []
    ledger = CreditLedger(on_reconcile=seen.append)
    ledger.reconcile(_snapshot())
    ledger.reconcile(_snapshot())
    assert len(ledger.reconciliations) == 1
    assert len(seen) == 1


def test_latest_reconciliation_wins() -> None:
    ledger = CreditLedger()
    ledger.reconcile(_snapshot(total=42, start=date(2026, 8, 1)))
    later = ReconciliationRecord(
        window_start=date(2026, 8, 2),
        window_end=date(2026, 8, 28),
        total_credits_used=99,
        reconciled_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
    )
    ledger.reconcile(later)
    assert ledger.reconciled_credits == 99


def test_reconciliation_rejects_impossible_windows_and_totals() -> None:
    ledger = CreditLedger()
    with pytest.raises(ValueError, match="non-negative"):
        ledger.reconcile(_snapshot(total=-1))
    with pytest.raises(ValueError, match="must not precede"):
        ledger.reconcile(
            ReconciliationRecord(
                window_start=date(2026, 8, 28),
                window_end=date(2026, 8, 1),
                total_credits_used=5,
                reconciled_at=NOW,
            )
        )
