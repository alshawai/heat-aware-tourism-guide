# Fixture Demo Script

The narration, scene order, and fallback handling for the submission
recording. Preparation (environment choice, wake-up, post-recording checks)
is in [How to record the demo](how-to/record-the-demo.md). Target length:
four to five minutes.

Every claim in the narration is worded to match what the data provenance
supports. Do not improvise stronger claims while recording.

## Deterministic flow

The recording follows this exact sequence every time:

1. Trip setup with the canonical date `2024-07-15` and the 08:00-20:00
   window.
2. Best-time evidence and the selected recommendation hour.
3. Hotel ranking and the district provenance.
4. Returned walking routes: geometry, heat evidence, coverage, and the
   explicit route decision state.
5. One alternate scenario (San Fernando Cathedral to Spanish Governor's
   Palace) showing two returned routes and no recommendation under weak
   shade evidence.
6. One deliberate unavailable state, then the restored canonical result.

## Environment

**Primary — hosted fixture demonstration:**
<https://heat-aware-tourism-guide-demo.onrender.com/>. The free service
sleeps after 15 minutes without traffic; allow about one minute for its
first load, and warm it before recording.

**Hosted deployment:** the hosted curated form pins the committed fixture date
`2024-07-15`. The hosted deployment is intentionally limited to the canonical
public fixture; use the local fixture run for alternate and unavailable scenes.

**Deterministic fallback — local fixture run:**

```bash
ALLOW_LIVE=false .venv/bin/uvicorn app.main:app --reload
npm run frontend:dev
```

Open the frontend, use the curated trip, and enter `2024-07-15` as the
date. The local flow supports every scene below, including the alternate
scenarios and the unavailable state.

## Scene-by-scene narration

### Scene 1 — Opening (trip setup)

> "This is the Heat-Aware Tourism Guide, a trip planner for hot-weather
> city visits. I'm planning the canonical demonstration trip: walking from
> the Menger Hotel to The Alamo in Downtown San Antonio. The banner shows
> the server is running in fixture mode — every result you'll see is
> replayed from committed provider data with its provenance attached, and
> the demo makes no live provider calls."

Show the health banner reading "Fixture replay". Enter date `2024-07-15`
(if the form allows) and leave hours at 08:00 to 20:00.

### Scene 2 — Best time

> "First: when to go. The analysis returns hourly heat evidence for my
> window and recommends a visit hour with its reason. The recommendation is
> hour-only — the provider's environmental series carries a timezone
> inconsistency, so the product deliberately avoids claiming an exact
> timestamp it cannot support."

Point at the recommended hour, the hourly evidence, and the hour-only note.

### Scene 3 — Hotel ranking

> "Second: where to stay. One district-level heat analysis ranks the
> downtown hotels. Each hotel shows its heat components — night heat, hot
> hours, persistence, and day heat — as candidate-relative percentiles, with
> the weights visible and adjustable. These weights are product defaults,
> not scientific truths."

Point at the component values, a percentile, and the weights summary.

### Scene 4 — Route comparison

> "Third: how to walk there. The routing provider returned one valid
> pedestrian route for this request, so the product shows that route with
> limited-comparison wording — it never invents a second route, and it never
> claims any route is globally optimal. The route's heat evidence, coverage,
> and the explicit decision state are all shown with the data date."

Open the route comparison. Point at the map geometry, the heat label, and
the decision wording.

### Scene 5 — Alternate scenario (local flow)

Switch to "Explore another trip", select San Fernando Cathedral as origin
and Spanish Governor's Palace as destination (hours pin to 10:00-17:00),
and analyze.

> "Here the provider returned two routes. The corridor's building-height
> evidence is weak, so the product keeps every route and metric visible but
> makes no recommendation — the traveler compares the trade-offs. Weak
> evidence yields honesty, not a guess."

Point at both route cards, the weak-coverage notice, and the absence of a
recommended badge.

### Scene 6 — Unavailable state

Change the trip date (or window) to a non-fixture value and analyze once.

> "Finally, what failure looks like. There's no fixture for this setup, so
> the product returns an explicit unavailable state with recovery guidance —
> never an empty success. Restore the canonical setup and the analysis
> returns."

Restore `2024-07-15` (and the canonical window) and re-run the canonical
analysis so the recording ends on the working result.

### Scene 7 — Closing

> "Everything you saw ran on committed fixtures through the same domain
> contracts the live path uses — provenance, degradation, and budgets are
> enforced server-side. The repository, documentation, and this fixture set
> are public for inspection."

## Fallback handling

- **Hosted service asleep, slow, or regressed:** record the local fixture
  flow above with the same scenes and narration; note the switch in the
  recording. See the [deployment guide](how-to/deploy.md) for warm-up,
  keep-warm, and rollback procedures.
- **To demonstrate an unavailable fixture deliberately:** change the trip
  date or time window and submit again. The server returns the explicit
  unavailable state rather than an empty success. Restore the canonical
  date and window before the recording ends.
- **Route-provider failure in a maintainer environment:** use an exact cache
  or fixture replay. The result retains its `fixture` or `cache` provenance
  and stale marking. Budget exhaustion remains an HTTP 503 and is never
  converted into ordinary degradation.
- **Missing map tiles:** continue recording; browser OSM tiles are allowed
  but are not a readiness dependency. A degraded basemap does not invalidate
  the fixture demo.

## Verification

Run the offline checks before recording:

```bash
npm run typecheck
npm run test
npm run frontend:build
```

The fixture flow makes no FortyGuard, Overpass, or OSRM requests. Live
provider acquisition is a separate maintainer operation and must not be
used for the public recording.
