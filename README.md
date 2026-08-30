# Heat-Aware Tourism Guide

Heat-aware trip planning for visitors to hot US cities. The application
combines landmark timing, outdoor neighborhood heat, and walking-route
comparison in one fixture-backed web experience.

**Public demo:** <https://heat-aware-tourism-guide-demo.onrender.com/>

The free Render service sleeps after 15 minutes without traffic, so allow about
one minute for the first load during judging.

## Project Shape

- React/Vite responsive UI with Leaflet map.
- FastAPI orchestration and provider integrations.
- FortyGuard heat data, OSRM walking alternatives, and OpenStreetMap data.
- Fixture mode for public deployment, CI, and offline review.
- San Antonio, Texas as the primary validated scenario; Austin as fallback.

The implementation decisions and constraints are in
[`docs/design/design-doc.md`](docs/design/design-doc.md). External fact checks
are collected in [`docs/research/`](docs/research/).

## Documentation

Detailed contributor setup, live-mode acquisition, deployment, API reference,
and demo instructions are organized under the Diataxis structure:

- [Design explanation](docs/design/design-doc.md)
- [Deployment guide](docs/deployment.md)
- [Deployment decision](docs/adr/0009-separated-public-fixture-and-protected-live-deployments.md)
- [Fixture demo script](docs/demo-script.md)
- [Provider and coordinate research](docs/research/)

## Contributor Quality Gates

Install the Python dependencies into the repository virtual environment, then install the Node tooling:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
npm ci
npm ci --prefix frontend
```

Run the local quality gates:

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

For the browser-level fixture flow, install Chromium once and run Playwright:

```bash
npx --prefix frontend playwright install chromium
npm run e2e
```

`npm install` enables Husky. Each commit formats staged files with lint-staged,
then runs the local Python and frontend type checks and unit tests. CI also runs
the fixture-backed HTTP integration suite and browser flow.

All automated checks set or retain `ALLOW_LIVE=false`. They require no provider
credentials and make no FortyGuard, Overpass, OSRM, or other metered provider
requests. Live acquisition remains an explicit maintainer operation through the
scripts documented below.

## Live Credit Usage

The salvaged quickstart account-usage endpoint is available as a credential-safe
terminal command. Load `FORTYGUARD_API_KEY` into the process environment without
printing it, then run:

```bash
python scripts/fortyguard_usage.py
python scripts/fortyguard_usage.py --start 2026-08-01 --end 2026-08-24
```

The command reports the selected window, total credits, and provider activity
breakdown. It never prints the API key. The source is the quickstart's
`POST /v1/system/fetch-api-key-custom-usage` utility; the original
`notebooks/00_setup.ipynb` remains the reference walkthrough.

## Lidar Corridor Prototype

The official USGS National Map coverage probe records classified lidar
products intersecting the bounded Austin and San Antonio route corridors:

```bash
python scripts/lidar_corridor_probe.py
```

This writes local, gitignored metadata to `data/lidar-prototype/coverage.json`.
It does not download point-cloud binaries. Review the tile metadata and source
dates before adding an opt-in download/derivation workflow.

The local research environment can inspect a downloaded LAZ tile with
`laspy[lazrs]` (the package is not an application dependency):

```bash
python scripts/derive_lidar_corridor_stats.py \
  data/lidar-prototype/laz/USGS_LPC_TX_Central_B2_2017_stratmap17_50cm_2998373a1_LAS_2019.laz
```

For the canonical San Antonio corridor, the bounded OpenStreetMap XML extract
and classified LAZ tile can be compared at building-footprint level with:

```bash
python scripts/validate_building_lidar_heights.py \
  /path/to/san-antonio.osm \
  data/lidar-prototype/laz/USGS_LPC_TX_Central_B2_2017_stratmap17_50cm_2998373a1_LAS_2019.laz
```

Pass the saved OSRM response with `--route-json` to use the full walking route
instead of the endpoint chord.
