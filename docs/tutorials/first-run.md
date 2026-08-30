# Tutorial: From Clone To First Fixture-Backed Run

This tutorial takes a new contributor from a fresh clone to a working,
fixture-backed run of the Heat-Aware Tourism Guide in about fifteen minutes.
Everything here runs offline: no provider credentials, no FortyGuard account,
and no billable API calls. Live provider execution is a separate maintainer
operation described in
[How to configure live mode](../how-to/configure-live-mode.md).

You will:

- install the Python and Node toolchains,
- start the FastAPI backend and the React/Vite frontend,
- run the canonical Menger Hotel to The Alamo trip against committed
  fixtures,
- try one alternate scenario and one explicit unavailable state,
- run the offline quality gates.

## What you need first

- **Git.**
- **Python 3.12.** The Docker runtime image pins Python 3.12; use the same
  version locally.
- **Node.js 22.** The frontend build and the repository tooling (Prettier,
  Husky, lint-staged, Playwright) run on Node 22.
- A POSIX shell. Paths below use `.venv/bin/python`; the npm scripts wrap
  this and also resolve `.venv\Scripts\python.exe` on Windows.

No API keys. The default execution mode is fixture replay, enforced by
`ALLOW_LIVE=false`.

## Step 1: Clone and create the virtual environment

```bash
git clone https://github.com/alshawai/heat-aware-tourism-guide.git
cd heat-aware-tourism-guide
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

This installs the FastAPI application and its dev tooling (pytest, ruff,
mypy) into the repository virtual environment. Always invoke this interpreter
directly (`.venv/bin/python`); the npm scripts do the same through
`scripts/python-tool.mjs`.

## Step 2: Install the Node tooling

```bash
npm ci
npm ci --prefix frontend
```

The root install provides the shared quality-gate tooling; the frontend
install provides Vite, ESLint, TypeScript, Vitest, and Playwright. Installing
at the root also enables the Husky pre-commit hook.

## Step 3: Start the backend

```bash
ALLOW_LIVE=false .venv/bin/uvicorn app.main:app --reload
```

The API now serves at `http://127.0.0.1:8000`. Confirm it is healthy and in
fixture mode:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
```

The response reports `"mode": "fixture"` and
`"execution_capability": "fixture-only"`. `ALLOW_LIVE=false` is the default;
stating it explicitly documents intent. With no `FORTYGUARD_API_KEY`
configured, live execution is impossible, not merely discouraged.

## Step 4: Start the frontend

In a second terminal:

```bash
npm run frontend:dev
```

Open `http://127.0.0.1:5173`. The Vite development server proxies `/api` and
`/health` to the backend on port 8000, so no other configuration is needed.

Prefer one service? Build the frontend once and let FastAPI serve it:

```bash
npm run frontend:build
```

Then use `http://127.0.0.1:8000` directly; the backend serves the built
assets and falls back to the SPA index for deep links. This is the same
layout the public deployment uses.

## Step 5: Run the canonical trip

The page opens on the trip setup screen with the curated trip already
selected: Menger Hotel to The Alamo, 08:00 to 20:00.

**Set Date to `2024-07-15`.** This matters: every committed trip fixture was
acquired for `2024-07-15`, and the fixture adapter matches the exact request
identity, including the date. The form's default date does not match any
fixture, so leaving it untouched returns an explicit unavailable state rather
than a wrong answer. See [How fixtures are matched](#how-fixtures-are-matched)
below.

Click **Analyze trip**. You should see, in order:

1. The **trip analysis** summary with a "Fixture replay" execution banner and
   the fixture data date in the provenance footer.
2. **Best time**: hourly heat evidence for the window and the recommended
   visit hour, with an hour-only recommendation note (the environment series'
   provider timezone is inconsistent with `America/Chicago`, so the product
   recommends an hour, not an exact timestamp).
3. **Hotel ranking**: ranked Downtown San Antonio hotels with component
   values and percentiles.
4. **Route comparison**: one returned walking route on the map. The canonical
   routing request genuinely returned a single route, so the product shows it
   with limited-comparison wording instead of inventing a second route.

No network request to FortyGuard, Overpass, or OSRM was made. Every result
came from `fixtures/` through the same domain schema the live path uses.

## Step 6: Try an alternate scenario and an unavailable state

Still on the trip setup screen, click **Explore another trip**. Search and set
**San Fernando Cathedral** as origin and **Spanish Governor's Palace** as
destination. Selecting this place pair pins the fixture's date and hours
(`2024-07-15`, 10:00-17:00). Analyze again: this scenario returns two routes,
and because the building-height evidence along the corridor is weak, the
product shows both routes with all metrics but **no route recommendation**.
That is the intended weak-evidence behavior, not a failure.

Finally, change the date to any other value and analyze once more. The
response is an explicit `scenario_unavailable` state with recovery guidance —
never an empty success. Restore `2024-07-15` when done.

## Step 7: Run the offline quality gates

Confirm your clone passes the same checks CI runs:

```bash
npm run python:test
npm run python:test:integration
npm run frontend:test
npm run typecheck
npm run frontend:build
```

The full command list, including Playwright browser installation for the
end-to-end fixture flow, is in the
[commands reference](../reference/commands.md). All automated checks run with
`ALLOW_LIVE=false` and require no credentials.

## How fixtures are matched

The fixture adapter matches a trip request against each committed fixture's
sidecar `request_configuration` — mode, landmark and district names, date,
start and end hour, cautious flag, and origin/destination coordinates
(compared with a tolerance of `1e-7` degrees). Filenames are never matching
identity. Zero matches return `scenario_unavailable`; duplicate matches are a
hard error. The full rules, including provenance sidecar structure, are in
[ADR 0004](../adr/0004-fixture-cache-provenance-ledger.md) and the
[fixture acquisition guide](../how-to/acquire-fixtures.md).

## Where to go next

- [How to record the demo](../how-to/record-the-demo.md) and the
  [demo script](../demo-script.md) with narration.
- [How to deploy](../how-to/deploy.md) the public fixture service.
- [Environment variables](../reference/environment-variables.md) and the
  [API reference](../reference/api.md).
- [Why the product is built this way](../explanation/architecture.md).
