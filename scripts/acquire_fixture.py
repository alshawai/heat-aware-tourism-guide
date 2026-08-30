"""Acquire real provider fixtures: run a scenario, commit the raw fixture + sidecar.

Maintainer-triggered (real credits are spent). Usage:

    python scripts/acquire_fixture.py --scenario tcm-historical --out-dir fixtures/acquired

Requires ALLOW_LIVE=true and FORTYGUARD_API_KEY (see .env.example). The call
is appended to the ledger (FORTYGUARD_LEDGER_PATH, default data/ledger.jsonl)
and obeys FORTYGUARD_CALL_BUDGET. The provider does not price individual calls,
so run scripts/reconcile_ledger.py for the credit cost (ADR 0004 5).
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.acquisition import (
    ENV_PARAMS_SCENARIOS,
    HEATMAP_SCENARIOS,
    acquire_env_params_fixture,
    acquire_heatmap_fixture,
    OSRM_SCENARIOS,
    acquire_osrm_fixture,
    acquire_overpass_building_fixture,
)
from app.settings import load_settings
from app.wiring import build_ledger, build_live_client
from app.integrations.osrm.client import OsrmClient
from app.integrations.osrm.transport import HttpOsrmTransport
from app.integrations.overpass.client import OverpassClient
from app.integrations.overpass.transport import HttpOverpassTransport
from app.integrations.osrm.client import normalize_response
from app.services.issue23_acquisition import (
    DEFAULT_OUT_DIR as ISSUE23_OUT_DIR,
    execute_issue23_canonical_resume,
    execute_issue23_hotels_resume,
    execute_issue23_plan,
    planned_issue23_env_recovery,
    planned_issue23_hotels_resume,
    planned_canonical_resume_requests,
    planned_requests,
    recover_issue23_canonical_env,
)

ALL_SCENARIOS = {
    **HEATMAP_SCENARIOS,
    **ENV_PARAMS_SCENARIOS,
    **OSRM_SCENARIOS,
    "cathedral-governors-palace-buildings": None,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Acquire a real provider fixture (raw payload + acquisition sidecar).",
        epilog=f"available scenarios: {', '.join(sorted(ALL_SCENARIOS))}",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scenario", choices=sorted(ALL_SCENARIOS))
    mode.add_argument("--plan-issue-23", action="store_true")
    mode.add_argument("--execute-issue-23", action="store_true")
    mode.add_argument("--plan-issue-23-canonical-resume", action="store_true")
    mode.add_argument("--execute-issue-23-canonical-resume", action="store_true")
    mode.add_argument("--plan-issue-23-canonical-env-recovery", action="store_true")
    mode.add_argument("--execute-issue-23-canonical-env-recovery", action="store_true")
    mode.add_argument("--plan-issue-23-hotels-resume", action="store_true")
    mode.add_argument("--execute-issue-23-hotels-resume", action="store_true")
    parser.add_argument(
        "--activity-id",
        help="existing provider activity ID (required for canonical env recovery)",
    )
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

    if args.plan_issue_23:
        out_dir = args.out_dir if args.out_dir != Path("fixtures/acquired") else ISSUE23_OUT_DIR
        print(json.dumps(planned_requests(out_dir), indent=2))
        return 0
    if args.plan_issue_23_canonical_resume:
        out_dir = args.out_dir if args.out_dir != Path("fixtures/acquired") else ISSUE23_OUT_DIR
        print(json.dumps(planned_canonical_resume_requests(out_dir), indent=2))
        return 0
    if args.plan_issue_23_canonical_env_recovery:
        if not args.activity_id:
            parser.error("--activity-id is required for canonical env recovery")
        out_dir = args.out_dir if args.out_dir != Path("fixtures/acquired") else ISSUE23_OUT_DIR
        print(json.dumps(planned_issue23_env_recovery(args.activity_id, out_dir), indent=2))
        return 0
    if args.plan_issue_23_hotels_resume:
        out_dir = args.out_dir if args.out_dir != Path("fixtures/acquired") else ISSUE23_OUT_DIR
        print(json.dumps(planned_issue23_hotels_resume(out_dir), indent=2))
        return 0

    settings = load_settings()
    if args.execute_issue_23:
        if not settings.allow_live:
            print("acquisition requires ALLOW_LIVE=true and FORTYGUARD_API_KEY", file=sys.stderr)
            return 2
        if args.ledger_path is not None:
            settings = replace(settings, ledger_path=args.ledger_path)
        out_dir = args.out_dir if args.out_dir != Path("fixtures/acquired") else ISSUE23_OUT_DIR
        ledger = build_ledger(settings)
        # Preflight occurs inside the workflow before this client can submit.
        outcomes = execute_issue23_plan(
            build_live_client(settings, ledger=ledger),
            ledger,
            out_dir=out_dir,
            polling=settings.polling,
        )
        print(f"completed issue 23 acquisition: {len(outcomes)} new provider record(s)")
        return 0
    if args.execute_issue_23_canonical_resume:
        if not settings.allow_live:
            print("acquisition requires ALLOW_LIVE=true and FORTYGUARD_API_KEY", file=sys.stderr)
            return 2
        if args.ledger_path is not None:
            settings = replace(settings, ledger_path=args.ledger_path)
        out_dir = args.out_dir if args.out_dir != Path("fixtures/acquired") else ISSUE23_OUT_DIR
        ledger = build_ledger(settings)
        outcomes = execute_issue23_canonical_resume(
            build_live_client(settings, ledger=ledger),
            ledger,
            out_dir=out_dir,
            polling=settings.polling,
        )
        print(
            "completed issue 23 canonical resume: "
            f"1 prerequisite replayed, {len(outcomes)} new provider record(s)"
        )
        return 0
    if args.execute_issue_23_canonical_env_recovery:
        if not args.activity_id:
            parser.error("--activity-id is required for canonical env recovery")
        if not settings.allow_live:
            print("acquisition requires ALLOW_LIVE=true and FORTYGUARD_API_KEY", file=sys.stderr)
            return 2
        if args.ledger_path is not None:
            settings = replace(settings, ledger_path=args.ledger_path)
        out_dir = args.out_dir if args.out_dir != Path("fixtures/acquired") else ISSUE23_OUT_DIR
        ledger = build_ledger(settings)
        count_before = ledger.call_count
        outcome = recover_issue23_canonical_env(
            build_live_client(settings, ledger=ledger),
            ledger,
            args.activity_id,
            out_dir=out_dir,
            polling=settings.polling,
        )
        if ledger.call_count != count_before:
            raise RuntimeError("status-only recovery unexpectedly changed the ledger")
        print(
            f"recovered issue 23 env activity {outcome.record.activity_id}: {outcome.fixture_path}"
        )
        return 0
    if args.execute_issue_23_hotels_resume:
        if not settings.allow_live:
            print("acquisition requires ALLOW_LIVE=true and FORTYGUARD_API_KEY", file=sys.stderr)
            return 2
        if args.ledger_path is not None:
            settings = replace(settings, ledger_path=args.ledger_path)
        out_dir = args.out_dir if args.out_dir != Path("fixtures/acquired") else ISSUE23_OUT_DIR
        ledger = build_ledger(settings)
        outcomes = execute_issue23_hotels_resume(
            build_live_client(settings, ledger=ledger),
            ledger,
            out_dir=out_dir,
            polling=settings.polling,
        )
        print(f"completed issue 23 hotel resume: {len(outcomes)} new provider record(s)")
        return 0
    if args.scenario in OSRM_SCENARIOS or args.scenario == "cathedral-governors-palace-buildings":
        if args.out_dir.parent and not args.out_dir.parent.is_dir():
            parser.error(f"output parent does not exist: {args.out_dir.parent}")
        osrm_client = OsrmClient(
            HttpOsrmTransport(
                settings.osrm.base_url,
                user_agent=settings.osrm.user_agent,
                timeout_seconds=settings.osrm.timeout_seconds,
            )
        )
        overpass_client = OverpassClient(
            HttpOverpassTransport(
                settings.overpass.endpoint,
                user_agent=settings.overpass.user_agent,
                timeout_seconds=settings.overpass.timeout_seconds,
            ),
            max_attempts=settings.overpass.max_attempts,
            retry_delay_seconds=settings.overpass.retry_delay_seconds,
        )
        if args.scenario in OSRM_SCENARIOS:
            outcome = acquire_osrm_fixture(
                OSRM_SCENARIOS[args.scenario], osrm_client, out_dir=args.out_dir
            )
        else:
            cathedral_path = args.out_dir.parent / "osrm" / "cathedral-governors-palace.json"
            if not cathedral_path.is_file():
                parser.error(f"Cathedral OSRM fixture is required first: {cathedral_path}")
            routes = normalize_response(
                json.loads(cathedral_path.read_text(encoding="utf-8")),
                provider_instance="fossgis-routed-foot",
            )
            outcome = acquire_overpass_building_fixture(
                routes, overpass_client, out_dir=args.out_dir
            )
        print(f"acquired {args.scenario}: {outcome.fixture_path}")
        print(f"retrieved {outcome.record.retrieved_at}, data date {outcome.record.data_date}")
        return 0
    if not settings.allow_live:
        print("acquisition requires ALLOW_LIVE=true and FORTYGUARD_API_KEY", file=sys.stderr)
        return 2
    if args.ledger_path is not None:
        settings = replace(settings, ledger_path=args.ledger_path)

    ledger = build_ledger(settings)
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
    print(f"activity {outcome.record.activity_id}, data date {outcome.record.data_date}")
    print(
        f"call logged to {settings.ledger_path or 'in-memory ledger'}; "
        f"{ledger.call_count} call(s) all-time"
    )
    print("run scripts/reconcile_ledger.py for the authoritative credit cost")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
