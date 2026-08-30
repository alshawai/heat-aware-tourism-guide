# Heat-Aware Tourism Guide

A San Antonio tourism guide that helps a traveler make three connected
decisions in hot weather: when to visit a landmark, which hotel
neighborhoods have lower outdoor heat exposure, and which returned walking
route has the lower modeled heat and shade burden. It combines FortyGuard
urban-heat data, OSRM walking routes, and OpenStreetMap buildings behind one
FastAPI service with a React/Vite map UI.

**Status:** built for the FortyGuard '26 Hackathon. The core flows, fixture
set, quality gates, and deployment are complete; final validation and the
submission recording are the remaining work.

**Public demo:** <https://heat-aware-tourism-guide-demo.onrender.com/>

The demo runs on Render's free tier in fixture mode: it replays committed,
provenance-labelled provider data (canonical date `2024-07-15`) and makes no
live provider calls. It sleeps after 15 minutes without traffic, so allow
about one minute for the first load. Local setup takes about fifteen minutes
in the [tutorial](docs/tutorials/first-run.md).

## Architecture

```text
React/Vite build ──> FastAPI static assets and API
                            │
                            ├─ fixture/live execution ─── provenance, cache, degradation
                            ├─ FortyGuard client ─────── submit-and-poll, bounded polling
                            ├─ OSRM client ───────────── one request, returned alternatives
                            ├─ Overpass acquisition ──── hotels, buildings
                            └─ local decisions ───────── heat policy, hotel ranking, shade
```

The server owns all provider credentials and external calls; the frontend
never calls a provider directly. Fixture and live execution share one domain
schema, and every result carries its execution mode and provenance. See
[Architecture](docs/explanation/architecture.md) and the ADR index.

## Prerequisites

- Git, Python 3.12, and Node.js 22.
- No API keys for fixture mode, CI, or the public demo. Live provider
  execution is a maintainer capability.

## Documentation

Documentation is organized under the Diátaxis structure:

- **Tutorial:** [clone to first fixture-backed run](docs/tutorials/first-run.md)
- **How-to guides:** [configure live mode](docs/how-to/configure-live-mode.md),
  [acquire fixtures](docs/how-to/acquire-fixtures.md),
  [deploy](docs/how-to/deploy.md),
  [record the demo](docs/how-to/record-the-demo.md)
- **Reference:** [environment variables](docs/reference/environment-variables.md),
  [HTTP API](docs/reference/api.md),
  [domain schemas](docs/reference/domain-schemas.md),
  [commands](docs/reference/commands.md),
  [configuration](docs/reference/configuration.md)
- **Explanation:** [architecture](docs/explanation/architecture.md),
  [cost model](docs/explanation/cost-model.md),
  [heat metrics](docs/explanation/heat-metrics.md),
  [hotel weights](docs/explanation/hotel-weights.md),
  [shade assumptions](docs/explanation/shade-assumptions.md),
  [limitations](docs/explanation/limitations.md)
- **Design and research:** [design document](docs/design/design-doc.md),
  [research notes](docs/research/), [demo script](docs/demo-script.md)

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
npm ci
npm ci --prefix frontend
ALLOW_LIVE=false .venv/bin/uvicorn app.main:app --reload   # backend on :8000
npm run frontend:dev                                       # frontend on :5173
```

Open `http://127.0.0.1:5173`, set the trip date to `2024-07-15`, and analyze
the curated Menger Hotel to The Alamo trip. The full walkthrough, including
alternate scenarios and the unavailable state, is in the
[tutorial](docs/tutorials/first-run.md).

## Quality gates

```bash
npm run format:check
npm run python:format:check
npm run python:lint
npm run python:typecheck
npm run python:test
npm run python:test:integration
npm run frontend:format:check
npm run frontend:lint
npm run frontend:typecheck
npm run frontend:test
npm run frontend:build
.venv/bin/python -m pip_audit
npm audit --audit-level=high
npm audit --prefix frontend --audit-level=high
```

Browser-level fixture flow:

```bash
npx --prefix frontend playwright install chromium
npm run e2e
```

`npm install` enables Husky; each commit runs staged formatting plus local
type checks and unit tests. CI additionally runs the fixture-backed HTTP
integration suite, the Playwright flow, and dependency audits. All automated
checks set `ALLOW_LIVE=false`, require no provider credentials, and make no
FortyGuard, Overpass, or OSRM requests. The complete command catalog is in
the [commands reference](docs/reference/commands.md).

## Honesty boundaries

Results are fixture replays or live observations with explicit provenance;
routes are compared only among returned alternatives; shade is modeled from
OSM building data, never measured; heat guidance is product policy, not
medical advice. The full list is in
[Limitations](docs/explanation/limitations.md).
