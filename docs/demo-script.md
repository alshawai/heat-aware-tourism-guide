# Fixture Demo Script

## Primary Scenario

Open the hosted fixture demonstration at
<https://heat-aware-tourism-guide-demo.onrender.com/>. The free service sleeps
after 15 minutes without traffic, so allow about one minute for its first load.

For an offline fallback, run the unified fixture-backed application locally:

```bash
ALLOW_LIVE=false .venv/bin/uvicorn app.main:app --reload
npm run frontend:dev
```

Open the frontend and submit the curated trip from Menger Hotel to The Alamo.
Use the committed San Antonio fixture and show these states in order:

1. Trip setup with the canonical date and time window.
2. Best-time evidence and the selected recommendation hour.
3. Hotel ranking and the district provenance.
4. Returned walking routes, their geometry, heat evidence, coverage, and
   explicit route decision state.

The route comparison is limited to routes returned by OSRM. The application
must not describe a route as globally optimal.

## Fallback Path

To demonstrate an unavailable fixture, change the trip date or time window and
submit again. The server must return an explicit unavailable state rather than
an empty success response. Restore the canonical date and window before the
recording ends.

For a route-provider failure in a maintainer environment, use an exact cache or
fixture replay. The result must retain its `fixture` or `cache` provenance and
mark stale replay appropriately. Budget exhaustion remains an HTTP 503 and is
not converted into ordinary degradation.

## Verification

Run the offline checks before recording:

```bash
npm run typecheck
npm run test
npm run frontend:build
```

The fixture flow makes no FortyGuard, Overpass, or OSRM requests. Live provider
acquisition is a separate maintainer operation and must not be used for the
public recording. Browser OSM tiles are allowed, but they are not a readiness
dependency; a missing basemap does not invalidate the fixture demo. For hosted
deployment smoke tests, health, warm-up, and rollback procedures are in the
[deployment guide](deployment.md).
