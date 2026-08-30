# Reference: Commands

All npm scripts route Python through `scripts/python-tool.mjs`, which
resolves the repository virtual environment (`.venv/bin/python` on Unix,
`.venv\Scripts\python.exe` on Windows) — the same interpreter the commands
below assume when run directly.

## Quality gates

| Command                                          | What it runs                                           |
| ------------------------------------------------ | ------------------------------------------------------ |
| `npm run python:format:check`                    | `ruff format --check app tests`                        |
| `npm run python:lint`                            | `ruff check app tests`                                 |
| `npm run python:typecheck`                       | `mypy app tests`                                       |
| `npm run python:test`                            | `pytest -q -m "not integration"` (unit tier)           |
| `npm run python:test:integration`                | `pytest -q -m integration` (fixture-backed HTTP suite) |
| `npm run frontend:format:check`                  | `prettier --check frontend`                            |
| `npm run frontend:lint`                          | ESLint (zero warnings allowed)                         |
| `npm run frontend:typecheck`                     | `tsc --noEmit`                                         |
| `npm run frontend:test`                          | Vitest                                                 |
| `npm run frontend:build`                         | Vite production build                                  |
| `npm run e2e`                                    | Playwright fixture flow (see below)                    |
| `npm run format:check`                           | `prettier --check .` (whole repository)                |
| `npm run format`                                 | `prettier --write .`                                   |
| `npm run typecheck`                              | Python + frontend typechecks                           |
| `npm run test`                                   | Python unit + frontend unit tests                      |
| `.venv/bin/python -m pip_audit`                  | Python dependency audit                                |
| `npm audit --audit-level=high`                   | Root Node dependency audit                             |
| `npm audit --prefix frontend --audit-level=high` | Frontend dependency audit                              |

Every automated check sets or retains `ALLOW_LIVE=false` and requires no
provider credentials.

### End-to-end fixture flow

```bash
npx --prefix frontend playwright install chromium   # once
npm run e2e
```

Playwright starts the fixture-backed backend itself
(`uvicorn app.main:app` on `127.0.0.1:8000`, `ALLOW_LIVE=false`), blocks
every non-loopback browser request, and drives all four trip scenarios
through the visible UI.

## Development servers

| Command                | Serves                                                                                 |
| ---------------------- | -------------------------------------------------------------------------------------- |
| `npm run backend:dev`  | FastAPI with reload at `http://127.0.0.1:8000`                                         |
| `npm run frontend:dev` | Vite dev server at `http://127.0.0.1:5173`, proxying `/api` and `/health` to port 8000 |

Equivalent direct invocation:

```bash
ALLOW_LIVE=false .venv/bin/uvicorn app.main:app --reload
```

After `npm run frontend:build`, the backend alone serves the whole product
at `http://127.0.0.1:8000`.

## Maintenance scripts (`scripts/`)

Maintainer acquisition and research tools. The FortyGuard paths are
credential-gated and billable; see
[How to acquire fixtures](../how-to/acquire-fixtures.md).

| Command                                                                                          | Network                                            | Purpose                                                                                                                                                                                                                                                                   |
| ------------------------------------------------------------------------------------------------ | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `python scripts/acquire_fixture.py --scenario <name>`                                            | FortyGuard / OSRM / Overpass (depends on scenario) | Acquire one sanitized fixture pair plus sidecar. Scenarios: `tcm-historical`, `tcm-forecast`, `exceedance-historical`, `env-params-anchor35`, `canonical-menger-alamo`, `main-plaza-market-square`, `cathedral-governors-palace`, `cathedral-governors-palace-buildings`. |
| `python scripts/acquire_fixture.py --plan-issue-23` / `--execute-issue-23`                       | FortyGuard                                         | Inspect or run the staged nine-activity issue 23 plan.                                                                                                                                                                                                                    |
| `python scripts/acquire_fixture.py --execute-issue-23-hotels-resume`                             | FortyGuard                                         | Resume the three hotel activities.                                                                                                                                                                                                                                        |
| `python scripts/acquire_fixture.py --execute-issue-23-canonical-env-recovery --activity-id <id>` | FortyGuard                                         | Status-only recovery of a prior env-params activity (ledger-preserving).                                                                                                                                                                                                  |
| `python scripts/generate_trip_snapshots.py [--overwrite]`                                        | none                                               | Regenerate `fixtures/trips/*.trip.json` from committed inputs with hash verification.                                                                                                                                                                                     |
| `python scripts/reconcile_ledger.py [--start D] [--end D]`                                       | FortyGuard account endpoint                        | Append the authoritative credit total for a window to the ledger.                                                                                                                                                                                                         |
| `python scripts/fortyguard_usage.py [--start D] [--end D]`                                       | FortyGuard account endpoint                        | Read-only credit usage report; prints nothing secret.                                                                                                                                                                                                                     |
| `python scripts/lidar_corridor_probe.py [--download] [--city …]`                                 | USGS TNM API                                       | Record lidar coverage metadata (and optionally LAZ tiles) for the bounded corridors.                                                                                                                                                                                      |
| `python scripts/derive_lidar_corridor_stats.py <file.laz>`                                       | none                                               | Research-only LAZ screening stats (needs `laspy[lazrs]` in a local research env).                                                                                                                                                                                         |
| `python scripts/validate_building_lidar_heights.py <osm.xml> <file.laz> [--route-json …]`        | none                                               | Compare OSM building heights against lidar-derived estimates.                                                                                                                                                                                                             |

Dates are ISO (`YYYY-MM-DD`). `--ledger-path` overrides
`FORTYGUARD_LEDGER_PATH` for the run.

## Direct backend access

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
```

API request/response shapes for `curl`-level smoke tests are in the
[API reference](api.md).

## Git hooks

`npm install` enables Husky. Each commit runs lint-staged (Prettier on
staged files; ruff format/check --fix on staged Python), then the local
type checks and unit tests. CI additionally runs the integration suite,
the Playwright flow, and the dependency audits.
