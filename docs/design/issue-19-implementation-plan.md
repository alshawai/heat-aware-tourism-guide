# Issue #19 Implementation Plan: OSM Building Quality And Modeled Route Shade

## Goal

Complete the elevated route-heat stage from ADR 0006 with deterministic,
exact-time modeled building shade. Preserve all returned route evidence, make
OSM limitations explicit, recommend only when the applicable evidence supports
a decision, and avoid all building acquisition when shade is physically
irrelevant at night.

This plan implements ADR 0007. It does not build the route-comparison UI owned
by issue #20.

## Current Baseline

Issue #18 already provides:

- one normalized OSRM route set with full WGS84 geometry;
- per-route distance, duration, TCM, heat coverage, and heat source;
- `lowest_heat_route_id` when route heat is comparable;
- `mild_shortest_recommended` and the elevated intermediate `shade_required`;
- separate routing and heat provenance;
- Shapely and pyproj geometry foundations;
- a bounded Overpass transport, cache service, and acquisition-sidecar model.

The remaining gaps are:

- `BestTimeResult` discards exact TCM `valid_time` and retains only an hour;
- the Overpass client is specialized for hotel queries;
- modeled-shade response fields are placeholders without backend evidence;
- explicit final shade/nighttime/insufficient-comparison states do not exist;
- the legacy `RouteComparator` still encodes the rejected weak-coverage
  shortest fallback.

## Settled Behavior

1. Preserve the exact timezone-aware TCM timestamp selected by best-time
   analysis and the named local timezone. Never manufacture precision when
   selected-hour timestamps disagree.
2. At solar elevation `<= 0`, perform no Overpass request, report building shade
   as `0%` and `not_applicable`, and recommend the coolest returned route.
   Distance and stable identity are tie-breakers only among equal TCM values.
3. At positive solar elevation, make one shared Overpass request for all
   returned routes, requesting both `building` and `building:part` geometry.
4. The shared building AOI uses a configurable 250 m route buffer. The boundary
   and its omitted-beyond-boundary limitation are visible in provenance.
5. Valid explicit OSM `height` wins over valid `building:levels * 3 m`; otherwise
   height is unknown. Explicit, inferred, and unknown quality remain visible.
6. Building parts replace overlapping parent geometry; uncovered parent area
   retains the parent's own height quality.
7. Each route's building-height coverage is the area-weighted known-height
   fraction within its analysis corridor. No mapped footprints means zero
   coverage. The configurable sufficiency default is `0.70`.
8. A daytime comparison is sufficient only when every compared route meets the
   threshold, solar/time evidence is valid, and no potentially relevant OSM
   building geometry was dropped.
9. Sufficient alternatives recommend the highest modeled building-shade
   percentage, then shorter distance, then stable route identity.
10. One sufficiently evidenced route is recommended as the only returned route
    with limited-comparison wording.
11. Weak or uncomputable daytime evidence retains every route and every
    available metric, leaves `recommended_id` null, and explicitly delegates
    comparison to the traveler.
12. Modeled shade is always labelled as an OSM-based estimate, never measured
    shade, and explicitly excludes trees, awnings, clouds, and temporary
    obstructions.

## Phase 1: Preserve Exact Recommendation Time

### Contract changes

Extend the best-time contract with typed temporal evidence rather than deriving
an instant later from `date + hour`:

- timezone-aware `recommendation_time`, serialized as ISO 8601;
- `recommendation_timezone`, preserving the IANA zone name;
- an explicit temporal-evidence state for exact, inconsistent, or unavailable
  evidence so a best-time result can survive while shade becomes insufficient.

The exact state requires a timestamp and named zone. Inconsistent/unavailable
states carry no invented timestamp and include a limitation in provenance.

### Temporal orchestration

When selecting the best hour:

1. Gather all TCM tiles contributing to that hour.
2. Require one unique `valid_time` instant across those tiles.
3. Prefer the env-params series timezone when available.
4. Validate the timestamp's local date, hour, and UTC offset against that IANA
   zone and the trip setup.
5. For the curated TCM-only fallback, use `America/Chicago` as an explicit
   timezone-resolution transformation and validate its offset against the TCM
   timestamp.
6. Preserve disagreement as temporal evidence failure; do not fail the complete
   best-time or route-heat result.

Update fixture normalization so fixture and live paths expose the same exact
contract. Existing fixtures must gain truthful timestamps and timezone names.

## Phase 2: Building And Shade Domain Model

Create a provider-neutral shade module, likely `app/domain/route_shade.py`, with
validated immutable types for:

- `BuildingHeightQuality`: `explicit`, `inferred_levels`, `unknown`;
- normalized building identity, footprint, effective geometry, height, and
  height quality;
- `ShadeConfidence`: `sufficient`, `insufficient`, `not_applicable`;
- solar position with north-referenced clockwise azimuth and horizon-referenced
  elevation;
- per-route shade evidence, including modeled percentage, building-height
  coverage, quality area fractions, footprint counts, and dropped geometry;
- route-set shade evidence and limitations.

### Height parsing

Implement one strict parser for common OSM forms:

- plain numeric values are metres;
- metre suffixes such as `12 m`;
- feet values such as `40 ft`;
- feet/inches notation such as `10'6"`;
- positive finite values only;
- semicolon lists, ranges, malformed text, zero, and negatives are invalid.

Use a valid explicit `height` first. If it is absent or invalid, use positive
finite `building:levels * 3.0`. Otherwise classify the footprint as unknown.
Keep the 3 m approximation in configuration/provenance and never label it as an
explicit OSM height.

### Parent and part geometry

Normalize building and `building:part` objects independently, preserving OSM
identity. For overlapping geometry:

1. partition each parent by the union of its parts;
2. use each part's own height classification over its footprint;
3. retain the parent's classification only on uncovered parent geometry;
4. do not inherit parent height into a part;
5. avoid double-counting area, coverage, or shadows.

Invalid or empty polygonal geometry is dropped and counted. If its bounds or
membership make it potentially relevant to a route corridor, that route's
confidence is forced insufficient. If relevance cannot be localized, apply the
limitation to the whole returned route set.

## Phase 3: Solar And Shadow Geometry

Add and pin Astral as the solar-position implementation. Wrap it behind a small
pure domain-facing adapter so provider conventions and test vectors remain
owned by this repository.

For the exact recommendation instant and route-set centroid:

- calculate azimuth clockwise from true north;
- calculate elevation from the horizon;
- validate finite values and normalize azimuth to `[0, 360)`;
- classify elevation `<= 0` as nighttime before any OSM acquisition.

For positive elevation, project routes and footprints to the existing local UTM
CRS. For each known-height effective footprint:

1. compute shadow length as `height / tan(elevation)`;
2. cast opposite the solar azimuth;
3. construct the geometric sweep from the footprint to its translated copy;
4. union all sweeps;
5. subtract occupied building footprints;
6. intersect the shadow union with each route LineString;
7. divide covered route length by total projected route length and report a
   percentage in `[0, 100]`.

Use structured Shapely operations for the polygonal sweep; do not approximate
coverage with point sampling. Union overlapping shadows before route
intersection so route length is never counted twice.

## Phase 4: Shared OSM Building Acquisition

### Query boundary

Generalize the Overpass client to execute bounded typed queries, or add a
building-specific client over the existing transport. Keep hotel normalization
separate.

Build one deterministic query over the shared 250 m buffered route AOI:

- select ways and relations tagged `building`;
- select ways and relations tagged `building:part`;
- request tags, identities, relation membership, and full geometry;
- preserve `osm3s.timestamp_osm_base` as the OSM data date;
- make exactly one provider execution for the complete returned route set.

### Cache, fixture, and provenance

Create a building execution service with live to exact cache to matching
fixture to explicit unavailability. Identity includes:

- Overpass endpoint/provider instance;
- canonical shared AOI;
- complete query options and selected tags;
- schema version;
- provider configuration version;
- route-shade model version where it affects requested data.

Cache and fixture replay remain stale and retain the true OSM data date. Add a
canonical provider-shape building fixture and acquisition sidecar. The committed
canonical building fixture is synthesized to the provider's response shape, not
captured from a live Overpass execution; its acquisition sidecar records
`source: "synthesized"`, a null `retrieved_at`, and the exact request identity
it stands in for. Synthesized geometry used for focused tests stays in test
fixtures and is labelled synthesized.

Shade provenance should report source, OSM timestamp, retrieval timestamp,
staleness, AOI/search distance, metres-per-level policy, solar timestamp and
position, model version, counts by height quality, dropped geometry, coverage,
and model limitations.

## Phase 5: Coverage And Confidence

For each route, intersect effective footprints with its projected 250 m
analysis corridor. Calculate area by quality after parent/part partitioning:

- `explicit_fraction = explicit_area / total_relevant_area`;
- `inferred_levels_fraction = inferred_area / total_relevant_area`;
- `unknown_fraction = unknown_area / total_relevant_area`;
- `building_coverage = explicit_fraction + inferred_levels_fraction`.

When total relevant area is zero, all known fractions and coverage are zero.
Percentages and counts remain visible even when confidence is insufficient.

`ShadeConfidence.SUFFICIENT` requires:

- exact validated recommendation time and named timezone;
- positive solar elevation;
- successful provider/cache/fixture normalization;
- no potentially relevant dropped building geometry;
- every route's building-height coverage at or above the configured threshold;
- finite modeled shade for every route.

`INSUFFICIENT` applies to weak or uncomputable daytime evidence.
`NOT_APPLICABLE` applies only to nighttime, with zero building shade and no
building acquisition.

## Phase 6: Route Decisions And Contracts

Extend `RouteDecisionState` with:

- `shade_shadiest_recommended`;
- `shade_only_route_recommended`;
- `nighttime_coolest_recommended`;
- `insufficient_shade_comparison_required`.

Extend route results with typed shade confidence, detailed height-quality
coverage, building and solar provenance, and limitations. Keep distance, TCM,
heat coverage, heat source, full geometry, and partial modeled shade available
in insufficient states.

Decision order after issue #18's route heat gate:

1. Mild heat remains `mild_shortest_recommended`; do no solar or OSM work.
2. Elevated heat with missing comparable TCM retains the existing heat
   unavailable/no-suitable behavior; shade cannot repair missing heat evidence.
3. Resolve exact solar position.
4. At night, set every route to `0%`/`not_applicable`, recommend minimum TCM,
   and break ties by distance then identity.
5. In daytime, acquire and model all returned routes once.
6. If every route is sufficient, recommend maximum shade, then distance, then
   identity. Use the only-route state when applicable.
7. Otherwise leave `recommended_id` null and use
   `insufficient_shade_comparison_required`.

Update contract invariants so final recommendation states require exactly one
matching recommended option, while insufficient comparison requires none.
Remove or rewrite the legacy `RouteComparator` shortest fallback so there is
one authoritative decision policy.

## Phase 7: Service Integration And Settings

Add a `RouteShadeAnalysisService` between route heat evidence and final route
decisioning. Keep pure solar, geometry, coverage, and recommendation functions
outside provider orchestration.

Extend settings with a focused shade configuration:

- building search/analysis distance, default `250.0` m;
- minimum building-height coverage, default `0.70`;
- inferred metres per level, default `3.0`;
- canonical trip timezone, `America/Chicago`;
- building schema/provider configuration versions;
- shade model version.

Reuse Overpass endpoint, User-Agent, timeout, and bounded retry policy. Validate
all numeric ranges and the IANA timezone at startup.

Inject shade analysis into `RouteAnalysisService` after elevated heat is known.
Nighttime must bypass the building loader entirely. Building failures become an
insufficient shade comparison, not loss of the already valid route section.

Update trip degradation rules:

- sufficient shadiest and nighttime decisions are final route results;
- a single-route recommendation remains degraded only for limited comparison;
- insufficient shade comparison keeps the route section and adds a route
  degradation reason;
- no forced fallback recommendation is introduced.

## Phase 8: Offline Test Strategy

### Exact-time tests

- preserve offset-aware selected TCM time;
- preserve and validate `America/Chicago` across standard and daylight time;
- reject inconsistent selected-hour tile instants without losing best-time;
- reject local date/hour or zone-offset mismatch for shade purposes;
- serialize fixture and live timestamps identically.

### Height and geometry tests

- explicit height precedence over levels;
- valid metres, feet, and feet/inches parsing;
- malformed explicit height falling back to valid levels;
- invalid levels producing unknown quality;
- exact `3 m/level` inference and provenance;
- building parts replacing parent overlap;
- no duplicated parent/part area or shadow;
- malformed geometry retained as a confidence limitation.

### Solar and shadow tests

- representative San Antonio summer-noon and winter cases;
- morning/evening azimuth direction;
- positive, zero, and negative solar elevation boundaries;
- a known-height footprint casting the expected cardinal-direction shadow;
- route fully shaded, partially shaded, and unshaded cases;
- overlapping shadows not double-counting route length;
- building footprints excluded from shade length.

### Coverage and decisions

- explicit/inferred/unknown area fractions sum correctly;
- no buildings produces zero coverage;
- `0.70` boundary is sufficient and just below it is insufficient;
- any route with weak coverage blocks a comparison recommendation;
- partial evidence remains visible in insufficient results;
- sufficient alternatives recommend shadiest with deterministic ties;
- sufficient single route uses `shade_only_route_recommended`;
- weak single route has no recommendation;
- nighttime recommends coolest and uses distance only for equal-TCM ties;
- nighttime makes zero Overpass calls;
- mild heat makes zero solar and Overpass calls.

### Acquisition and integration

- exactly one shared Overpass request for elevated daytime alternatives;
- query includes `building` and `building:part` full geometry;
- every cache identity field changes the key;
- live, cache, fixture, and exhausted degradation paths are truthful;
- stale fixture/cache evidence remains visible;
- dropped geometry and provider failure yield no forced recommendation;
- route, heat, building, and solar provenance remain distinct;
- frontend type checks and fixtures accept all new states for issue #20.

## Phase 9: Documentation And Issue Alignment

- Amend issue #19 to replace the weak-coverage shortest fallback with explicit
  no-recommendation comparison behavior and add exact-time/nighttime criteria.
- Keep `CONTEXT.md` synchronized with the accepted domain terms.
- Add ADR 0007 for exact-time, nighttime, and insufficient-evidence decisions.
- Document Astral, shade settings, Overpass building fixtures, and model
  limitations in README/design documentation.
- Update fixture inventory and acquisition records.
- Point issue #20 at the four final shade decision states and the detailed
  evidence it must present.

## Planned File Map

New files:

- `app/domain/route_shade.py`
- `app/integrations/overpass/buildings.py` or equivalent typed query module
- `app/services/building_execution.py`
- `app/services/route_shade_analysis.py`
- `tests/test_building_heights.py`
- `tests/test_route_shade.py`
- `tests/test_building_execution.py`
- canonical building fixture and acquisition sidecar under `fixtures/`

Primary modified files:

- `app/domain/contracts.py`
- `app/domain/route_decision.py`
- `app/domain/trip.py` to remove or align the legacy comparator
- `app/services/route_analysis.py`
- `app/services/trip_adapters.py`
- `app/integrations/overpass/client.py`
- `app/settings.py`
- `app/wiring.py`
- `pyproject.toml` and lock data
- fixture/API/orchestration tests
- `frontend/src/types.ts` and response guards
- README and relevant design documentation

## Implementation Order

1. Add failing exact-time contract and temporal orchestration tests.
2. Preserve exact recommendation time and timezone through live and fixture
   paths.
3. Add failing height normalization, parent/part, coverage, and shadow tests.
4. Implement pure building-height, solar, shadow, and coverage domain logic.
5. Add Overpass building query, normalization, exact degradation, and fixtures.
6. Add final decision states and prove nighttime/weak/single-route behavior.
7. Integrate shade analysis after the elevated heat gate and prove call counts.
8. Update API fixtures and frontend compatibility types.
9. Run focused tests, then the complete backend and frontend verification suite.
10. Finish configuration, fixture, model-limitation, and issue documentation.

## Completion Criteria

Issue #19 is complete when exact temporal evidence reaches solar calculations;
elevated daytime routes receive deterministic OSM building-shade estimates and
height-quality coverage; sufficient evidence recommends the shadiest returned
route; nighttime performs no building acquisition and recommends the coolest
returned route; weak daytime evidence preserves every available route metric
without a recommendation; all provider, geometry, confidence, provenance, and
call-count behavior is proven offline; and no result presents modeled shade as
measured real-world shade.
