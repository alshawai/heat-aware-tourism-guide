# Heat-Aware Tourism Guide

## Status

This is the implementation source of truth for the FortyGuard '26 Hackathon
submission. The team confirmed the decisions in this document through a
grilling session on 23 August 2026.

The implementation deadline is the end of day 4 of the seven-day window. Days
5-7 are reserved for validation, deployment, repository cleanup, recording,
rehearsal, and submission fixes.

## Product Decision

Heat-Aware Tourism Guide helps a traveler make three connected decisions in a
hot US city:

1. When to visit a landmark.
2. Which hotel neighborhoods have lower outdoor heat exposure.
3. Which available walking route has the lower modeled heat and shade burden.

The product's strongest proof point is the Neighbourhood Heat Score: one
district-level heat analysis ranks multiple hotels, while local computation
handles hotel lookup, percentiles, ties, and re-weighting.

The product supports travelers visiting US cities. It is not restricted to US
residents. FortyGuard's documented geographic coverage is currently US-only,
so the product truthfully limits supported live data to the United States.

## Users And Modes

The primary audience is a leisure traveler visiting an unfamiliar hot city.
An optional conservative-guidance setting supports users who want more cautious
recommendations. It is not a clinical risk assessment and does not provide
medical advice.

The application has two modes:

- **Curated mode:** the public deployment and recorded demo start with a
  validated San Antonio scenario.
- **Exploratory mode:** maintainers and repository reviewers can create another
  trip by searching for places or selecting origin and destination on the map.
  Live exploratory requests require maintainer configuration and credentials;
  fixture mode reports clearly when a scenario is not available.

The recorded submission is a deterministic video/presentation. Judges do not
change the flow during the recording, but the repository must contain a real,
fixture-backed application that can be inspected and run.

## Geography And Demo

San Antonio, Texas is the primary city. Austin, Texas is the fallback if San
Antonio fails the live validation gates.

The canonical scenario is:

- Origin: Menger Hotel (latitude 29.4245914, longitude -98.4864288 —
  OpenStreetMap relation 1204761 centroid, WGS84).
- Destination: The Alamo (latitude 29.425833, longitude -98.485833 — UNESCO
  World Heritage San Antonio Missions component 006 "Mission Valero / The
  Alamo" central point).
- Hotel district: Downtown San Antonio / Alamo Plaza.
- Optional visual context: River Walk and La Villita.
- Date and visit hour: one historical date captured in the committed fixture.

The pinned coordinates are the identity used by the curated trip request and
the committed trip fixture; fixture matching requires the request to carry
these same values.
Provenance and rejected alternatives are documented in
[issue-40 coordinate research](../research/issue-40-menger-alamo-coordinates.md).
Neither value is a routing-snap observation.

The city is configurable in code, but multi-city support is out of scope for
the product. The final city is locked only after these checks pass:

1. A FortyGuard heatmap completes with populated data.
2. At least five usable, conservatively deduplicated hotels are found.
3. The selected walking corridor has sufficient building-height coverage.
4. A single OSRM request returns usable pedestrian route alternatives.

## User Experience

The product is one responsive React/Vite single-page application with four
primary states:

1. **Trip setup:** curated default, place search, map-click origin, map-click
   destination, date/hour, and optional cautious-guidance setting.
2. **Best time:** hourly heat/comfort evidence, metric and date provenance,
   NOAA category when actual heat index is available, and a recommendation with
   its reason.
3. **Hotel ranking:** ranked hotels, percentile, component values, ties,
   tile resolution, and the provisional weighting configuration.
4. **Route comparison:** all returned route alternatives highlighted on a
   Leaflet map at once, synchronized route cards, distance, heat status,
   modeled building-shadow coverage, data coverage, and the recommended route.

Leaflet uses OpenStreetMap tiles with proper attribution. The map is a primary
interaction surface, not a decorative screenshot. The UI must work on desktop
and mobile, keep route lines and controls readable, and never imply that a
route is globally optimal when it is only the best among returned alternatives.

## Architecture

The deployed system is one service where practical:

```text
React/Vite build -> FastAPI static assets and API
                           |
                           +-- fixture/live execution
                           +-- FortyGuard client and bounded polling
                           +-- OSRM client
                           +-- Overpass acquisition/cache
                           +-- local heat, hotel, and shade computations
```

FastAPI owns provider credentials, external calls, polling, caching, quota
logging, provenance, fallback behavior, and the product-shaped response. The
frontend never calls FortyGuard directly and never receives its API key.

The main endpoint is a product-level trip analysis endpoint, such as
`POST /api/trip/analyze`. Narrow endpoints may expose optional drill-downs, but
the frontend must not orchestrate provider jobs itself.

Fixture and live execution return the same domain schema. The response includes
execution mode and provenance so the UI can distinguish live data, cached data,
and unavailable optional enrichment.

## External Data Contracts

### FortyGuard

The documented API uses `POST /v1/heatmap`, `POST /v1/env_params`, and
`GET /v1/status/{activity_id}`. Calls are asynchronous:

1. Submit a job.
2. Receive an activity ID.
3. Poll at a bounded interval while processing.
4. Consume the completed result or record failure.

The client must handle validation/auth/plan errors, temporary not-found status
immediately after submission, rate limiting, server errors, and failed jobs.
Failed jobs must not be retried indefinitely. Successful responses are cached
and logged with activity ID, request configuration, timestamps, status, and
sanitized response metadata.

The provided hackathon access is Premium, with approximately 2,000,000 credits
per teammate and roughly 6,000,000 credits available collectively. Exact job
costs and rate limits remain operational facts to measure, not assumptions. The
cost ledger must therefore record actual usage during acquisition.

The core uses:

- `tcm` heatmap data as a provider temperature metric in Celsius.
- `env_params` `heat_index_celsius` when available for NOAA classification.
- `exceedance` and `persistence` for district heat framing.
- Optional satellite canopy or street-view segmentation only as enrichment.

`tcm` must never be silently treated as NOAA Heat Index. If actual heat index
is unavailable, the UI displays the Celsius metric and a separately named
product band. The initial product-only `tcm` bands are lower (below 30 C),
moderate (30 to below 35 C), higher (35 to below 40 C), and very high (40 C
and above). These labels and thresholds are product policy, not NOAA/NWS
categories or clinical guidance.

### OSRM

OSRM is consumed, not implemented. One request per trip asks for a pedestrian
route and alternatives with full GeoJSON geometry. Alternatives are not
guaranteed, so the application accepts one or more returned routes and compares
only those routes. It never makes a second routing request for the same trip
and never fabricates route variants.

The request cache key includes origin, destination, routing profile, options,
provider instance, and relevant data/configuration version.

### OpenStreetMap And Overpass

Overpass provides bounded hotel and building queries. Successful results are
cached immediately and retain the OSM base timestamp and source object IDs.
The client uses a descriptive User-Agent, handles HTTP 429 with a delay, and
does not make per-hotel or per-building live requests.

Hotels are discovered from `tourism=hotel` nodes, ways, and relations. Object
identity, relation membership, names, addresses, websites, and operators are
used before proximity as a deduplication heuristic. Nearness alone must not
silently merge distinct hotels.

Building height precedence is:

1. Valid explicit `height` in metres.
2. Valid `building:levels` multiplied by the documented approximate 3 m/level.
3. Unknown.

`building:part` geometries are considered where available. Inferred heights
are marked as inferred; they are never presented as measured values.

## Heat And Safety Policy

When `heat_index_celsius` is available, the UI uses NOAA/NWS category names and
boundaries:

| Category        |   Heat index |
| --------------- | -----------: |
| Caution         |  26.7-32.2 C |
| Extreme caution |  32.2-40.6 C |
| Danger          |  40.6-54.4 C |
| Extreme danger  | above 54.4 C |

These are Heat Index categories, not a claim that FortyGuard `tcm` is Heat
Index. The app avoids calling any result comfortable or safe. Preferred
phrasing is “no elevated heat concern detected by the selected metric” and
“more cautious guidance selected.”

The optional cautious setting shifts the product action threshold one band
earlier. This is an explicit team safety policy supported by general public
health guidance, not an official medical transformation. It does not collect a
diagnosis, medication, or clinical profile. Standard guidance takes action from
the third band; cautious guidance takes action from the second band. The
measured value and displayed observation band do not change. Recommendations
prefer returned hours or routes below the applicable action threshold, then the
lowest selected-metric value. Route confidence remains the higher-priority
guardrail: when route comparison confidence is insufficient, the product
preserves the returned route evidence and makes no recommendation instead of
applying a shortest-route fallback.

## Best-Time Decision

For a landmark and date, the backend obtains an hourly series once, caches it,
and reuses it for the route decision and display. The recommendation selects
the coolest available periods according to the applicable metric/category and
shows the reason and source.

Exceedance and persistence are framing metrics, not hidden substitutes for the
hourly curve. Their threshold, initially 35 C for the product framing, is a
declared product choice and must be visible in provenance.

## Hotel Decision

A district heatmap is fetched per required analytic component, not once per
hotel. Hotels are assigned values through local point-in-tile lookup. Hotel
count therefore does not multiply FortyGuard jobs.

The provisional default weights are:

- Night heat: 35%.
- Hot hours: 25%.
- Persistence: 20%.
- Day heat: 20%.

These weights are product defaults, not scientific or satisfaction-derived
truth. The implementation must expose components, ranking/percentiles, ties,
tile resolution, and local re-weighting. It must not present an absolute score
out of 100 as if it were objective.

The team will research relevant urban-heat, thermal-comfort, and traveler
satisfaction evidence, then run a sensitivity analysis. Hotel review sentiment
alone is insufficient evidence because room quality, service, price, season,
and many other factors confound it.

## Route Decision

The route flow is:

1. Fetch OSRM alternatives exactly once.
2. Retain only the valid returned routes and compare those routes only.
3. If every returned route is at most the configurable representative distance,
   reuse the selected-hour landmark TCM value with `landmark_reuse` evidence.
4. If any returned route is longer, request one shared rectangular corridor AOI
   for the recommendation hour and aggregate a conservative maximum TCM value
   per route. The shared heat request is never a second routing request.
5. If comparable heat is mild, recommend the shortest returned route.
6. If any comparable route has elevated heat, expose all evidence with a
   `shade_required` state and defer the final recommendation to modeled shade.
7. A single returned route is shown as `single_route`; zero routes or missing
   route heat evidence produces `no_suitable_returned_route` or
   `heat_unavailable` with an explicit degraded reason.

The initial representative-route threshold is 1,500 m and is configurable. It
is an engineering heuristic, not a scientific boundary. Route heat is evaluated
at `BestTimeResult.recommendation_hour`, so the route and landmark evidence use
the same selected hour.

The shade value is described as “modeled shade estimate, based on OSM building
data.” It is deterministic relative to the model assumptions, but it is not a
measurement of real-world shade. The model does not fully represent trees,
awnings, terrain, sidewalk side, temporary objects, or missing/inaccurate OSM
data.

Every route result includes:

- Distance and duration.
- Full returned route geometry when route comparison is available.
- Heat metric, heat status, per-route coverage, and evidence source.
- Explicit route-set and decision states.
- Modeled building-shadow percentage, if computable in the shade phase.
- Building-height coverage and confidence state when shade modeling is present.
- Whether the route is recommended and why.

## Failure And Fallback Policy

Transient provider failures receive bounded retries and bounded polling. After
failure, the system uses a matching cached fixture when available and exposes
provenance. It never returns an empty success response, retries indefinitely,
or silently substitutes an unrelated scenario.

Specific fallbacks include:

- No live credentials: fixture mode.
- Unavailable fixture for an exploratory trip: explicit unavailable state.
- Fewer OSRM alternatives: compare those returned, including one.
- Weak building-height coverage: show routes, preserve partial shade evidence,
  and make no route recommendation; the traveler compares the trade-offs.
- Premium enrichment unavailable: omit the enrichment without affecting the
  core flow.
- Public deployment: fixture mode only, protecting the shared credit balance.
- Maintainer environment: live mode through server-side environment variables.

## Provenance And Fixture Design

Fixture acquisition is explicit and lives under `scripts/`. It makes the
required FortyGuard, OSRM, and Overpass calls, writes sanitized data, and
records source/provider, request configuration, retrieval time, data date,
activity IDs where safe, response statuses, and transformation version.

The public fixture set contains:

- One complete Menger Hotel to The Alamo scenario.
- Two or three additional supported scenarios in the same San Antonio area.
- Provider payloads sufficient to exercise route, hotel, time, and fallback
  states without network access.

Fixtures contain no API keys or sensitive credentials. The live and fixture
paths use the same domain models and validation rules.

## Testing And Quality Gates

Tests must cover:

- Celsius conversion and NOAA boundary classification.
- Metric-specific classification and `tcm` non-equivalence.
- FortyGuard polling states and bounded failure handling.
- Hotel normalization, tile lookup, percentile ranking, ties, and weights.
- Height parsing, explicit/inferred/unknown precedence, and coverage.
- Solar azimuth/elevation conventions and representative shade cases.
- Short/long route gating and maximum corridor aggregation.
- Weak-coverage route fallback.
- Fixture/live schema parity.
- Frontend build and one fixture-backed end-to-end user flow.

CI runs offline checks only. Live FortyGuard and Overpass requests are manual
acquisition/validation tasks and must never be required for pull requests.

Pre-commit runs fast formatting and staged checks locally. The full CI pipeline
runs Python lint/type/test checks, frontend lint/type/test/build checks, and
available dependency/security checks. Secrets are supplied through local
environment configuration or deployment secrets, never committed.

### CI Follow-Up When The Scaffold Lands

The current CI workflow intentionally checks only repository tooling because the
FastAPI and React/Vite applications do not exist yet. This is a temporary
scaffold state, not the final quality gate. The first agent or teammate who
adds the application scaffold must update `.github/workflows/ci.yml` and this
document together.

The follow-up is complete only when CI runs all of these checks without live
provider access:

- Python formatting and linting, using the project's selected tools.
- Python type checking.
- Python unit and integration tests, including fixture-backed provider flows.
- Frontend formatting and linting.
- Frontend type checking.
- Frontend unit tests.
- Frontend production build.
- Fixture-backed application startup and one end-to-end user flow.
- High-severity dependency/security audit for Python and Node dependencies.

The follow-up agent must also:

1. Add the corresponding local scripts to the Python and Node project
   configuration.
2. Add or update dependency lockfiles and CI dependency caching.
3. Keep live FortyGuard, Overpass, and other metered network calls out of pull
   request CI.
4. Make the pre-commit hook run fast staged formatting plus the appropriate
   local type and test checks once those scripts exist.
5. Run the complete workflow locally or against a GitHub branch and record the
   resulting commands in the Diataxis documentation.

Until this checklist is implemented, the CI status must not be described as
covering application quality gates.

## Deployment

The project requires a public URL because it has a UI. The selected target is a
unified FastAPI deployment serving the built React assets and API from one
Render Docker web service. The checked-in Blueprint provisions the free public
fixture service in Ohio; the deployment guide records its constraints and
operations.

Public deployment is explicitly `APP_PROFILE=public-fixture` with
`ALLOW_LIVE=false`. Live provider mode is a separate future paid deployment,
HTTP Basic protected on every application route except `/health`, with
server-side secrets, one worker and one instance, a persistent finite-budget
ledger, and rollback procedures. A public user must never be able to consume
the team's FortyGuard credits.

The deployment must be smoke-tested before recording. The README retains a
pending URL placeholder until actual provisioning; the local fixture flow is
the fallback. Browser OSM tiles are allowed and do not participate in readiness
checks.

## Team Ownership And Schedule

- **Project/UI owner:** product state model, React/Vite implementation, Leaflet
  interaction, integration, design document, and final user experience.
- **Mohammed Ahmad:** FastAPI service, FortyGuard client, polling, caching,
  fixture acquisition, deployment, and operational configuration.
- **Shahd Ayad:** heat/route/hotel scoring validation, OSM/Overpass data quality,
  tests, research evidence, and demo evidence.
- **All three:** city gates, quota review, code review, deployment validation,
  recording, and final rehearsal.

Schedule:

- **Days 1-2:** scaffold, provider smoke tests, city validation, domain schema,
  fixture acquisition, and minimal UI shell.
- **Days 3-4:** complete core flows, map route comparison, tests, fixture mode,
  CI/pre-commit, and deployment. Feature freeze at end of day 4.
- **Days 5-6:** hardening, responsive checks, research notes, README/docs,
  demo script, recording, and repository review.
- **Day 7:** rehearsal, final fixes only, deployment verification, and
  submission.

## Documentation Structure

`README.md` remains a short repository landing page: purpose, status, public
URL, high-level architecture, prerequisites, and links to detailed documents.
It should not duplicate full setup recipes or reference material.

The documentation will grow according to Diataxis:

- **Tutorial:** get a new contributor from clone to first fixture-backed run.
- **How-to guides:** configure live mode, acquire fixtures, deploy, and record
  a demo.
- **Reference:** environment variables, API/domain schemas, commands, and
  configuration options.
- **Explanation:** cost model, heat metrics, hotel weights, shade assumptions,
  limitations, and architecture decisions.

Required submission artifacts are:

- `docs/design/design-doc.md`.
- Cited research notes under `docs/research/`.
- A concise `README.md` landing page with links.
- `.env.example` with no secrets.
- `docs/demo-script.md` with narration and fallback handling.

## Non-Goals

- Global or non-US live coverage.
- A routing engine or city-wide optimal cool-route search.
- Booking, pricing, availability, or indoor hotel comfort.
- Medical risk scoring or diagnosis.
- Treating segmentation imagery as the core shade measurement.
- Claiming exact real-world shade or a globally optimal route.
- Requiring live network calls for public deployment or CI.
- A multi-city product in the hackathon scope.
