"""JSONL persistence for the credit ledger: append-only, reload-idempotent."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from app.domain.ledger import CreditLedger, UsageRecord


class JsonlLedgerStore:
    """Append-only JSONL ledger store loaded at startup (ADR 0004).

    Reload is idempotent via activity-ID dedupe; loaded records are history —
    they never trigger budget enforcement, only new records do.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def read_records(self) -> list[UsageRecord]:
        if not self._path.is_file():
            return []
        records: list[UsageRecord] = []
        seen: set[str] = set()
        for line_number, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                record = UsageRecord(
                    activity_id=payload["activity_id"],
                    endpoint=payload["endpoint"],
                    credits_used=payload["credits_used"],
                    completed_at=_parse_datetime(payload["completed_at"]),
                    status=payload["status"],
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"ledger file {self._path} line {line_number} is malformed: {error}"
                ) from error
            if record.activity_id in seen:
                continue
            seen.add(record.activity_id)
            records.append(record)
        return records

    def load(self, budget: int | None = None) -> CreditLedger:
        return CreditLedger(budget, initial_records=self.read_records(), on_record=self.append)

    def append(self, record: UsageRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "activity_id": record.activity_id,
            "endpoint": record.endpoint,
            "credits_used": record.credits_used,
            "completed_at": record.completed_at.isoformat(),
            "status": record.status,
        }
        with self._path.open("a", encoding="utf-8") as ledger_file:
            ledger_file.write(json.dumps(payload) + "\n")


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("completed_at must be an ISO datetime string")
    return datetime.fromisoformat(value)
