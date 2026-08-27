"""Acquire real provider fixtures: run a scenario, commit the raw fixture + sidecar.

Maintainer-triggered (real credits are spent). Usage:

    python scripts/acquire_fixture.py --scenario tcm-historical --out-dir fixtures/acquired

Requires ALLOW_LIVE=true and FORTYGUARD_API_KEY (see .env.example). Actual
usage is appended to the ledger (FORTYGUARD_LEDGER_PATH, default
data/ledger.jsonl) and obeys FORTYGUARD_CREDIT_BUDGET.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.acquisition import (
    ENV_PARAMS_SCENARIOS,
    HEATMAP_SCENARIOS,
    acquire_env_params_fixture,
    acquire_heatmap_fixture,
)
from app.settings import load_settings
from app.wiring import build_ledger, build_live_client

ALL_SCENARIOS = {**HEATMAP_SCENARIOS, **ENV_PARAMS_SCENARIOS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Acquire a real provider fixture (raw payload + acquisition sidecar).",
        epilog=f"available scenarios: {', '.join(sorted(ALL_SCENARIOS))}",
    )
    parser.add_argument("--scenario", required=True, choices=sorted(ALL_SCENARIOS))
    parser.add_argument(
        "--out-dir", type=Path, default=Path("fixtures/acquired"), help="fixture output directory"
    )
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=None,
        help="override FORTYGUARD_LEDGER_PATH for this acquisition",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    if not settings.allow_live:
        print("acquisition requires ALLOW_LIVE=true and FORTYGUARD_API_KEY", file=sys.stderr)
        return 2
    if args.ledger_path is not None:
        settings = replace(settings, ledger_path=args.ledger_path)

    ledger = build_ledger(settings)
    credits_before = ledger.total_used
    client = build_live_client(settings, ledger=ledger)
    if args.scenario in HEATMAP_SCENARIOS:
        outcome = acquire_heatmap_fixture(
            HEATMAP_SCENARIOS[args.scenario],
            client,
            out_dir=args.out_dir,
            polling=settings.polling,
        )
    else:
        outcome = acquire_env_params_fixture(
            ENV_PARAMS_SCENARIOS[args.scenario],
            client,
            out_dir=args.out_dir,
            polling=settings.polling,
        )
    print(f"acquired {args.scenario}: {outcome.fixture_path}")
    credits_recorded = ledger.total_used > credits_before
    if credits_recorded:
        print(
            f"activity {outcome.record.activity_id}, "
            f"data date {outcome.record.data_date}, "
            f"credits recorded to {settings.ledger_path or 'in-memory ledger'}"
        )
    else:
        print(
            f"activity {outcome.record.activity_id}, "
            f"data date {outcome.record.data_date}, "
            f"no credits reported by provider (ledger not updated)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
