from datetime import datetime, timezone

import pytest

from app.ledger import CreditLedger, UsageRecord


def test_ledger_records_actual_provider_usage_and_rejects_overspend() -> None:
    ledger = CreditLedger(budget=10)
    ledger.record(UsageRecord("activity-1", "/v1/heatmap", 4, datetime.now(timezone.utc), "completed"))
    assert ledger.remaining == 6
    assert ledger.total_used == 4
    with pytest.raises(ValueError, match="budget"):
        ledger.record(UsageRecord("activity-2", "/v1/env_params", 7, datetime.now(timezone.utc), "completed"))


def test_ledger_separates_planned_optional_usage_from_actual_usage() -> None:
    ledger = CreditLedger(budget=10)
    ledger.plan_optional("hotel-a", 3)
    ledger.record(UsageRecord("activity-1", "/v1/satellite", 2, datetime.now(timezone.utc), "completed"))
    assert ledger.planned_optional == {"hotel-a": 3}
    assert ledger.total_used == 2
    assert ledger.records[0].activity_id == "activity-1"
