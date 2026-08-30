# How To Configure Live Provider Execution

Live execution makes authenticated FortyGuard calls through the server. It is
a maintainer capability: it spends credits, and the public deployment must
never enable it. This guide covers enabling live mode for local maintainer
work and for the separately deployed, access-controlled `protected-live`
instance. The boundary and rationale are in
[ADR 0009](../adr/0009-separated-public-fixture-and-protected-live-deployments.md);
the credit cost model is explained in
[Cost model](../explanation/cost-model.md).

Fixture mode needs none of this. See the
[tutorial](../tutorials/first-run.md) for the offline path.

## What live mode requires

| Requirement                                 | Local maintainer run              | `protected-live` deployment                  |
| ------------------------------------------- | --------------------------------- | -------------------------------------------- |
| `ALLOW_LIVE=true`                           | required                          | required                                     |
| `FORTYGUARD_API_KEY`                        | required                          | required (secret manager)                    |
| `APP_PROFILE`                               | `local` (default)                 | `protected-live`                             |
| `LIVE_AUTH_USERNAME` / `LIVE_AUTH_PASSWORD` | not used                          | required (HTTP Basic)                        |
| `FORTYGUARD_CALL_BUDGET`                    | optional (record-only when unset) | required, positive                           |
| `FORTYGUARD_LEDGER_PATH`                    | optional                          | required, absolute path on a persistent disk |

Startup fails fast when any requirement is missing; the checks live in
`app/settings.py` (`validate_profile_settings`). Setting
`APP_PROFILE=public-fixture` forbids live execution and the API key entirely.

## Configure a local live run

Put the key in the process environment or a local `.env` file (never commit
it; `.env` is gitignored and `.env.example` intentionally ships empty
values):

```bash
export FORTYGUARD_API_KEY="your-key"
export ALLOW_LIVE=true
.venv/bin/uvicorn app.main:app --reload
```

Check the mode:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
```

`"mode"` becomes `"live"` and `"execution_capability"` becomes
`"fixture-and-live"`. A request may still explicitly ask for fixture
execution; `execution_mode` is per request.

Read-only credit reporting is available without enabling anything:

```bash
python scripts/fortyguard_usage.py
python scripts/fortyguard_usage.py --start 2026-08-01 --end 2026-08-24
```

The utility submits the account-level usage request, prints the window, total
credits, and an activity breakdown, and never prints the key.

## Configure the protected live deployment

The protected instance is a separate paid deployment, never the public
Blueprint. For each of the following, use the provider's secret manager, not
committed files:

- `APP_PROFILE=protected-live`
- `ALLOW_LIVE=true`
- `FORTYGUARD_API_KEY` (secret)
- `LIVE_AUTH_USERNAME` / `LIVE_AUTH_PASSWORD` (secrets)
- `FORTYGUARD_CALL_BUDGET` — a finite, positive all-time call count
- `FORTYGUARD_LEDGER_PATH` — an absolute path on a persistent disk

Every route except `GET /health` then requires HTTP Basic authentication.
Run exactly one worker and one instance so the in-process cache and the
append-only ledger stay coherent. Provisioning steps and rollback are in
[How to deploy](deploy.md).

## Budgets and the ledger

- Every submitted live activity is appended to the ledger at
  `FORTYGUARD_LEDGER_PATH` (JSONL). `FORTYGUARD_LEDGER_PATH` set to an empty
  value selects an in-memory ledger only.
- `FORTYGUARD_CALL_BUDGET` counts **calls**, not credits: the provider does
  not price per call, so credit truth comes only from reconciliation. When
  unset, the ledger records without enforcing.
- Optional enrichment has its own UTC calendar-day budget:
  `FORTYGUARD_ENRICHMENT_CALL_BUDGET`. One submitted enrichment activity
  consumes one unit even if it later fails; cache hits and fixture replay
  consume none.
- After acquisition, append the provider's authoritative account total:

  ```bash
  python scripts/reconcile_ledger.py --start 2026-08-01 --end 2026-08-30
  ```

## What changes when live is enabled

- **United States geography gate.** A live trip request whose endpoints fall
  outside the supported US extent receives an explicit
  `unsupported_geography` unavailable response (HTTP 200 with
  `state: "unavailable"`), because FortyGuard's documented coverage is
  US-only.
- **Degradation chain.** On a live-path failure the execution layer replays
  an exact cache entry, then a matching fixture (date-relaxed for forecast
  mode only), otherwise raises an explicit unavailable error. Replays are
  labelled `source: "cache"` or `"fixture"` with `stale: true` and the true
  data date, never presented as a current forecast. Budget exhaustion is an
  HTTP 503 and is never degraded. See
  [ADR 0004](../adr/0004-fixture-cache-provenance-ledger.md).
- **Submit-once.** One `POST` per billable submission; transient transport
  failures are retried as status `GET`s only. See
  [ADR 0003](../adr/0003-bounded-polling-and-404-tolerance.md).

## Safety rules

1. Never commit `.env`, provider keys, Render keys, or Basic credentials.
2. Never set `ALLOW_LIVE=true` on the public fixture deployment; the public
   profile refuses the API key at startup, and bypassing that is a
   product-boundary violation, not a configuration choice.
3. Keep a finite `FORTYGUARD_CALL_BUDGET` on any long-lived live instance.
4. Treat `docs/research/issue-7-san-antonio-provider-validation.md` as the
   source of truth for observed provider behavior, including the
   documented-vs-implemented transport mismatch (`api-key` header vs
   `X-API-Key`).
