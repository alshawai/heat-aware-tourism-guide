# How To Record The Demo

This is the operational recipe for producing the submission recording. What
to say while recording — the narration, the deterministic scene order, and
the fallback handling — is the
[demo script](../demo-script.md). This guide covers everything around it:
preparation, environment choice, and post-recording checks.

## Choose the recording environment

Two supported environments, in preference order:

1. **Hosted public fixture deployment**
   (<https://heat-aware-tourism-guide-demo.onrender.com/>). Judges can also
   open this URL themselves. Requires wake-up handling (below).
2. **Local fixture run** — the deterministic fallback. Same fixture data,
   same product states, no network dependency beyond browser OSM tiles.

Record locally when the hosted service is asleep, degraded, or has a bad
frontend build; the committed fixtures make the two runs equivalent at the
product level.

### Known hosted-demo state at time of writing

The hosted curated form pins a fixed request date (currently `2026-08-23`)
while every committed trip fixture is dated `2024-07-15`. Until the pinned
date is corrected to match the fixture, submitting the hosted curated trip
returns the explicit `scenario_unavailable` state, and the hosted UI does not
offer the alternate scenarios. Before recording against the hosted demo,
either correct the pinned date in `frontend/src/screens/TripSetupScreen.tsx`
(`PUBLIC_FIXTURE_DATE`) and redeploy, or record the primary flow locally
(where the date field is editable — set it to `2024-07-15`). The hotel
ranking flow is date-independent and works on the hosted demo either way.

## Prepare the environment

1. **Quality gates.** From a clean checkout of the commit being demoed:

   ```bash
   npm run python:test
   npm run python:test:integration
   npm run frontend:test
   npm run typecheck
   npm run frontend:build
   npm run e2e
   ```

   (`npx --prefix frontend playwright install chromium` once, if needed.)

2. **Local run (if recording locally).** Two terminals:

   ```bash
   ALLOW_LIVE=false .venv/bin/uvicorn app.main:app --reload
   ```

   ```bash
   npm run frontend:dev
   ```

   Record the browser at `http://127.0.0.1:5173`. Optionally disable all
   non-loopback traffic in the browser or recording VM: the fixture flow
   makes no provider requests (the Playwright suite proves this by aborting
   every non-loopback route).

3. **Hosted run (if recording hosted).** Follow
   [How to deploy](deploy.md): check keep-warm layers are active, manually
   warm the service, and rerun the smoke tests. Allow roughly one minute for
   a sleeping free-tier instance to wake before starting the recording.

4. **Fixtures.** Confirm the canonical date `2024-07-15` and window 08:00 to
   20:00 reproduce the canonical analysis, and that the three alternate
   scenarios and the unavailable state behave as scripted.

## Record

1. Start the recording at the trip setup screen; the health banner should
   read "Fixture replay".
2. Follow [the demo script](../demo-script.md) scene order exactly — it is
   deterministic by design.
3. Do not improvise provider explanations; every claim is worded to match
   what the data provenance supports (fixture replay, returned alternatives,
   modeled shade).
4. Keep the full recording inside roughly five minutes.

## Handle problems during recording

- **Hosted service asleep or slow:** wait out the wake window, or switch to
  the local flow and note the switch in the recording.
- **Map tiles missing:** continue; browser OSM tiles are allowed but not a
  readiness dependency. A missing basemap does not invalidate the fixture
  demo.
- **Unexpected unavailable state:** the explicit unavailable contract is a
  product feature — follow the demo script's fallback scene to show it
  deliberately, then restore the canonical setup and finish the primary
  flow.
- **Budget/503 errors:** impossible in fixture mode. If seen on a maintainer
  live instance, stop; that environment is not for the public recording.

## Verify after recording

1. The recording shows: trip setup, best-time evidence and recommended hour,
   hotel ranking with provenance, route comparison with coverage and
   decision state, one deliberate unavailable state, and the restored
   canonical result.
2. No frame shows live provenance, provider credentials, or a claim of
   global route optimality.
3. The hosted health check still passes, and keep-warm remains configured
   for the judging window (see [How to deploy](deploy.md) for disabling it
   afterwards).
