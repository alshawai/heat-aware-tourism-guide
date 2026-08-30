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

## Keeping The Demo Awake

The free tier sleeps after 15 minutes of inactivity (see
[Free-Tier Boundaries](#free-tier-boundaries)). To keep a sleeping instance from
greeting a reviewer with a cold start, keep inbound traffic flowing at least
once inside every 15-minute window. Two free layers do this without a payment
method; run both for the judging period so a gap in one is covered by the other.

### In-repo GitHub Actions ping

`.github/workflows/keep-warm.yml` requests `GET /health` every five minutes on a
schedule and can also be run on demand from the Actions tab
(`workflow_dispatch`). The repository is public, so scheduled Actions minutes are
free. The workflow needs no secrets, never deploys, and never fails the run on a
bad ping — it emits a warning instead, so a transient outage does not spam
failure notifications. Override the target by setting a repository variable
`KEEP_WARM_URL`; otherwise it pings the demo URL above.

GitHub runs `schedule` triggers only on the default branch and may delay them
when its runners are busy, so treat this layer as best-effort rather than exact.
GitHub also disables scheduled workflows after 60 days without repository
activity; re-enable it from the Actions tab if that lapses before a demo.

### External uptime monitor

A hosted monitor is independent of GitHub's scheduler and can ping more often.
Point either of these at the `/health` URL, which returns without calling
FortyGuard, Overpass, OSRM, or any other provider, so pinging it is cheap:

- **UptimeRobot** (free): add an HTTP(s) monitor named e.g. `Heat demo health`,
  URL `https://heat-aware-tourism-guide-demo.onrender.com/health`, interval
  5 minutes (the free-plan minimum).
- **cron-job.org** (free): create a cronjob with the same URL on a 1-minute
  schedule for tighter coverage than the 15-minute sleep window.

Neither needs credentials — `/health` is public and unauthenticated — so there
is nothing to commit or store as a secret.

### Instance-hours caveat

Keeping the instance awake means it runs continuously and consumes instance
hours as if always-on (about 730 of the 750 free hours per month). That fits
only if `heat-aware-tourism-guide-demo` is the workspace's sole free web
service. If the workspace runs other free web services, a continuously-awake
instance can exhaust the shared 750-hour allowance and suspend every free web
service until the next month. As with the other free-tier limits above this
creates no bill, but it does risk availability, so when in doubt enable
keep-warm only for the active review window and disable it afterward.

### Disabling keep-warm

- GitHub Actions: Actions tab, select **Keep demo warm**, then the `⋯` menu and
  **Disable workflow** (or remove the `schedule` block to keep only manual runs).
- External monitor: pause or delete the monitor in its dashboard.

If every keep-warm layer lapses and the instance does sleep, the frontend is the
final safety net: the hotel ranking flow shows a "Waking the demo server…" state
and automatically retries the request with backoff on a timeout, transport
failure, or `502/503/504`, so a reviewer who arrives during a cold start sees the
result complete on its own instead of a terminal error.

## Warm-Up, Fallback, And Rollback

Beyond the automated [keep-warm layers](#keeping-the-demo-awake), warm the
service manually shortly before a recording by opening the public URL or running
the health check. Allow roughly one minute for a sleeping instance to wake, then
perform the smoke tests again. A warm-up is operational only; it does not disable
the free-tier sleep policy.

If the hosted service is asleep, unavailable, or has a bad frontend build, run
the local fixture flow from `docs/demo-script.md` with networking disabled. If
a deployment regresses, redeploy the last known-good image or commit from
Render's deploy history, then rerun health and browser smoke tests. Keep
`ALLOW_LIVE=false` during recovery. For a persistent provider incident, leave
the public URL unchanged if possible and use the local recording fallback.

See [ADR 0008](adr/0008-separated-public-fixture-and-protected-live-deployments.md)
for the separation, authentication, ledger, Render, and rollback rationale.
