"""JSONL ledger persistence: call records and reconciliation snapshots (ADR 0004 §5)."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.domain.ledger import (
    BudgetExceededError,
    CreditLedger,
    ReconciliationRecord,
    UsageRecord,
)
from app.services.ledger_store import JsonlLedgerStore

COMPLETED_AT = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)


def _record(activity_id: str, credits: int | None = None) -> UsageRecord:
    return UsageRecord(activity_id, "/v1/heatmap", credits, COMPLETED_AT, "completed")


def _snapshot(total: int = 42, start: date = date(2026, 8, 1)) -> ReconciliationRecord:
    return ReconciliationRecord(
        window_start=start,
        window_end=date(2026, 8, 28),
        total_credits_used=total,
        reconciled_at=COMPLETED_AT,
        activity_breakdown=({"name": "Thermal Comfort Map", "credits": total, "count": 7},),
    )


def test_ledger_store_appends_and_reloads_records_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "data" / "ledger.jsonl"
    JsonlLedgerStore(path).load(budget=10).record(_record("activity-1", 4))

    reloaded = JsonlLedgerStore(path).load(budget=10)
    assert reloaded.call_count == 1
    assert reloaded.reported_credits == 4
    assert reloaded.records[0].activity_id == "activity-1"
    assert reloaded.records[0].completed_at == COMPLETED_AT


def test_ledger_store_round_trips_unpriced_calls(tmp_path: Path) -> None:
    """The real provider reports no credits, so null must survive a restart."""
    path = tmp_path / "ledger.jsonl"
    JsonlLedgerStore(path).load().record(_record("activity-1", None))

    reloaded = JsonlLedgerStore(path).load()
    assert reloaded.call_count == 1
    assert reloaded.records[0].credits_used is None
    assert reloaded.reported_credits == 0


def test_ledger_store_reload_is_idempotent_for_duplicate_activity_ids(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = JsonlLedgerStore(path).load()
    ledger.record(_record("activity-1", 4))
    ledger.record(_record("activity-1", 4))
    assert ledger.call_count == 1

    reloaded = JsonlLedgerStore(path).load(budget=10)
    assert reloaded.call_count == 1


def test_ledger_store_loaded_history_enforces_call_budget_for_new_calls(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    store = JsonlLedgerStore(path)
    ledger = store.load()
    ledger.record(_record("activity-1"))
    ledger.record(_record("activity-2"))

    reloaded = JsonlLedgerStore(path).load(budget=3)
    assert reloaded.remaining == 1
    reloaded.authorize_call()
    reloaded.record(_record("activity-3"))
    with pytest.raises(BudgetExceededError):
        reloaded.authorize_call()
    assert JsonlLedgerStore(path).load().call_count == 3


def test_ledger_store_round_trips_reconciliation_records(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = JsonlLedgerStore(path).load()
    ledger.record(_record("activity-1"))
    ledger.reconcile(_snapshot())

    reloaded = JsonlLedgerStore(path).load()
    assert reloaded.call_count == 1
    assert reloaded.reconciled_credits == 42
    assert reloaded.reconciliations[0].window == (date(2026, 8, 1), date(2026, 8, 28))
    assert reloaded.reconciliations[0].activity_breakdown[0]["name"] == "Thermal Comfort Map"


def test_ledger_store_reload_dedupes_reconciliations_by_window(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    store = JsonlLedgerStore(path)
    store.append_reconciliation(_snapshot())
    store.append_reconciliation(_snapshot())
    assert len(store.load().reconciliations) == 1


def test_ledger_store_reads_legacy_lines_without_a_kind_field(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        '{"activity_id": "activity-1", "endpoint": "/v1/heatmap", "credits_used": 2,'
        ' "completed_at": "2026-08-23T12:00:00+00:00", "status": "completed"}\n',
        encoding="utf-8",
    )
    ledger = JsonlLedgerStore(path).load()
    assert ledger.call_count == 1
    assert ledger.reported_credits == 2


def test_ledger_store_handles_missing_file_as_empty(tmp_path: Path) -> None:
    ledger = JsonlLedgerStore(tmp_path / "missing.jsonl").load(budget=10)
    assert ledger.call_count == 0
    assert ledger.reconciled_credits is None
    assert isinstance(ledger, CreditLedger)


def test_ledger_store_rejects_malformed_lines_loudly(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ledger"):
        JsonlLedgerStore(path).load()


def test_ledger_store_rejects_malformed_reconciliation_lines(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        '{"kind": "reconciliation", "window_start": "2026-08-01",'
        ' "window_end": "2026-08-28", "total_credits_used": "many",'
        ' "reconciled_at": "2026-08-28T12:00:00+00:00"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ledger"):
        JsonlLedgerStore(path).load()


def test_ledger_store_load_without_budget_is_record_only(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = JsonlLedgerStore(path).load()
    for index in range(20):
        ledger.record(_record(f"activity-{index}"))
    assert JsonlLedgerStore(path).load().call_count == 20
