"""The reconcile entry point: account-level credit truth into the ledger (ADR 0004 §5)."""

from datetime import date
import json
from pathlib import Path
import sys
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.reconcile_ledger as reconcile_ledger
from app.services.ledger_store import JsonlLedgerStore

USAGE_RESPONSE: dict[str, Any] = {
    "date_range": {"date_range_formatted": "Aug 1 - Aug 28, 2026"},
    "total_credits_used": 42,
    "activity_breakdown": [{"name": "Thermal Comfort Map", "credits": 42, "count": 7}],
}


def _stub_provider(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any] | None = None
) -> None:
    """Replace the live account query; no network, no real key."""
    monkeypatch.setattr(reconcile_ledger, "load_api_key_from_environment", lambda: "secret")
    monkeypatch.setattr(
        reconcile_ledger,
        "fetch_custom_usage",
        lambda *args, **kwargs: dict(USAGE_RESPONSE if response is None else response),
    )


def _run(tmp_path: Path, *extra: str) -> tuple[int, Path]:
    ledger_path = tmp_path / "ledger.jsonl"
    code = reconcile_ledger.main(
        ["--start", "2026-08-01", "--end", "2026-08-28", "--ledger-path", str(ledger_path), *extra]
    )
    return code, ledger_path


def test_reconcile_appends_authoritative_window_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_provider(monkeypatch)
    code, ledger_path = _run(tmp_path)
    assert code == 0

    ledger = JsonlLedgerStore(ledger_path).load()
    assert ledger.reconciled_credits == 42
    assert ledger.reconciliations[0].window == (date(2026, 8, 1), date(2026, 8, 28))
    assert ledger.reconciliations[0].activity_breakdown[0]["count"] == 7


def test_reconcile_does_not_invent_call_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reconciliation is account-scoped; it cannot attribute calls."""
    _stub_provider(monkeypatch)
    _, ledger_path = _run(tmp_path)
    ledger = JsonlLedgerStore(ledger_path).load()
    assert ledger.call_count == 0
    assert ledger.records == []


def test_reconcile_is_idempotent_for_the_same_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_provider(monkeypatch)
    _, ledger_path = _run(tmp_path)
    reconcile_ledger.main(
        ["--start", "2026-08-01", "--end", "2026-08-28", "--ledger-path", str(ledger_path)]
    )
    lines = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["kind"] == "reconciliation"


def test_reconcile_fails_loudly_when_provider_omits_the_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_provider(monkeypatch, response={"other": 1})
    code, ledger_path = _run(tmp_path)
    assert code == 1
    assert not ledger_path.exists()


def test_reconcile_never_writes_the_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_provider(monkeypatch)
    _, ledger_path = _run(tmp_path)
    assert "secret" not in ledger_path.read_text(encoding="utf-8")
