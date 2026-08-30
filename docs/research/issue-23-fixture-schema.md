# Issue #23: Full-Flow Fixture And Schema Design

**Research date:** 2026-08-30  
**Issue:** [#23, Complete fixture acquisition for canonical and alternate scenarios](https://github.com/alshawai/heat-aware-tourism-guide/issues/23)  
**Scope:** Completed fixture/schema implementation under the settled scenario matrix in
[`issue-23-alternate-scenarios.md`](issue-23-alternate-scenarios.md). No private
configuration was read and no external provider request was made during this
documentation update. The implementation and committed generated sidecars are
the factual outcome record.

## Executive Recommendation

Define **`trip-contract-v2` as a versioned, product-level snapshot schema**,
decode both live and fixture snapshots through one strict decoder, and retain
the raw OSRM, Overpass, FortyGuard, and hotel-discovery acquisitions as separate
fixtures with their own sidecars. Generate each successful product snapshot by
running the production domain orchestration over those normalized acquisitions;
do not hand-author recommendation fields. Generate the two product failure
states through explicit deterministic injection points, then serialize the
resulting validated domain response.

This is smaller and safer than rebuilding the whole product from lower-level
fixtures on every replay. The current live trip path still omits hotel ranking
and always returns a degraded result
([`trip_adapters.py:196-219`](../../app/services/trip_adapters.py)), while the
hotel endpoint is separately orchestrated
([`api.py:344-370`](../../app/api.py)). Replay-time orchestration would therefore
turn Issue #23 into unfinished live-flow integration work. A product snapshot
also does not duplicate domain _logic_ if it stores only a validated output,
records its generator version and inputs, and is regenerated rather than edited
when policy changes.

Do not extend the existing compact `trip-contract-v1` shape. Its route decoder
requires a recommendation, finite aggregate/per-route heat, and a legacy single
confidence model
([`trip_adapters.py:762-826`](../../app/services/trip_adapters.py)); it discards
modern route states, separate routing/heat/building/solar provenance, per-route
heat coverage/source, height-quality evidence, and limitations
([`trip_adapters.py:829-878`](../../app/services/trip_adapters.py)). The current
domain and frontend contracts already contain those modern fields
([`contracts.py:760-885`](../../app/domain/contracts.py),
[`types.ts:213-277`](../../frontend/src/types.ts)). Calling a substantially
different payload `v1` would hide a breaking semantic change.

The smallest coherent implementation is therefore:

1. Add a strict `trip-contract-v2` encoder/decoder mirroring the complete
   `TripAnalysisResponse` domain shape.
2. Make `FixtureTripAnalysisAdapter` accept an explicit ordered collection of
   fixture paths and select by sidecar identity, not by filename.
3. Keep one sidecar per product snapshot and one per underlying provider
   acquisition. Add provider identity and typed upstream acquisition references
   to acquisition metadata.
4. Add an optional-enrichment code and permit it to mark a full base result as
   degraded; accept the already-domain-modeled structured whole-trip
   unavailable object in v2.
5. Acquire dedicated public/provider data for the exact coordinates, AOIs,
   dates, and configurations. Do not transplant existing heat values to the new
   places.

## Repository Facts That Constrain The Design

### Product and scenario facts

- The product has three linked decisions and the server owns provider calls and
  product-shaped responses
  ([`CONTEXT.md:8-11`](../../CONTEXT.md),
  [`design-doc.md:116-126`](../design/design-doc.md)).
- Issue #23 explicitly requires canonical plus two or three San Antonio
  scenarios, all listed decision/fallback states, acquisition metadata, shared
  live/fixture validation, and an offline core flow. The two issue comments also
  pin the corrected canonical coordinates and require the date-level TCM caveat
  while retaining declared night/day windows.
- The settled alternate matrix establishes only place identity, observed route
  counts, observed OSM height coverage, and synthesized failure semantics. It
  does **not** establish heat values or modeled shade
  ([`issue-23-alternate-scenarios.md:23-81`](issue-23-alternate-scenarios.md),
  [`issue-23-alternate-scenarios.md:362-373`](issue-23-alternate-scenarios.md)).
- A route alternative means a route returned by the configured provider; a
  second route must never be invented
  ([`CONTEXT.md:129-135`](../../CONTEXT.md)). A one-route result is usable and
  explicitly limited
  ([ADR 0006:52-55](../adr/0006-returned-route-heat-analysis.md)).
- Weak daytime height/shade evidence preserves route evidence but produces no
  recommendation
  ([ADR 0007:37-41](../adr/0007-exact-time-modeled-shade-decisions.md)). This
  supersedes the stale shortest-route wording in
  [`design-doc.md:298-313`](../design/design-doc.md) and
  [`fortyguard-extraction.md:90-95`](../design/fortyguard-extraction.md).

### Existing schema facts

- `TripAnalysisResponse` already validates complete success, partial degraded,
  and structured unavailable states
  ([`contracts.py:1036-1071`](../../app/domain/contracts.py),
  [`contracts.py:1073-1128`](../../app/domain/contracts.py)).
- `BestTimeResult` already carries a timezone-aware `recommendation_time`, IANA
  `recommendation_timezone`, and typed temporal-evidence state; exact evidence
  requires both fields
  ([`contracts.py:557-575`](../../app/domain/contracts.py),
  [`contracts.py:625-636`](../../app/domain/contracts.py)).
- The live temporal path derives exactness from one unique selected TCM instant,
  validates local date/hour/offset, and uses `America/Chicago` only as the
  documented fallback
  ([`trip_adapters.py:326-352`](../../app/services/trip_adapters.py)).
- The modern route contract validates route-set cardinality, full WGS84
  geometry, nullable recommendation in non-final states, separate provenance,
  and heat-unavailable invariants
  ([`contracts.py:941-1013`](../../app/domain/contracts.py)).
- Per-route route fields already include heat value/coverage/source, modeled
  shade, `ShadeConfidence`, height-quality fractions and counts, dropped
  geometry, and limitations
  ([`contracts.py:760-859`](../../app/domain/contracts.py)).
- Hotel results validate exact component units (`C`, `hours`, `hours`, `C`) and
  all ranking arithmetic
  ([`contracts.py:687-758`](../../app/domain/contracts.py)). Optional enrichment
  currently has only `state` and free-text `reason`
  ([`contracts.py:124-141`](../../app/domain/contracts.py)).
- `UnavailableResult` already has `reason`, `recoverable`, `code`, and `action`,
  with default code `scenario_unavailable`
  ([`contracts.py:1036-1049`](../../app/domain/contracts.py)). The live initial
  TCM failure helper already defaults to `provider_data_missing`
  ([`trip_adapters.py:513-528`](../../app/services/trip_adapters.py)).

### Existing fixture and parity facts

- ADR 0004 makes the sidecar `request_configuration` the authoritative fixture
  identity and requires provider-shaped acquisitions to traverse the same
  translation and normalization pipeline as live data
  ([ADR 0004:40-65](../adr/0004-fixture-cache-provenance-ledger.md)).
- `FixtureTripAnalysisAdapter` currently takes exactly one path, reads one
  sidecar, and returns `scenario_unavailable` if it does not match
  ([`trip_adapters.py:65-98`](../../app/services/trip_adapters.py)).
- Product fixture and a payload-returning test live adapter both call
  `normalize_trip_analysis`, and the parity test compares their resulting
  fields
  ([`trip_adapters.py:114-128`](../../app/services/trip_adapters.py),
  [`test_trip_adapters.py:46-65`](../../tests/test_trip_adapters.py)). This is
  useful structural parity, but it is not parity with the real
  `TemporalTripAnalysisAdapter`, which directly constructs domain objects.
- `normalize_trip_analysis` accepts unavailable only as a non-empty string and
  then loses code/action specificity
  ([`trip_adapters.py:551-571`](../../app/services/trip_adapters.py)).
- The committed trip fixture is legacy: no exact recommendation instant, only
  two hotels, a synthesized second canonical route, and combined route
  provenance
  ([`trip-analysis.json:11-32`](../../fixtures/trip-analysis.json),
  [`trip-analysis.json:34-86`](../../fixtures/trip-analysis.json),
  [`trip-analysis.json:88-145`](../../fixtures/trip-analysis.json)).
- Frontend runtime guards understand the modern explicit route states and exact
  time fields
  ([`dataClient.ts:237-328`](../../frontend/src/services/dataClient.ts),
  [`dataClient.ts:356-408`](../../frontend/src/services/dataClient.ts)), but
  hotel content in `TripAnalysisResponse` is still typed only as
  `Record<string, unknown>`
  ([`types.ts:279-295`](../../frontend/src/types.ts)).

## Decision 1: `trip-contract-v2`

### Why v2 is required

`trip-contract-v1` is not merely missing optional fields. Its parser enforces a
different route model: `recommended_id`, `heat_status`, every route heat value,
and aggregate corridor heat are mandatory
([`trip_adapters.py:771-826`](../../app/services/trip_adapters.py)). That cannot
truthfully encode:

- `single_route` with limited comparison under the modern state machine;
- elevated heat awaiting shade;
- weak-height daytime comparison with `recommended_id: null`;
- route heat unavailable while geometry remains;
- separate routing, heat, building, and solar evidence;
- route-specific heat coverage and height quality;
- exact temporal evidence; or
- a structured product failure code.

There is no concrete backward-compatibility requirement for committed product
fixtures. They are repository-owned data, selected internally, and can be
regenerated atomically with their sidecars and tests. Keep the v1 decoder only
if another active branch or released consumer still needs the old committed
fixture; otherwise replace it rather than supporting two formats indefinitely.
The public API response is already the dataclass shape, so the new snapshot
should converge on that shape rather than inventing another compact format.

### V2 envelope

The product JSON should contain only these top-level fields:

```json
{
  "schema_version": "trip-contract-v2",
  "state": "success | degraded | unavailable",
  "best_time": {},
  "hotels": {},
  "routes": {},
  "unavailable": null,
  "degraded_reasons": null
}
```

`mode`, `execution_mode`, and `request_identity` are adapter-owned response
fields derived from the actual request and selected execution mode. They should
not be trusted from fixture JSON. The scenario identity remains sidecar-owned,
as ADR 0004 requires. An embedded scenario block may exist only as non-authority
for human inspection; omitting it is cleaner.

For successful/degraded sections, use the serialized domain shape exactly:

- `best_time`: complete `BestTimeResult`, including hourly metric objects,
  environmental concerns, retained TCM, framing metrics, exact recommendation
  timestamp/timezone, temporal-evidence state, and provenance.
- `hotels`: complete `HotelRankingResult`, including ranked hotels, exact
  component units, counts, weights, provenance, and typed enrichment outcome.
- `routes`: complete `RouteComparisonResult`, including explicit state fields,
  all `RouteOption` evidence, and four distinct provenance fields.
- `unavailable`: complete `UnavailableResult` object, not a string.

The decoder should reject unknown keys at every contract-owned object boundary.
Current helper parsing mostly ignores extras, so malformed fixture fields can
silently survive even while the resulting dataclass is valid. Strict keys are
part of making “same schema” testable rather than rhetorical.

### Temporal and route invariants

The v2 decoder must preserve the existing domain invariants, not recompute a
different decision:

- `temporal_evidence="exact"` requires an offset-aware ISO 8601 instant and
  `recommendation_timezone="America/Chicago"` for these scenarios.
- The local date/hour/offset must agree with the requested date and recommended
  hour, matching live validation in
  [`trip_adapters.py:341-348`](../../app/services/trip_adapters.py).
- `single_route` requires exactly one route; `alternatives_returned` requires at
  least two
  ([`contracts.py:964-970`](../../app/domain/contracts.py)).
- `insufficient_shade_comparison_required` requires no recommended route, while
  preserving route heat and partial shade/height evidence
  ([`route_decision.py:234-258`](../../app/domain/route_decision.py)).
- Height fractions must sum to one when nonzero, and usable coverage must equal
  explicit plus inferred-level area fractions
  ([`route_shade.py:61-95`](../../app/domain/route_shade.py)).
- Hotel scores, ordering, ties, and percentiles must remain domain-validated,
  not accepted as arbitrary JSON
  ([`contracts.py:727-757`](../../app/domain/contracts.py)).

## Decision 2: Product Snapshots, Not Replay-Time Full Orchestration

| Option                                              | Complexity                                                                                                           | Live-validation parity                                                                                | Compatibility                                                   | Main risk                                                                                                               | Decision             |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | -------------------- |
| Extend compact v1                                   | Initially small, then many conditionals                                                                              | Poor: old parser owns legacy decision behavior                                                        | Avoids a fixture rename that has no demonstrated consumer value | Calls a semantically new format v1 and preserves wrong invariants                                                       | Reject               |
| Define product `trip-contract-v2`                   | One encoder/decoder plus fixture regeneration                                                                        | Strong at the product schema/domain boundary; underlying provider fixtures still use live normalizers | Clean break; no legacy need established                         | Derived snapshots can drift if hand-edited                                                                              | **Recommend**        |
| Orchestrate all lower-level fixtures at replay time | Largest: complete hotel integration, failure injection, fixture registry for every provider, and deterministic clock | Strongest computational parity                                                                        | No product snapshot compatibility issue                         | Expands Issue #23 into application orchestration and makes offline selection depend on many coordinated fixture matches | Reject for Issue #23 |

The recommended acquisition/build process is:

1. Acquire raw, sanitized provider payloads with exact sidecars.
2. Replay them through the same provider translators/normalizers as live.
3. Run production domain services once with a pinned clock and explicit
   deterministic failure injection where the scenario calls for it.
4. Validate the resulting `TripAnalysisResponse`.
5. Serialize it as `trip-contract-v2`, record generator/policy versions and
   upstream fixture references, then decode it once more through the shared v2
   decoder before committing.

This stores derived facts but not duplicated decision rules. A changed rule
requires regenerating snapshots and bumping the product transformation version.

## Decision 3: Exact Live/Fixture Schema Parity

### Current parity

- Raw FortyGuard acquisitions already replay through live translation and
  normalization, as ADR 0004 requires.
- OSRM live/cache/fixture payloads all traverse `normalize_response`
  ([`routing.py:59-62`](../../app/services/routing.py),
  [`routing.py:94-103`](../../app/services/routing.py),
  [`routing.py:120-126`](../../app/services/routing.py)).
- Overpass building live/cache/fixture payloads all reach the same shade
  normalization service after exact sidecar matching
  ([`building_execution.py:93-121`](../../app/services/building_execution.py),
  [`building_execution.py:144-171`](../../app/services/building_execution.py)).
- Product fixture and the artificial payload-based live adapter share the v1
  normalizer.

### Gaps

- The real live temporal adapter does not pass through the trip JSON decoder.
- The v1 route decoder does not represent current domain/API behavior.
- Product provenance parsing overwrites `source` with the requested execution
  mode
  ([`trip_adapters.py:942-959`](../../app/services/trip_adapters.py)); this loses
  whether an underlying input was provider, cache, fixture, computed, or
  unavailable.
- The frontend has independent hand-written guards rather than a generated or
  shared schema, and the trip hotel section is effectively unvalidated.
- API serialization uses unrestricted `dataclasses.asdict`
  ([`api.py:508-540`](../../app/api.py)); there is no round-trip contract check.

### Exact interpretation of the acceptance criterion

Implement one pair of functions, conceptually
`encode_trip_analysis_v2(response)` and
`decode_trip_analysis_v2(payload, request, execution_mode)`. Both paths must
cross the decoder boundary:

- Fixture: read JSON -> v2 decoder -> `TripAnalysisResponse`.
- Live: production orchestration -> v2 encoder -> v2 decoder ->
  `TripAnalysisResponse`.
- HTTP: serialize the decoded response through the same encoder, not raw
  `asdict`.

This deliberately validates live serialization, not only live Python object
construction. It also ensures fixture JSON cannot contain a shape that the live
API could never emit.

Recommended parity tests:

1. Round-trip every live-produced result state through encode/decode and compare
   equality except adapter-owned execution source.
2. Decode every committed trip v2 fixture and re-encode it to canonical JSON;
   assert semantic equality.
3. Feed the same canonical v2 payload through fixture and live decoding and
   assert identical sections and different only `execution_mode` plus the
   adapter-level fixture/live source where intentionally defined.
4. Parameterize every route decision state and top-level state, including one
   route, weak shade, optional enrichment failure, and core unavailable.
5. Mutate/omit every newly required field and assert both paths reject it with
   the same error category.
6. Validate the HTTP response in the frontend guard for all four committed
   scenarios; add a real `HotelRankingResult` frontend type/guard.
7. Assert the raw acquisition fixtures still traverse OSRM, Overpass, and
   FortyGuard production normalizers before snapshot generation.

## Decision 4: Multiple Product Fixture Selection

Extend `FixtureTripAnalysisAdapter` to accept an explicit sequence of fixture
paths, supplied by wiring. Do **not** scan a directory by filename and do not add
a separate index file.

Reasons:

- Sidecars are already the authoritative index and exact match identity
  ([ADR 0004:49-53](../adr/0004-fixture-cache-provenance-ledger.md)). A second
  JSON index creates two authorities that can drift.
- Naming conventions are not identity; they cannot safely encode coordinates,
  date/window, mode, district, and all request semantics.
- An explicit path list is deterministic, reviewable in wiring, and consistent
  with existing `additional_fixtures` handling for lower-level executions
  ([`wiring.py:532-545`](../../app/wiring.py)).

Selection algorithm:

1. For every configured path, load and validate its sidecar first.
2. Ignore a well-formed, non-replayable sidecar as a successful match candidate;
   it may still represent a selectable synthesized unavailable product fixture
   only if product selection explicitly permits its non-`ok` status. The
   current generic `replayable == status == "ok"` rule
   ([`provenance.py:94-96`](../../app/domain/provenance.py)) is too narrow for a
   deliberately unavailable product response; product selection should instead
   allow a documented terminal status such as `unavailable` while lower-level
   success fallback remains `ok` only.
3. Compare the complete sidecar request identity to the request. Use explicit
   coordinate tolerance (recommend `abs_tol=1e-7`, `rel_tol=0`) rather than
   default `math.isclose`, and exact mode/name/date/window/district matching.
4. Zero matches returns structured `scenario_unavailable`.
5. Exactly one match decodes that fixture.
6. More than one match is a configuration error, never “first wins.” Raise an
   ambiguity error naming the duplicate sidecars.
7. A malformed configured fixture or sidecar is a startup/inventory error, not
   a silent non-match. This differs from live fallback candidate probing, where
   a malformed optional fallback may be skipped; the public offline scenario
   inventory is expected to be valid.

The four paths should be explicit in production wiring. Tests should reverse
their order to prove order-independent exact selection and should add malformed
and duplicate-sidecar cases.

## Decision 5: Acquisition Metadata

### Generic `AcquisitionRecord` fields

Keep `source` as the origin class and add these generic fields:

```text
provider: non-empty stable provider/product identity
derived_from: ordered tuple of acquisition references
```

Each acquisition reference should contain a repository-relative fixture path,
its sidecar path or acquisition ID, and a SHA-256 of the exact committed payload.
Hashes prevent a product snapshot from continuing to claim an input after that
input is changed in place. For example:

```json
{
  "fixture": "fixtures/providers/osrm/main-plaza-market-square.json",
  "sha256": "...",
  "role": "routing"
}
```

`provider` is needed because `source="provider"` says _how_ the fixture arose,
not _which_ provider supplied it. Recommended values are stable identifiers such
as `fortyguard`, `fossgis-osrm`, `overpass-api-de`, and
`heat-aware-tourism-guide`. A synthesized product fixture uses
`source="synthesized"`, `provider="heat-aware-tourism-guide"`, null retrieval
time/activity ID, and populated `derived_from` links.

Keep these existing generic fields in `AcquisitionRecord`: endpoint,
authoritative request configuration, retrieval time, data date, status, payload
schema version, provider configuration version, safe activity ID, and applied
transformations
([`provenance.py:63-80`](../../app/domain/provenance.py)).

Validation should become source-aware:

- `source="provider"` requires a real `retrieved_at`, provider identity, endpoint,
  config version, and terminal status.
- `source="synthesized"` requires null `retrieved_at` and `activity_id`, as the
  current inventory test already enforces
  ([`test_fixture_inventory.py:46-50`](../../tests/test_fixture_inventory.py)).
- `activity_id` remains optional for provider acquisitions. OSRM and Overpass
  are synchronous public providers and truthfully have no FortyGuard activity
  ID.
- `data_date` means the data's own effective/source date where supplied. For
  Overpass, use `osm3s.timestamp_osm_base`; for FortyGuard, use requested date
  only with the `valid_time_from_request` transformation; for OSRM, whose
  response exposes no OSM dataset timestamp, use retrieval date and explicitly
  label that basis in endpoint metadata rather than implying an OSM snapshot
  date.

### Endpoint-specific `request_configuration`

Put all values that determine matching/cache identity here:

- FortyGuard: internal analytic request, exact point or polygon AOI, date,
  half-open product window, documented rendered provider window, forecast flag,
  analytic type, threshold/direction, granularity, and timezone interpretation.
- OSRM: supplied origin/destination coordinates, profile, alternatives,
  overview, geometry and steps options, provider instance, request version. The
  existing complete identity is already defined in
  [`routing.py:129-147`](../../app/services/routing.py).
- Overpass buildings: exact AOI, search distance, response/query options,
  selected tags, and model version. The existing sidecar demonstrates this
  shape
  ([`overpass-buildings-canonical.acquisition.json:4-25`](../../fixtures/acquired/overpass-buildings-canonical.acquisition.json)).
- Hotel discovery: canonical district ID/name, exact district AOI, query tags,
  object types, center/geometry output, and deduplication contract version.
- Product trip: mode, both named places with application ID and exact
  coordinates, landmark and canonical hotel-district identity, date, half-open
  traveler window, cautious flag if fixture output depends on it, and product
  policy/generator version.

### Endpoint-specific response metadata or payload provenance

Do **not** put units in generic `AcquisitionRecord`; units are metric semantics
and must stay beside values in the raw/normalized payload. Product contracts
already enforce them. Record provider response facts that do not determine a
request under a small endpoint-specific `response_metadata` object in the raw
fixture or sidecar:

- OSRM: top-level code, route count, units (`distance="m"`, `duration="s"`),
  and returned waypoint snap coordinates/distances.
- Overpass: OSM base timestamp, element count, and response format/version.
- FortyGuard: terminal provider status, activity ID where present, raw unit
  presence/absence, and raw freshness presence/absence. Inferred Celsius and
  valid time remain named/versioned transformations per ADR 0002
  ([ADR 0002:24-54](../adr/0002-live-unit-and-freshness-inference.md)).

Place coordinate meaning and OSM identity belong in product payload provenance
or product-sidecar place records because they explain scenario identity; they
are not generic acquisition fields. Preserve application ID, display name,
`{object_type, object_id}`, coordinate, coordinate role (`centroid`,
`component_central_point`), and authority/source classification. Never replace
supplied place coordinates with OSRM snaps
([`issue-23-alternate-scenarios.md:83-102`](issue-23-alternate-scenarios.md)).

### Hotel temporal metadata

For night/day component evidence, preserve all of the following machine-readably:

```json
{
  "declared_window": {
    "start": "00:00",
    "end": "05:00",
    "timezone": "America/Chicago",
    "interval": "[start,end)"
  },
  "temporal_basis": "date_level_tcm",
  "provider_window_validated": false,
  "caveat_code": "date_level_not_interval_maximum"
}
```

Use `10:00`/`17:00` for day. These belong in each component's payload
provenance because they qualify what the displayed component means, and should
also be mirrored in the component acquisition request configuration when they
were actually sent. They must not be represented as actual provider interval
maxima until a windowed acquisition establishes that fact. Current wiring has
the correct caveat only as prose
([`wiring.py:291-303`](../../app/wiring.py)); the issue comment requires a
machine-readable representation.

## Decision 6: Meaning Of `source="provider"`

Keep the source enum unchanged: `provider | synthesized` is honest for
FortyGuard, OSRM, and Overpass.

ADR 0004 defines `provider` broadly as “real acquisitions,” not as “FortyGuard
activity”
([ADR 0004:40-47](../adr/0004-fixture-cache-provenance-ledger.md)). Runtime route
and building outcomes already use `source="provider"` for successful OSRM and
Overpass calls
([`routing.py:69-81`](../../app/services/routing.py),
[`building_execution.py:101-121`](../../app/services/building_execution.py)).
Changing the source enum to `public_provider` would create migration and test
work without adding truth. Add the separate `provider` identity described above
instead.

Update tests that currently assert only `{"provider", "synthesized"}`
([`test_fixture_inventory.py:39-43`](../../tests/test_fixture_inventory.py)) to
also require provider identity and source-specific timestamp/activity rules.
Public, synchronous, unauthenticated, or free does not make a response
non-provider data.

## Decision 7: Failure Codes And Reasons

### Optional enrichment

Evolve `OptionalEnrichment` to:

```text
state: available | unavailable | not_requested
code: optional_provider_failure | null
reason: human-readable string | null
```

For the San Fernando Cathedral scenario use:

```json
{
  "state": "unavailable",
  "code": "optional_provider_failure",
  "reason": "Optional hotel enrichment was unavailable; base hotel results are unchanged."
}
```

Unavailable requires both a nonblank code and reason; other states require both
null. The complete ranked base hotels remain present. The top-level trip should
be `degraded`, and `degraded_reasons.hotels` should be permitted for this one
case even though the hotel section exists. Current normalization rejects a
reason for a present section
([`trip_adapters.py:600-612`](../../app/services/trip_adapters.py)); that rule
must be refined to recognize an unavailable nested enrichment. This is more
truthful than calling the whole response success while displaying a known
failure.

The product snapshot and its sidecar are synthesized. Do not claim a failed
premium provider acquisition unless one was actually made. Existing readiness
tests establish that optional execution failure preserves the base ranking
([`test_application_domain.py:164-181`](../../tests/test_application_domain.py)).

### Whole-trip core failure

`normalize_trip_analysis` v2 must accept the structured object:

```json
{
  "state": "unavailable",
  "unavailable": {
    "code": "provider_data_missing",
    "reason": "The initial TCM analysis failed and no exact cache or fixture fallback was available.",
    "recoverable": true,
    "action": "retry_or_edit_setup"
  },
  "best_time": null,
  "hotels": null,
  "routes": null,
  "degraded_reasons": null
}
```

This matches the live helper's existing code and action. It must contain no
route result even if a genuine route acquisition is retained separately,
because orchestration exits at initial TCM failure
([`trip_adapters.py:151-165`](../../app/services/trip_adapters.py)). The product
failure sidecar is synthesized with null retrieval/activity fields and may link
to place/routing acquisitions for scenario provenance, but it must identify the
failure injection itself as synthesized.

## Decision 8: District And Fixture-Specific AOIs

Do not broaden or rename the canonical hotel district merely because alternate
trip endpoints lie west or south of its current bounding box. `district_name`
is a hotel-decision scope in the trip request, while route/building AOIs are
derived per fixture and belong to their endpoint request configurations.

Use stable product identities:

- Canonical hotel scope: `Downtown San Antonio` / Alamo Plaza, retaining the
  existing canonical semantics in [`CONTEXT.md:15-17`](../../CONTEXT.md).
- Scenario display context: place-specific labels such as Main Plaza,
  Cattleman's Square, Military Plaza, or Hemisfair. These are display metadata,
  not replacements for hotel district identity.
- `hotel_aoi`: exact canonical district bounding box only when hotel ranking is
  included.
- `route_heat_aoi`: exact shared route heat polygon, if the long-route branch is
  ever used.
- `building_aoi`: exact route-derived 250 m shared bounding box for shade.

For the San Fernando scenario, the base hotel ranking may remain the canonical
district result because the matrix tests optional enrichment behavior, not a
new district ranking. If maintainers want a west-downtown hotel ranking, that is
a new named district/AOI and a new acquisition, not an unnoticed expansion of
“Downtown San Antonio / Alamo Plaza.” The current globally configured hotel AOI
is explicitly `29.421,-98.490,29.429,-98.482`
([`settings.py:69-78`](../../app/settings.py)).

## Decision 9: Dates, Windows, Heat, And Shade

### Facts

- Existing provider-sourced committed heat is a 2026-08-23 request at
  `(29.4241,-98.4936)`, not at any selected landmark
  ([`heatmap-tcm-historical.acquisition.json:4-19`](../../fixtures/acquired/heatmap-tcm-historical.acquisition.json)).
- Existing provider env-params is one 2026-08-24 observation at
  `(29.4259,-98.4861)` with a caller-supplied 35 C anchor
  ([`env-params.acquisition.json:4-16`](../../fixtures/env-params.acquisition.json)).
- Existing hotel heat data is synthesized and uses 2026-08-24
  ([`hotel-heat-analysis.acquisition.json:1-22`](../../fixtures/hotel-heat-analysis.acquisition.json)).
- The strongest observed deterministic historical provider experiment used
  `2024-07-15T14:00` and returned byte-identical results in two submissions, but
  only for its bounded observation AOI
  ([`issue-7-san-antonio-provider-validation.md:236-279`](issue-7-san-antonio-provider-validation.md)).
- Existing observations cannot be relocated to the new endpoints or presented
  as route heat. The alternate-scenario research explicitly establishes no
  heat or shade fact.

### Recommended acquisition target

Use **2024-07-15** as the first historical acquisition target for successful
scenarios because it has the repository's only repeated deterministic provider
content experiment. This is a target, not permission to copy its values. Every
location/AOI still needs a dedicated acquisition. If a dedicated request is
empty, malformed, temporally inconsistent, or does not produce the state the
matrix needs, fail fixture generation and choose another genuinely acquired
historical date; do not edit values.

Recommended product windows:

| Scenario                                            | Date target | Traveler window         | Exact daytime need                                                                                                                                                                                                             |
| --------------------------------------------------- | ----------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Menger Hotel -> The Alamo                           | 2024-07-15  | `08:00-20:00` half-open | Preserve the actual selected instant from dedicated TCM/env evidence; only run shade if it is exact and solar elevation is positive.                                                                                           |
| Main Plaza -> Historic Market Square                | 2024-07-15  | `10:00-17:00` half-open | No special shade state is required. Use genuine dedicated heat; one-route behavior must not depend on invented temperature.                                                                                                    |
| San Fernando Cathedral -> Spanish Governor's Palace | 2024-07-15  | `10:00-17:00` half-open | Required. Commit the weak-height/no-recommendation product fixture only if dedicated heat evidence triggers the elevated daytime branch and yields one exact `America/Chicago` instant with positive computed solar elevation. |
| Briscoe Museum -> Tower of the Americas             | 2024-07-15  | `10:00-17:00` half-open | None, because the synthesized initial TCM failure stops the trip. The date/window still form the exact failed request identity.                                                                                                |

If maintaining the current UI default is more important than using the repeated
historical experiment, 2026-08-23 `08:00-20:00` is the alternative, but it
requires all-new dedicated acquisitions too. The current product fixture's
three hand-authored hourly values do not establish an hourly provider curve
([`trip-analysis.json:14-21`](../../fixtures/trip-analysis.json)). Do not mix a
2024 best-time section with 2026 hotel components: current normalization
correctly requires section data dates to match the request
([`trip_adapters.py:632-635`](../../app/services/trip_adapters.py),
[`trip_adapters.py:723-728`](../../app/services/trip_adapters.py)).

### Truthful construction of heat and shade inputs

1. Acquire dedicated raw TCM and env-params payloads for each successful
   destination/date/window and normalize them through the live adapter.
2. Acquire canonical district heat components for the chosen date. Night/day
   remain correlated date-level TCM unless validated provider windows are
   acquired; encode the declared `00:00-05:00` and `10:00-17:00` windows plus
   `provider_window_validated=false`.
3. Acquire each OSRM route payload independently. All settled alternate routes
   are below the 1,500 m representative threshold, so production logic should
   reuse the selected landmark TCM for route heat and mark
   `heat_source="landmark_reuse"`, rather than fabricate corridor values
   ([ADR 0006:30-44](../adr/0006-returned-route-heat-analysis.md)).
4. For the weak-height scenario, replay the genuine 2026-08-30 Overpass payload
   only with its exact route/AOI/configuration and retain its own OSM source
   timestamp. Recompute coverage and modeled shade locally at the newly selected
   exact trip instant. The known 0.346416/0.340474 coverage is height evidence,
   not shade evidence
   ([`issue-23-alternate-scenarios.md:195-242`](issue-23-alternate-scenarios.md)).
5. Compute solar position through the production Astral path from exact instant
   and route-set centroid. Store model/version/instant/position provenance; do
   not acquire or hand-author solar facts
   ([`route_analysis.py:461-492`](../../app/services/route_analysis.py)).
6. Never tune TCM values to force “elevated.” If the dedicated weak-height
   acquisition is mild under the selected guidance, the matrix is not met and
   fixture generation must stop for a user decision.

## Decision 10: Offline Integration And E2E Matrix

### Backend inventory and schema tests

- Every fixture has exactly one parseable sidecar; every provider acquisition
  has provider identity, real retrieval time, endpoint/config version, and
  truthful optional activity ID.
- Every synthesized fixture has null retrieval/activity fields and valid
  `derived_from` references/hashes.
- Every product fixture round-trips through v2 and satisfies strict unknown-key,
  date/window, unit, state, route, ranking, and provenance validation.
- Secret scan covers raw payloads, sidecars, and nested upstream references.
- Duplicate and malformed sidecars fail inventory/startup.

### Completed Scenario Outcomes

| Scenario                       | Required assertions                                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Canonical                      | Menger Hotel `way/23727574` -> The Alamo `way/129152944`; one genuine OSRM route, 193.1 m / 154.7 s; valid provider TCM `34.0147 C`; complete best-time, six-hotel, and route sections; degraded for GMT-7 temporal inconsistency and limited one-route comparison.                                                                                                                                 |
| Main Plaza -> Market Square    | Main Plaza `way/93118472` -> Historic Market Square (El Mercado) `way/79636475`; one genuine OSRM route, 635.7 m / 510.7 s; `single_route`; non-routing and heat sections are synthesized demo evidence, and the no-feature result is intentionally uncommitted.                                                                                                                                    |
| Cathedral -> Governor's Palace | San Fernando Cathedral `way/80647022` -> Spanish Governor's Palace `way/78601534`; two genuine routes, 265.5 m / 212.3 s and 278.6 m / 222.8 s; genuine Overpass height evidence is 0.346416 / 0.340474 with 7 explicit, 16 inferred, and 87 unknown footprints per route; synthesized demo heat drives ADR 0007, so no recommendation is made; optional enrichment is `optional_provider_failure`. |
| Briscoe -> Tower               | Briscoe Western Art Museum `way/337650172` -> Tower of the Americas `way/78485919`; synthesized complete unavailability with `provider_data_missing`; orchestration stops before environment, hotels, and routing. The observed public route acquisition remains separate evidence and is not returned.                                                                                             |

The corrected canonical acquisition now settles that conflict: the request
genuinely returned one route, so the canonical product snapshot is one-route
and degraded for limited comparison. Cathedral supplies the genuine two-route
comparison. The former synthesized `shady` route is not retained as routing
evidence.

### API and place-search tests

- Add all six stable application IDs/names/coordinates to both FastAPI and
  stdlib search paths. They currently each hard-code only Menger and Alamo
  ([`api.py:97-134`](../../app/api.py), [`api.py:234-265`](../../app/api.py)).
- Parameterize exact and case-insensitive searches for all eight places and
  assert both paths return identical objects.
- For each directed trip, POST the exact searched coordinates and selected
  date/window to `/api/trip/analyze`; assert the matching scenario and no other
  fixture is selected.
- Near-coordinate, reversed-direction, wrong-date, wrong-window, and wrong-name
  requests must return `scenario_unavailable` rather than a nearby fixture.
- Validate all responses with the frontend runtime decoder, including typed
  hotel enrichment and structured unavailable codes.

### Network isolation

- In Python integration tests, monkeypatch the OSRM, Overpass, FortyGuard, and
  generic HTTP opener/socket seams to raise if any non-loopback request occurs.
  Start the real fixture-mode app and run all four POST flows plus all place
  searches.
- Assert zero provider loader calls, zero ledger additions, and zero cache
  dependence in fixture mode.
- In Playwright, retain the current non-loopback route abort
  ([`fixture-trip.spec.ts:3-11`](../../frontend/e2e/fixture-trip.spec.ts)) and
  parameterize all four scenarios.
- E2E must select alternates through visible place search, not construct hidden
  request bodies. Assert canonical best-time/hotels/routes, one-route wording,
  weak-height/no-recommendation plus enrichment warning, and whole-trip failure
  code/recovery copy.
- Block remote map tiles without failing the flow; product data must remain
  usable offline.

This matrix covers every Issue #23 criterion rather than only the current one
canonical happy-path E2E
([`fixture-trip.spec.ts:12-48`](../../frontend/e2e/fixture-trip.spec.ts)).

## Decision 11: ADR And Context Impact

The implemented architectural decision is recorded in
[`ADR 0010`](../adr/0010-trip-v2-product-snapshots.md): **product-level
v2 snapshots linked to lower-level acquisitions, with a shared live/fixture
decoder, instead of replay-time full orchestration**. It fixes the fixture
boundary, parity definition, regeneration policy, and provenance graph. Amend
ADR 0004 remains authoritative for raw-provider truth and degradation; it does
not supersede this derived-snapshot decision.

Update `CONTEXT.md` after implementation with:

- product snapshot and upstream acquisition reference;
- `trip-contract-v2` as the committed full-flow schema;
- optional enrichment failure code semantics;
- declared hotel component windows versus date-level TCM temporal basis; and
- explicit multiple-fixture selection/ambiguity behavior.

Also correct stale accepted-design prose that still says weak coverage
recommends shortest. ADR 0007 is authoritative, but leaving contradictory design
documentation increases implementation risk. This documentation work records
the completed implementation rather than a remaining design task.

## Resolved Implementation Decisions

The implementation has resolved the choices below. They are retained as a
decision record, not as open work for the Issue #23 fixture boundary.

1. **Can v1 represent the agreed states?**
   Fact: no; its parser requires legacy route fields and drops modern evidence.
   Choice: rename the evolved snapshot or overload v1.
   **Recommended answer:** introduce `trip-contract-v2`; remove v1 support unless
   a concrete external consumer is identified.

2. **Should fixture replay orchestrate every provider input?**
   Fact: the live trip path still lacks hotel orchestration, so doing this now
   materially expands Issue #23.
   Choice: full replay-time orchestration or generated product snapshots.
   **Recommended answer:** generated validated snapshots linked to raw inputs.

3. **How are multiple trip fixtures found?**
   Fact: sidecar request configuration is already authoritative.
   Choice: explicit path list, index, or directory convention.
   **Recommended answer:** explicit paths plus sidecar matching; duplicate is a
   hard error.

4. **Does `provider` source include OSRM/Overpass?**
   Fact: ADR 0004 says real acquisition and runtime services already use this
   value.
   Choice: change enum or add provider identity.
   **Recommended answer:** keep source enum; add `provider` field.

5. **What historical date is acquired?**
   Fact: 2024-07-15 has the only repeated deterministic provider experiment,
   but not at the new scenario AOIs; no existing fixture supplies all needed
   heat facts.
   Choice: target 2024-07-15 or preserve UI default 2026-08-23.
   **Recommended answer:** target 2024-07-15 and require dedicated acquisitions;
   fall back only on observed acquisition results, never hand-edited values.

6. **What happens if the canonical OSRM request returns one route again?**
   Fact: the last corrected observation returned one route; canonical
   multi-route comparison cannot be synthesized honestly.
   Choice: change configured routing provider/instance, move multi-route purpose
   to another genuine scenario and amend the matrix, or accept canonical
   one-route behavior.
   **Recommended answer:** reacquire once under the pinned config; if still one,
   amend the scenario matrix rather than fabricate an alternative.

7. **What happens if the Cathedral heat acquisition is mild?**
   Fact: weak heights alone do not invoke ADR 0007's elevated shade decision.
   Choice: choose another genuinely acquired historical date/window or abandon
   this pairing.
   **Recommended answer:** try a separately justified historical daytime target;
   fail generation until genuine elevated evidence exists.

8. **Does optional enrichment make the whole result degraded?**
   Fact: a provider function failed while base ranking remains valid; current
   schema cannot mark a present hotel section degraded.
   Choice: nested warning inside success or top-level degraded.
   **Recommended answer:** top-level degraded plus nested
   `optional_provider_failure`, with base results intact.

9. **Should Briscoe's successful route observation be committed?**
   Fact: it is genuine scenario provenance but is unreachable in the failed
   product flow.
   Choice: retain as linked acquisition or omit as unused data.
   **Recommended answer:** retain it as a separate provider acquisition linked
   for scenario provenance; assert it never appears in the unavailable result.

10. **Are alternate hotel AOIs needed?**
    Fact: Issue #23 needs optional enrichment failure, not three new hotel
    districts; silently widening the canonical AOI changes domain meaning.
    Choice: reuse canonical base ranking or define/acquire new named districts.
    **Recommended answer:** reuse canonical base ranking for the enrichment
    scenario and keep route/building AOIs fixture-specific.

11. **Where do acquisition links live?**
    Fact: sidecars are the fixture provenance authority.
    Choice: payload-only links or generic sidecar references.
    **Recommended answer:** typed `derived_from` references in
    `AcquisitionRecord`, with role and payload hash; expose selected links in
    product provenance where useful to the API.

12. **Is a new ADR needed?**
    Fact: snapshot-versus-orchestration and parity semantics affect every future
    full-flow fixture.
    Choice: undocumented implementation detail, ADR 0004 amendment, or new ADR.
    **Recommended answer:** a short successor ADR, plus context updates after
    implementation.

## Proposed Fixture Inventory

Use descriptive paths but never use names for matching. One possible layout is:

```text
fixtures/trips/menger-alamo.trip.json
fixtures/trips/main-plaza-market-square.trip.json
fixtures/trips/cathedral-governors-palace.trip.json
fixtures/trips/briscoe-tower-unavailable.trip.json
fixtures/providers/osrm/*.json
fixtures/providers/overpass/*.json
fixtures/providers/fortyguard/*.json
fixtures/providers/hotels/*.json
```

Every JSON has a same-stem `.acquisition.json`. Product sidecars use
`schema_version="trip-contract-v2"`,
`provider_config_version="trip-product-config-v1"`, a generator transformation
such as `trip-product-snapshot` v1, and typed upstream links. Raw provider
sidecars use dedicated versions already established where available:
`fortyguard-config-v1`, `osrm-config-v1`, and
`overpass-building-config-v1`. Add a distinct hotel-discovery config version;
do not reuse a FortyGuard version for Overpass or product generation.

## Final Implementation Brief

Implement Issue #23 by first adding the v2 decoder/encoder and multi-path exact
selection, then acquire and validate raw provider fixtures, then generate the
four product snapshots through production domain services. Treat fixture
generation as failed if provider route cardinality, heat state, temporal
exactness, or weak-height reproduction does not match the agreed matrix. Add
all six places to both search paths, prove all scenarios under network blocking,
and record the snapshot boundary in an ADR/context update.

The essential guardrail is: **provider payloads are observed, product failures
are synthesized, and product recommendations are computed. None of the three
may be relabeled as another.**

## Sources Reviewed

Repository sources were primary evidence: Issue #23 and both comments;
`CONTEXT.md`; ADRs 0001-0007; all files under `docs/design/`; the Issue #7,
Issue #40, and settled Issue #23 research; trip, hotel, route heat, routing,
shade, decision, provenance, and environmental contracts/services; FortyGuard,
OSRM, and Overpass adapters; API parsing/serialization and wiring; frontend
types, runtime guards, setup screen, state, mocks, and E2E; all committed
fixtures/sidecars; and relevant backend/frontend tests. Official OSRM, OSM,
Overpass, and FortyGuard facts needed here were already captured with primary
links in the repository research, especially
[`issue-7-san-antonio-provider-validation.md:68-126`](issue-7-san-antonio-provider-validation.md),
[`issue-7-san-antonio-provider-validation.md:407-417`](issue-7-san-antonio-provider-validation.md),
and [`issue-7-san-antonio-provider-validation.md:506-524`](issue-7-san-antonio-provider-validation.md).
No additional external source was needed for this schema decision.
