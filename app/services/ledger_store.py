"""JSONL persistence for the call ledger: append-only, reload-idempotent.

The file holds two record kinds discriminated by ``kind`` (ADR 0004 §5): call
records (one per completed provider call) and reconciliation records
(authoritative account credit totals for a date window). Records written before
the ``kind`` field existed are read as call records.
"""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Any, Mapping

from app.domain.ledger import CreditLedger, ReconciliationRecord, UsageRecord

CALL_KIND = "call"
RECONCILIATION_KIND = "reconciliation"


class JsonlLedgerStore:
    """Append-only JSONL ledger store loaded at startup (ADR 0004 §5).

    Reload is idempotent: call records dedupe by activity ID, reconciliation
    records by window range. Loaded call records count toward the all-time
    total but never retroactively raise — enforcement happens before new calls.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def read_all(self) -> tuple[list[UsageRecord], list[ReconciliationRecord]]:
        if not self._path.is_file():
            return [], []
        calls: list[UsageRecord] = []
        reconciliations: list[ReconciliationRecord] = []
        seen_activities: set[str] = set()
        seen_windows: set[tuple[date, date]] = set()
        lines = self._path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if not isinstance(payload, Mapping):
                    raise TypeError("ledger entry must be an object")
                if payload.get("kind", CALL_KIND) == RECONCILIATION_KIND:
                    snapshot = _parse_reconciliation(payload)
                    if snapshot.window in seen_windows:
                        continue
                    seen_windows.add(snapshot.window)
                    reconciliations.append(snapshot)
                    continue
                record = _parse_call(payload)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"ledger file {self._path} line {line_number} is malformed: {error}"
                ) from error
            if record.activity_id in seen_activities:
                continue
            seen_activities.add(record.activity_id)
            calls.append(record)
        return calls, reconciliations

    def read_records(self) -> list[UsageRecord]:
        return self.read_all()[0]

    def load(self, budget: int | None = None) -> CreditLedger:
        calls, reconciliations = self.read_all()
        return CreditLedger(
            budget,
            initial_records=calls,
            initial_reconciliations=reconciliations,
            on_record=self.append,
            on_reconcile=self.append_reconciliation,
        )

    def append(self, record: UsageRecord) -> None:
        self._write(
            {
                "kind": CALL_KIND,
                "activity_id": record.activity_id,
                "endpoint": record.endpoint,
                "credits_used": record.credits_used,
                "completed_at": record.completed_at.isoformat(),
                "status": record.status,
            }
        )

    def append_reconciliation(self, snapshot: ReconciliationRecord) -> None:
        self._write(
            {
                "kind": RECONCILIATION_KIND,
                "window_start": snapshot.window_start.isoformat(),
                "window_end": snapshot.window_end.isoformat(),
                "total_credits_used": snapshot.total_credits_used,
                "reconciled_at": snapshot.reconciled_at.isoformat(),
                "activity_breakdown": list(snapshot.activity_breakdown),
            }
        )

    def _write(self, payload: Mapping[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as ledger_file:
            ledger_file.write(json.dumps(payload) + "\n")


def _parse_call(payload: Mapping[str, Any]) -> UsageRecord:
    credits_used = payload["credits_used"]
    if credits_used is not None and (
        isinstance(credits_used, bool) or not isinstance(credits_used, int)
    ):
        raise TypeError("credits_used must be an integer or null")
    return UsageRecord(
        activity_id=payload["activity_id"],
        endpoint=payload["endpoint"],
        credits_used=credits_used,
        completed_at=_parse_datetime(payload["completed_at"]),
        status=payload["status"],
    )


def _parse_reconciliation(payload: Mapping[str, Any]) -> ReconciliationRecord:
    breakdown = payload.get("activity_breakdown", [])
    if not isinstance(breakdown, list):
        raise TypeError("activity_breakdown must be a list")
    total = payload["total_credits_used"]
    if isinstance(total, bool) or not isinstance(total, int):
        raise TypeError("total_credits_used must be an integer")
    return ReconciliationRecord(
        window_start=_parse_date(payload["window_start"]),
        window_end=_parse_date(payload["window_end"]),
        total_credits_used=total,
        reconciled_at=_parse_datetime(payload["reconciled_at"]),
        activity_breakdown=tuple(row for row in breakdown if isinstance(row, Mapping)),
    )


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("timestamps must be ISO datetime strings")
    return datetime.fromisoformat(value)


def _parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise TypeError("window bounds must be ISO date strings")
    return date.fromisoformat(value)
