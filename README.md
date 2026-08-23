# Heat-Aware Tourism Guide

Heat-aware trip planning for visitors to hot US cities. The application
combines landmark timing, outdoor neighborhood heat, and walking-route
comparison in one fixture-backed web experience.

**Public URL:** to be added before recording.

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
and demo instructions will be organized under the Diataxis structure as the
application scaffold lands.

## Repository Checks

Repository tooling provides offline Python tests, lint/type checks, formatting,
and dependency audit checks:

```bash
npm install
npm run format:check
npm run python:lint
npm run python:typecheck
npm run python:test
npm audit --audit-level=high
```

Live FortyGuard and Overpass calls are never required by CI. Frontend checks will
be added with the React/Vite scaffold.
