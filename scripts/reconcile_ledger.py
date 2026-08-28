#!/usr/bin/env python3
"""Reconcile the call ledger against the provider's authoritative credit usage.

The provider reports credits only per account and date window, not per call
(ADR 0004 §5), so the ledger's credit truth comes from here. This appends a
reconciliation record holding the provider's own totals for the window.

    python scripts/reconcile_ledger.py                  # rolling 30-day window
    python scripts/reconcile_ledger.py --start 2026-08-01 --end 2026-08-28

The API key is read from FORTYGUARD_API_KEY and is never printed. This queries
an account endpoint; it submits no analytics activity.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.ledger import ReconciliationRecord
from app.integrations.fortyguard.usage import (
    default_usage_window,
    fetch_custom_usage,
    load_api_key_from_environment,
)
from app.settings import load_settings
from app.wiring import build_ledger


def main(argv: list[str] | None = None) -> int:
    start_default, end_default = default_usage_window()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=start_default)
    parser.add_argument("--end", type=date.fromisoformat, default=end_default)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=None,
        help="override FORTYGUARD_LEDGER_PATH for this reconciliation",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.ledger_path is not None:
        settings = replace(settings, ledger_path=args.ledger_path)
    ledger = build_ledger(settings)

    usage = fetch_custom_usage(
        load_api_key_from_environment(), args.start, args.end, timeout_seconds=args.timeout
    )
    total = usage.get("total_credits_used")
    if not isinstance(total, int) or isinstance(total, bool):
        print(
            f"provider did not report an integer total_credits_used: {total!r}",
            file=sys.stderr,
        )
        return 1
    breakdown = usage.get("activity_breakdown", [])
    snapshot = ReconciliationRecord(
        window_start=args.start,
        window_end=args.end,
        total_credits_used=total,
        reconciled_at=datetime.now(timezone.utc),
        activity_breakdown=tuple(row for row in breakdown if isinstance(row, dict)),
    )

    before = ledger.reconciled_credits
    ledger.reconcile(snapshot)
    if ledger.reconciled_credits == before and before is not None:
        print(f"window {args.start}..{args.end} already reconciled; ledger unchanged")
    else:
        print(f"reconciled {args.start}..{args.end} -> {total} credits")
    print(f"calls logged all-time: {ledger.call_count}")
    for row in snapshot.activity_breakdown:
        print(
            f"  {row.get('name', 'unknown')}: {row.get('credits', 'unknown')} credits"
            f" over {row.get('count', 'unknown')} calls"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
