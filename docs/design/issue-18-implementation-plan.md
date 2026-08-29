# Issue #18 Implementation Plan: OSRM Alternatives And Route Heat Gating

## Goal

Implement one server-owned pedestrian-routing stage that fetches OSRM routes
exactly once, evaluates heat for every valid returned route, recommends the
shortest route under mild heat, and hands elevated-heat alternatives to issue
#19 without fabricating routes or hiding weak evidence.

This plan implements the decisions in ADR 0006. It does not implement modeled
shade or the final route-comparison UI.

## Current Baseline

The merged #14 live path in `TemporalTripAnalysisAdapter` produces a
`BestTimeResult` and retains `recommended_hour_tcm_celsius`. The route section
is still absent with a degraded reason.

Existing reusable foundations are:

- `classify_heat` for standard and cautious route heat policy.
- `LiveAreaHeatmapAdapter` for polygon AOIs and bounded FortyGuard polling.
- normalized `HeatmapResult` tiles and projected polygon lookup.
- `CacheService`, acquisition sidecars, and the ADR 0004 degradation model.
- route-shaped response classes and a small `RouteComparator` prototype.

The existing route contracts are insufficient for #18 because they require a
finite heat value and exactly one recommendation, omit GeoJSON geometry, and
use one confidence field for several unrelated states. The existing area path
is also full-day and its execution cache identity is point-based rather than
AOI-based.

## Settled Behavior

1. Make one OSRM request per trip with the pedestrian profile, alternatives,
   overview, and full GeoJSON geometry.
2. Validate and retain only routes actually returned by OSRM. Do not synthesize
   alternatives.
3. Use the validated FOSSGIS routed-foot service by default, with configurable
   base URL, profile, timeout, options, provider instance, schema version, and
   provider configuration version.
4. If every returned route is at most the configurable representative distance,
   reuse #14's selected-hour landmark TCM value for every route. Make no area
   heatmap request.
5. If any returned route is longer than the threshold, build one buffered
   bounding rectangle around all returned geometries and request one TCM
   heatmap for the selected recommendation hour.
6. Join the shared normalized tiles back to every route locally. Route heat is
   the maximum intersecting value, never an average. Report coverage per route.
7. Mild heat recommends the shortest returned route and performs no shade work.
8. Elevated heat exposes all route evidence and a `shade_required` decision
   state. The lowest-heat route is evidence only; #19 owns the final shaded-route
   recommendation.
9. A single valid route is usable and explicitly marked as the only returned
   route. Zero valid routes, or no route with sufficient evidence, produces
   `no_suitable_returned_route`.
10. OSRM and area-heat degradation is live to exact cache to matching fixture to
    explicit unavailability. A long route never substitutes landmark heat.

## Phase 1: Route Domain And API Contract

### Add provider-neutral route acquisition models

Create `app/domain/routing.py` with validated immutable types:

- `RouteRequest`: origin, destination, pedestrian profile, alternatives flag,
  overview mode, geometry format, steps option, provider instance, and request
  version.
- `RouteGeometry`: ordered WGS84 coordinates with at least two distinct points.
- `ReturnedRoute`: stable response-order identity, distance, duration, and full
  geometry.
- `RouteSet`: one or more normalized routes plus routing provenance.
- pure helpers for shortest-route selection and the any-route-long branch.

Route identities should be deterministic within one provider response, such as
`route-1`, `route-2`, in provider order. They must not pretend to be durable
OSRM object identifiers.

### Reshape trip route results

Update `app/domain/contracts.py` so route states are explicit rather than
inferred from nullable fields:

- Add `RouteSetState`: `alternatives_returned`, `single_route`, and
  `no_suitable_returned_route`.
- Add `RouteDecisionState`: `mild_shortest_recommended`, `shade_required`,
  `heat_unavailable`, and `no_suitable_returned_route`.
- Add full GeoJSON-compatible geometry to each `RouteOption`.
- Make per-route heat value, heat interpretation, and coverage nullable only in
  explicit unavailable states.
- Add per-route `heat_source` or equivalent evidence marker distinguishing
  `landmark_reuse` from `shared_corridor`.
- Make `recommended_id` nullable when shade is required or no recommendation is
  supportable. Require exactly one recommended option only in the mild state.
- Add `lowest_heat_route_id` as evidence when all comparable route heat values
  are available; do not label it recommended under elevated heat.
- Separate route-set quality from heat coverage and future shade confidence.
- Carry routing provenance and heat provenance separately. A combined provider
  string is not sufficient to explain cache/fixture mixtures.

Update response serialization and frontend types/validation so the browser can
accept the new route shape even though issue #20 owns presentation.

### Contract invariants

Add tests proving:

- geometry is valid, ordered, finite WGS84 data;
- no returned route list can be empty unless the explicit no-suitable state is
  used outside the alternatives tuple;
- single-route state contains exactly one route;
- mild state recommends exactly the shortest route;
- shade-required state has no final recommendation;
- lowest-heat evidence is not treated as a recommendation;
- unavailable heat cannot carry a heat interpretation;
- route and aggregate coverage remain within `[0, 1]`.

## Phase 2: OSRM Integration

### Provider package

Create `app/integrations/osrm/` containing:

- `contracts.py`: provider request options, normalized response models, and
  strict OSRM response validation.
- `errors.py`: transport, HTTP, malformed-response, and no-route errors.
- `transport.py`: bounded HTTP GET using the configured timeout and descriptive
  User-Agent.
- `client.py`: URL construction and one-call route loading.

Build the route endpoint in OSRM's required longitude,latitude order while
normalizing response geometry to the repository's chosen coordinate convention
at the boundary. Require:

- `alternatives=true`;
- `overview=full`;
- `geometries=geojson`;
- configured pedestrian profile;
- optional steps only if downstream behavior needs them.

Reject non-`Ok` OSRM codes, missing/empty routes, malformed LineStrings,
non-finite distance/duration, and endpoint/profile mismatches. Accept one route
without manufacturing another.

### Settings and wiring

Extend `app/settings.py` with `OsrmSettings`:

- default base URL for the validated FOSSGIS routed-foot instance;
- profile `foot`;
- timeout;
- descriptive User-Agent;
- alternatives, overview, geometry, and steps options;
- provider instance identifier;
- schema and provider configuration versions;
- representative distance threshold, default `1500.0` m;
- minimum route-heat coverage, default `0.70` as a declared configurable
  product policy, separate from building-height coverage.

Validate settings before startup and document the non-secret variables in the
configuration documentation. Add builders in `app/wiring.py` for transport,
client, execution, and route orchestration.

## Phase 3: OSRM Cache, Fixture, And Degradation

Create `app/services/routing.py` with a `RouteExecution` boundary parallel to
existing provider executions but specific to synchronous OSRM semantics.

The complete cache and fixture identity must include:

- endpoint/base provider instance;
- origin and destination coordinates;
- pedestrian profile;
- alternatives, overview, geometry, and steps options;
- schema version;
- provider configuration version.

Behavior:

- fixture mode requires an exact matching acquisition sidecar;
- live success normalizes, stamps provenance, and caches the provider response;
- live failure tries the exact cache key, then an exact matching route fixture;
- exhausted degradation raises an explicit route-unavailable error;
- route fixtures are never date-relaxed because routing has no forecast date;
- cached and fixture routes retain their true source and stale state.

Add a committed canonical OSRM response fixture and `.acquisition.json`
sidecar. If the fixture is derived from the observed FOSSGIS response, record it
as provider-sourced with its real retrieval metadata; any manually constructed
alternative must remain explicitly synthesized and must not be mixed into a
provider-sourced response.

## Phase 4: Shared Corridor Heat

### AOI request model

Do not force multi-route AOIs through the current point-based
`HeatmapRequest`. Add an area request contract whose complete identity includes:

- canonicalized shared AOI GeoJSON;
- analytic type `tcm`;
- analysis date and selected recommendation hour;
- forecast/historical mode;
- granularity and buffer configuration;
- schema and provider configuration versions.

Extend the FortyGuard area payload builder to support a single-hour filter at
`BestTimeResult.recommendation_hour`. Stamp a new versioned transformation for
multi-route bounding-AOI construction rather than reusing
`route_to_aoi_buffer` unchanged.

### Shared AOI construction

Add a pure helper that:

1. validates every returned LineString;
2. projects all routes into the local UTM CRS;
3. unions their envelopes;
4. applies the configured metre buffer;
5. converts the resulting bounding rectangle back to WGS84;
6. canonicalizes coordinates for stable cache identity;
7. enforces provider vertex and geometry constraints.

Only one area heatmap activity may be submitted for the route set.

### Per-route aggregation

Move or replace raw-dictionary `map_tiles_to_route_segments` with domain-level
aggregation over normalized tiles. For every route:

- buffer route segments in projected coordinates;
- intersect them with normalized tile geometries;
- report covered route/corridor fraction;
- collect intersecting TCM values;
- use the maximum value as route heat;
- mark route heat unavailable when no usable overlap exists or coverage is
  below the configurable route-heat threshold, default `0.70`.

Do not use the current area-weighted segment average as route heat. Area
weighting can help calculate coverage, but the safety value is the maximum.

The aggregate heat gate is elevated when any comparable returned route requires
heat action under `classify_heat(..., cautious=request.cautious)`. This prevents
a cooler alternative from hiding an elevated route. Preserve each route's own
interpretation for display and #19.

## Phase 5: Trip Orchestration

Refactor `TemporalTripAnalysisAdapter` into a clearer orchestration boundary or
inject a route-analysis service into it. Keep provider mechanics outside the
trip adapter.

After #14 builds `BestTimeResult`:

1. Execute OSRM exactly once for request origin/destination.
2. Normalize all valid returned routes and select the shortest.
3. If every route is at most the threshold, assign
   `recommended_hour_tcm_celsius` to each route with `landmark_reuse` evidence.
4. Otherwise execute one shared-AOI heatmap at the recommendation hour and
   calculate each route's conservative maximum and coverage.
5. Apply `classify_heat` to each route using TCM and the request's cautious
   preference.
6. If comparable heat is mild, recommend the shortest returned route and set
   `mild_shortest_recommended`.
7. If heat is elevated, retain all evidence, set `shade_required`, and leave the
   final recommendation empty for #19.
8. If one valid route exists, mark `single_route`; preserve it with explicit
   limited-comparison wording.
9. If zero valid routes or every route lacks sufficient evidence, return the
   explicit `no_suitable_returned_route` route state and a route degradation
   reason.

Failure isolation:

- Best-time failure still stops route heat analysis because the selected hour
  and reusable landmark value are prerequisites.
- OSRM exhaustion leaves `best_time` intact, omits routes, and returns a
  degraded trip response with a route reason.
- Long-branch heat exhaustion preserves normalized routes in an explicit
  heat-unavailable route result, performs no shade work, and does not substitute
  landmark heat.
- Budget exhaustion remains a 503 `budget_exceeded`; do not convert it into an
  ordinary degraded result.
- Hotel absence remains independent until its live trip orchestration is added.

Update `TripAnalysisResponse` degraded-state validation so explicit route
states, rather than only `Confidence.INSUFFICIENT`, determine whether a present
route section requires a degraded reason.

## Phase 6: Fixtures And Provenance

Update the canonical trip fixture and sidecar together:

- preserve the corrected Menger Hotel and Alamo identity;
- include only real OSRM-returned alternatives;
- remove the synthesized placeholder shady route unless it is represented as a
  separate synthesized fixture with truthful provenance;
- include full route geometry;
- include per-route heat, coverage, interpretation, and evidence source;
- include route-set and decision states;
- split OSRM and FortyGuard provenance;
- identify the selected recommendation hour and shared AOI configuration.

For the canonical short trip, all genuine returned routes are expected to stay
below 1,500 m, so fixture execution should demonstrate landmark heat reuse and
zero corridor activities. Add synthetic offline fixtures in tests to exercise
the long shared-AOI branch without making live provider calls.

Update fixture inventory and secret-scanning tests for the new route fixture and
sidecar.

## Phase 7: Test Strategy

### OSRM unit tests

Add focused tests for:

- exact URL and longitude,latitude endpoint ordering;
- alternatives/full/GeoJSON options;
- one request invocation;
- one-route and multi-route normalization;
- no-route code;
- malformed geometry, distance, duration, and JSON;
- timeout and HTTP failure classification;
- cache identity changes for every relevant request/configuration field.

### Route execution tests

Prove:

- live success is cached;
- exact cache replay is marked stale/cached;
- exact fixture replay works;
- mismatched endpoints/profile/options/provider version do not replay;
- failure chain ends explicitly;
- no fixture alternative is fabricated.

### Corridor heat tests

Prove:

- all-short routes perform zero area heatmap calls;
- any-long route performs exactly one area heatmap call;
- the AOI covers every returned geometry;
- each route is evaluated from the same normalized tile set;
- maximum aggregation wins over mean aggregation;
- per-route coverage is calculated independently;
- weak/no overlap is explicit;
- selected-hour payload and cache identity are correct;
- standard and cautious gates reuse `classify_heat`;
- the configurable `0.70` route-heat coverage policy is enforced at its exact
  boundary and remains separate from shade/building coverage.

### Orchestration tests

Extend the temporal trip tests to assert:

- one OSRM request per trip;
- #14's landmark TCM is reused on the all-short branch;
- all returned alternatives are retained;
- mild heat recommends the shortest route;
- elevated heat has no final recommendation and requests shade;
- single route is usable with limited-comparison state;
- zero valid routes produces `no_suitable_returned_route`;
- OSRM failure preserves best-time as a degraded response;
- long-branch heat failure preserves routes but makes heat unavailable;
- provider/cache/fixture provenance combinations remain truthful;
- budget failures retain existing HTTP behavior.

### Frontend compatibility tests

Update response guards and fixtures so Trip Setup accepts all new route states
without presenting issue #20's map/cards yet. Confirm existing Trip Setup tests,
type checking, production build, and fixture end-to-end flow still pass.

## Phase 8: Documentation

- Keep `CONTEXT.md` route terms synchronized with implemented names.
- Keep ADR 0006 as the decision record for shared AOI and recommendation staging.
- Update `docs/design/design-doc.md` to clarify that any long returned route
  triggers one shared AOI when route temperatures are compared.
- Update `docs/design/point-vs-area-heatmap.md` with the multi-route AOI and
  selected-hour request behavior.
- Update README configuration and fixture documentation for OSRM.
- Update issue #18 acceptance wording or add an issue comment documenting the
  accepted refinement from “shortest selects the branch” to “any returned long
  route selects shared corridor analysis.”

## Planned File Map

New files:

- `app/domain/routing.py`
- `app/integrations/osrm/__init__.py`
- `app/integrations/osrm/contracts.py`
- `app/integrations/osrm/errors.py`
- `app/integrations/osrm/transport.py`
- `app/integrations/osrm/client.py`
- `app/services/routing.py`
- `tests/test_osrm_http.py`
- `tests/test_route_execution.py`
- `tests/test_route_heat.py`
- canonical OSRM fixture and acquisition sidecar under `fixtures/`

Primary modified files:

- `app/domain/contracts.py`
- `app/domain/trip.py` or its replacement callers
- `app/integrations/fortyguard/contracts.py`
- `app/integrations/fortyguard/live.py`
- `app/services/execution.py` only if shared execution helpers are extracted;
  keep OSRM execution separate otherwise
- `app/services/trip_adapters.py`
- `app/settings.py`
- `app/wiring.py`
- `frontend/src/types.ts`
- `frontend/src/services/dataClient.ts`
- fixture and orchestration tests
- relevant design and README documentation

## Implementation Order

1. Add failing route-domain and response-contract tests.
2. Implement OSRM contracts, transport, client, and settings tests.
3. Implement route execution cache/fixture degradation and tests.
4. Add hourly multi-route area request and geometry-aware identity.
5. Implement conservative per-route maximum and coverage tests.
6. Integrate route analysis after best-time and prove call counts/fallbacks.
7. Update canonical fixtures, API serialization, and frontend guards.
8. Run focused Python tests, then the full Python suite.
9. Run frontend type check, unit tests, production build, and fixture E2E.
10. Update design docs and issue #18 with the accepted branch refinement.

## Completion Criteria

Issue #18 is complete when one product-level trip request produces truthful
route alternatives and route heat states; OSRM is called at most once; the
all-short path performs no new heat activity; the any-long path performs one
shared selected-hour heat activity; every comparable route uses conservative
maximum TCM evidence; mild heat recommends only the shortest returned route;
elevated heat waits for #19; and all cache, fixture, provenance, failure, and
call-count behavior is proven offline.
