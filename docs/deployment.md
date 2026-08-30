# Deploying The Demo

This is the how-to guide for the public fixture deployment. The repository's
`Dockerfile` builds the React/Vite frontend with Node 22, then installs the
Python 3.12 FastAPI runtime in a smaller final stage. The final image contains
`app`, committed `fixtures`, and `frontend/dist`; it runs one Uvicorn worker on
`0.0.0.0` and uses Render's `PORT` value.

## Free-Tier Boundaries

The [Render Hobby workspace limits](https://render.com/docs/free) currently
include 750 free service hours per month, 5 GB of bandwidth, and 500 pipeline
minutes. A free web service sleeps after 15 minutes without traffic and normally
takes about one minute to wake. These limits are appropriate for a review or
recorded demo, not an always-on or high-traffic service.

Do not add a payment method to the demo workspace merely to keep it awake.
Without payment details, exhausting instance hours suspends free web services,
bandwidth exhaustion spins down workspace services, and pipeline exhaustion
stops new builds while the current deployment remains active. None creates an
unexpected bill. Check current Render documentation and workspace usage before
a scheduled recording because plan limits and suspension behavior can change. See Render's
[billing documentation](https://render.com/docs/billing) before provisioning.

## Provisioning

1. In Render, create a Blueprint from this repository and select
   `render.yaml`.
2. Confirm that it creates only `heat-aware-tourism-guide-demo` in Ohio on the
   free plan. The Blueprint has no secret values.
3. Confirm the service environment is `APP_PROFILE=public-fixture` and
   `ALLOW_LIVE=false`.
4. Let the Blueprint deploy only after repository checks pass. If the provider
   does not recognize `autoDeployTrigger: checksPass`, enforce the same rule in
   the repository branch protection and do not bypass failing checks.

The verified public fixture deployment is
<https://heat-aware-tourism-guide-demo.onrender.com/>. Its first smoke test
confirmed the public profile, built frontend and deep-link fallback, canonical
fixture analysis, hotel ranking, static assets, and rejection of live execution.

## Configuration And Secrets

The public service needs no API keys. Keep `ALLOW_LIVE=false`; setting it to
true requires `FORTYGUARD_API_KEY` and is not a valid public-demo change.
`APP_PROFILE` documents the deployment role and must remain
`public-fixture` for this service. Never commit `.env`, provider credentials,
Render API keys, or HTTP Basic credentials.

The future live deployment is a separate paid Docker service with a persistent
disk mounted for the finite ledger, exactly one worker and one instance, and
HTTP Basic authentication on every application route except the unauthenticated
`/health` probe. Store its provider key and Basic credentials in the provider
secret manager. Set a finite `FORTYGUARD_CALL_BUDGET`, configure an absolute
ledger path on the disk, and retain the ledger across restarts. The cache is
process-local and is lost on restart. Do not share the live service's URL or
secrets with the public Blueprint.

## Health And Tiles

Render checks `GET /health`, which returns status without calling FortyGuard,
Overpass, OSRM, or any other external provider. Browser OSM tiles are allowed
for the map and are not a readiness dependency: a tile-provider outage must
not make `/health` fail or prevent the fixture API from starting. The map may
show a degraded basemap while the demo remains available.

## Smoke Tests

After deployment, replace `SERVICE_URL` with the actual Render URL and run:

```bash
curl --fail --silent --show-error "$SERVICE_URL/health"
curl --fail --silent --show-error "$SERVICE_URL/" | grep -q '<html'
```

Open the URL in a browser, submit the canonical Menger Hotel to The Alamo
fixture trip, and verify that the result shows fixture provenance. Confirm
that a request explicitly asking for live execution is rejected. Repeat the
health check after the service wakes from idle sleep.

## Warm-Up, Fallback, And Rollback

Warm the service manually shortly before a recording by opening the public URL
or running the health check. Allow roughly one minute for a sleeping instance
to wake, then perform the smoke tests again. A warm-up is operational only; it
does not disable the free-tier sleep policy.

If the hosted service is asleep, unavailable, or has a bad frontend build, run
the local fixture flow from `docs/demo-script.md` with networking disabled. If
a deployment regresses, redeploy the last known-good image or commit from
Render's deploy history, then rerun health and browser smoke tests. Keep
`ALLOW_LIVE=false` during recovery. For a persistent provider incident, leave
the public URL unchanged if possible and use the local recording fallback.

See [ADR 0009](adr/0009-separated-public-fixture-and-protected-live-deployments.md)
for the separation, authentication, ledger, Render, and rollback rationale.
