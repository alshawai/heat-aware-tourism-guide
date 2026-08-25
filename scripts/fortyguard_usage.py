#!/usr/bin/env python3
"""Print FortyGuard credit usage for a date window.

The API key is read from FORTYGUARD_API_KEY. It is never printed or included in
the formatted output.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.fortyguard_usage import (
    default_usage_window,
    fetch_custom_usage,
    load_api_key_from_environment,
)


def main() -> int:
    start_default, end_default = default_usage_window()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=start_default)
    parser.add_argument("--end", type=date.fromisoformat, default=end_default)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    usage = fetch_custom_usage(
        load_api_key_from_environment(),
        args.start,
        args.end,
        timeout_seconds=args.timeout,
    )
    date_range = usage.get("date_range", {})
    print(f"Window: {date_range.get('date_range_formatted', f'{args.start} to {args.end}')}")
    print(f"Credits used: {usage.get('total_credits_used', 'unknown')}")
    for row in usage.get("activity_breakdown", []):
        if isinstance(row, dict):
            print(f"  {row.get('name', 'unknown')}: {row.get('credits', 'unknown')} credits over {row.get('count', 'unknown')} calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
