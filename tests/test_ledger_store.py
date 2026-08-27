from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.domain.ledger import BudgetExceededError, CreditLedger, UsageRecord
from app.services.ledger_store import JsonlLedgerStore


def _record(activity_id: str, credits: int) -> UsageRecord:
    return UsageRecord(
        activity_id, "/v1/heatmap", credits, datetime(2026, 8, 23, 12, tzinfo=timezone.utc), "completed"
    )


def test_ledger_store_appends_and_reloads_records_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "data" / "ledger.jsonl"
    first = JsonlLedgerStore(path)
    ledger = first.load(budget=10)
    ledger.record(_record("activity-1", 4))

    reloaded = JsonlLedgerStore(path).load(budget=10)
    assert reloaded.total_used == 4
    assert reloaded.records[0].activity_id == "activity-1"
    assert reloaded.records[0].completed_at == datetime(2026, 8, 23, 12, tzinfo=timezone.utc)


def test_ledger_store_reload_is_idempotent_for_duplicate_activity_ids(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    store = JsonlLedgerStore(path)
    ledger = store.load()
    ledger.record(_record("activity-1", 4))
    ledger.record(_record("activity-1", 4))
    assert ledger.total_used == 4

    reloaded = JsonlLedgerStore(path).load(budget=10)
    assert reloaded.total_used == 4
    assert len(reloaded.records) == 1


def test_ledger_store_loaded_history_enforces_budget_for_new_spend(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    store = JsonlLedgerStore(path)
    store.load().record(_record("activity-1", 8))

    reloaded = JsonlLedgerStore(path).load(budget=10)
    assert reloaded.remaining == 2
    with pytest.raises(BudgetExceededError):
        reloaded.record(_record("activity-2", 3))
    reloaded.record(_record("activity-2", 2))
    assert JsonlLedgerStore(path).load().total_used == 10


def test_ledger_store_handles_missing_file_as_empty(tmp_path: Path) -> None:
    ledger = JsonlLedgerStore(tmp_path / "missing.jsonl").load(budget=10)
    assert ledger.total_used == 0
    assert isinstance(ledger, CreditLedger)


def test_ledger_store_rejects_malformed_lines_loudly(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ledger"):
        JsonlLedgerStore(path).load()


def test_ledger_store_load_without_budget_is_record_only(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    JsonlLedgerStore(path).load().record(_record("activity-1", 999))
    assert JsonlLedgerStore(path).load().total_used == 999
