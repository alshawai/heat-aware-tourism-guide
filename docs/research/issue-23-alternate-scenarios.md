# Issue #23: Alternate San Antonio Fixture Scenarios

**Research date:** 2026-08-30  
**Issue:** [#23, Complete fixture acquisition for canonical and alternate scenarios](https://github.com/alshawai/heat-aware-tourism-guide/issues/23)  
**Scope:** Scenario selection, retained public acquisition evidence, and the
completed Issue #23 fixture outcomes. No provider request was made during this
documentation update.

## Executive Decision

Use these three nearby pedestrian trips, with the failure states labeled exactly
as described below:

| Matrix case                                                   | Recommended directed trip                               | Real-place and public-data facts                                                                                                                                                                                                                                                     | Fixture-only state                                                                                                                                                                   | Why this is decision-ready                                                                                                                                                                                      |
| ------------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A: exactly one valid pedestrian route returned                | **Main Plaza -> Historic Market Square (El Mercado)**   | The configured FOSSGIS pedestrian request returned HTTP-success code `Ok` with **one route**, 635.7 m and 510.7 s, on 2026-08-30 at approximately 12:21 UTC.                                                                                                                         | None for routing. Heat and other fixture inputs remain separately acquired or synthesized according to their own provenance.                                                         | It directly demonstrates the repository's `single_route` / limited-comparison behavior without inventing a route. The claim is only about this request at this retrieval time, not about all possible routes.   |
| B: weak OSM heights and optional hotel enrichment unavailable | **San Fernando Cathedral -> Spanish Governor's Palace** | The configured request returned two routes, 265.5 m / 212.3 s and 278.6 m / 222.8 s. Current OSM building data, processed with the repository's actual 250 m corridor and height model, produced area-weighted usable-height coverage of **0.3464** and **0.3405**, both below 0.70. | Inject optional hotel-enrichment failure after preserving base hotel ranking/results. Geography does not cause the enrichment failure.                                               | It is a compact downtown walk with two returned alternatives and quantitatively weak height evidence. The optional outage can visibly coexist with intact base results.                                         |
| C: core heat provider fails, whole trip unavailable           | **Briscoe Western Art Museum -> Tower of the Americas** | The configured request returned two routes, 895.5 m / 718.1 s and 928.4 m / 744.3 s, observed 2026-08-30 at 12:30:23 UTC. Both endpoints are genuine downtown/Hemisfair attractions.                                                                                                 | Inject deterministic failure of the initial core TCM request and ensure no exact cache or matching fixture can answer; expected product result is explicit whole-trip `unavailable`. | No supported-US place can honestly guarantee a heat-provider failure. This real trip gives the unavailable fixture a credible identity while the sidecar must label the failure as synthesized, not geographic. |

The canonical Menger Hotel -> The Alamo trip remains the fixture for best-time
and hotel ranking. Its corrected route acquisition is genuinely one route, so
it no longer serves as a multi-route comparison. Cathedral owns that comparison
with two genuine returned routes. None of the other scenarios fabricates a
route or replaces the canonical hotel scope.

## Implementation Outcome

The four generated `trip-contract-v2` snapshots now implement the matrix.
Provider observations and synthesized product states remain distinct in their
sidecars and product provenance. The canonical corrected route is genuinely one
route, so it is not described as multi-route and no second route is fabricated;
Cathedral retains the genuine two-route comparison instead. The regenerated
sidecars also record the selected place identities and content-addressed input
hashes.

The metered ledger contains six completed provider calls. They include the
valid canonical destination TCM (`34.0147 C` for 2024-07-15), recovered
canonical environment data, and three valid canonical hotel component
acquisitions. The environment's `GMT-7` metadata conflicts with the canonical
`America/Chicago` interpretation and is preserved as temporally inconsistent,
not normalized into an exact timestamp. The canonical hotel night/day windows
are declared metadata only; date-level TCM is not an interval maximum.

No Cathedral heat probe was made. Cathedral route and building-height evidence
remain genuine, while its heat, modeled decision trigger, and optional
enrichment failure are synthesized and explicitly labeled demo evidence. Main
Plaza heat and non-routing sections are also synthesized demo evidence; the
Market Square no-feature result was intentionally not committed. Briscoe's
core failure is synthesized and does not claim geographic provider failure.

The offline backend and network-blocked E2E coverage exercise all four
scenarios through the same strict live/fixture/HTTP v2 codec. Snapshot
generation checks input hashes, round-trip stability, and overwrite safety.

## Desired Behavior First

The scenario matrix is about product states, not three geographic phenomena.
Only the route count and OSM height coverage can be observed from place-dependent
public data.

### A. One returned route

The product definition is one valid pedestrian route **returned by the configured
routing provider**. It is not a claim that only one pedestrian route exists in
San Antonio. `CONTEXT.md` and ADR 0006 require the product to show the returned
route with limited-comparison wording and never fabricate a second route.

The evidence must therefore preserve:

- the exact endpoint coordinates and order;
- the configured FOSSGIS instance and `foot` profile;
- `alternatives=true`, `overview=full`, `geometries=geojson`, and `steps=false`;
- the complete returned geometry and route facts;
- retrieval time and provider/configuration versions.

### B. Weak height evidence and unavailable optional enrichment

These are two independent states paired in one fixture:

- Weak height coverage is an observed OSM-data property under the repository's
  model. The route's 250 m projected corridor includes relevant `building` and
  `building:part` footprints. Usable area is the unioned footprint area with a
  valid explicit `height`, or a valid `building:levels` converted at 3 m per
  level. Coverage is usable area divided by all relevant effective footprint
  area. No footprint means zero coverage. The default sufficiency threshold of
  0.70 is product policy, not an OSM or scientific threshold.
- Hotel enrichment unavailability is an **injected optional-provider response
  state**. Repository tests require optional-enrichment failure to preserve the
  base ranking. No address, route, district, or OSM tag makes a premium service
  unavailable.

For a daytime elevated-heat fixture, accepted ADR 0007 supersedes older design
text: weak shade evidence keeps all route and partial metrics visible but makes
**no route recommendation**. It must not silently fall back to the shortest
route. This research measures building-height coverage only; it does not measure
or claim shade.

### C. Core heat failure

The initial TCM heatmap is load-bearing. In
`TemporalTripAnalysisAdapter.analyze`, failure of that request or inability to
select its anchor immediately creates an unavailable trip response. ADR 0004
defines the chain as live -> exact cache -> matching fixture -> explicit
unavailable.

San Antonio is inside the supported United States geography. Geography therefore
cannot honestly be selected to force the configured core heat provider to fail.
The failure fixture must be a deterministic synthesized response state, such as
provider `Failed`, bounded polling exhaustion, rate limiting, or network failure,
combined with intentional absence of an exact cache/matching successful fixture.
It must not say that the Briscoe, Hemisfair, or San Antonio lacks heat coverage
unless an authenticated acquisition separately establishes that fact. No such
request was made here.

## Coordinate And Identity Rules

All pinned endpoint values below are WGS84 decimal degrees from the named
Nominatim result for the specified OSM object. Nominatim describes these values
as `lat` and `lon`; for ways, they are search-result centroids rather than an
entrance or official owner-published coordinate.

Use the representations consistently:

- Product/domain and documentation form: `(latitude, longitude)`.
- OSRM path form: `longitude,latitude;longitude,latitude`.
- GeoJSON route vertices: `[longitude, latitude]`.
- OSM identity: immutable pair `<object type>/<numeric ID>`, retained separately
  from display name and coordinates.
- Routing snap points are response observations only. They are not replacement
  place coordinates and are not official geocodes.

Official or owner/operator pages establish place identity and address where
available. OSM/Nominatim establishes the selected machine coordinate and OSM
object identity. This mixed provenance is deliberate and must remain visible.

## Recommendation A: Main Plaza To Historic Market Square

### Pinned trip

| Field                           | Origin                                                                      | Destination                                                                                            |
| ------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Display name                    | Main Plaza                                                                  | Historic Market Square (El Mercado)                                                                    |
| Direction                       | Origin                                                                      | Destination                                                                                            |
| Product coordinate `(lat, lon)` | `(29.4245773, -98.4935063)`                                                 | `(29.4254009, -98.4994785)`                                                                            |
| OSRM coordinate `lon,lat`       | `-98.4935063,29.4245773`                                                    | `-98.4994785,29.4254009`                                                                               |
| Coordinate meaning              | Nominatim centroid of the mapped park polygon                               | Nominatim centroid of the mapped El Mercado building footprint                                         |
| OSM identity                    | `way/93118472`                                                              | `way/79636475`                                                                                         |
| OSM classification              | `leisure=park`, `name=Main Plaza`, operator City of San Antonio             | `building=yes`, `name=El Mercado`, address 514 West Commerce Street                                    |
| Identity/address authority      | Main Plaza Conservancy identifies Historic Main Plaza at 115 N. Main Avenue | City of San Antonio's Historic Market Square site identifies the attraction and 514 W Commerce address |
| Evidence classification         | Owner/operator identity and address; crowd-sourced centroid/object          | Official city identity and address; crowd-sourced centroid/object                                      |
| District label for fixture      | Downtown / Main Plaza                                                       | Downtown / Cattleman's Square / Historic Market Square                                                 |

The destination display name should lead with the visitor-facing official name,
`Historic Market Square`, while retaining `(El Mercado)` to explain that the
pinned coordinate belongs to OSM's building object named `El Mercado`. Do not
silently call the whole Market Square campus OSM way 79636475.

### Observed routing fact

Public GET request, retrieved 2026-08-30 at approximately 12:21 UTC:

```text
https://routing.openstreetmap.de/routed-foot/route/v1/foot/-98.4935063,29.4245773;-98.4994785,29.4254009?alternatives=true&overview=full&geometries=geojson&steps=false
```

Observed response facts:

- top-level code: `Ok`;
- routes in this response: `1`;
- returned route: 635.7 m, 510.7 s, 47 GeoJSON points;
- origin snap: `[-98.493819, 29.424595]`, 30.43824485 m from the supplied
  coordinate, unnamed;
- destination snap: `[-98.499459, 29.425583]`, 20.26653002 m from the supplied
  coordinate, unnamed.

Correct fixture language: **"One valid pedestrian route was returned for this
configured request when retrieved on 2026-08-30."** Never say "only one route
exists" or "there is only one way to walk there."

### Rationale and caveats

- The 635.7 m trip is close enough for a plausible tourist walk but sufficiently
  long to avoid the near-identical-path behavior of adjacent plaza endpoints.
- It travels west from San Antonio's civic center to a major official visitor
  destination and remains near the canonical downtown scenario.
- Both supplied points snap by 20-30 m. Preserve the snaps as routing evidence;
  do not promote them to fixture place identity.
- FOSSGIS routing data and algorithms are mutable. Reacquisition may return a
  different route count, geometry, distance, duration, or snap. The committed
  response remains an honest time-stamped observation even if a later live
  request differs.

## Recommendation B: San Fernando Cathedral To Spanish Governor's Palace

### Pinned trip

| Field                           | Origin                                                                               | Destination                                                                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| Display name                    | San Fernando Cathedral                                                               | Spanish Governor's Palace                                                                                                            |
| Direction                       | Origin                                                                               | Destination                                                                                                                          |
| Product coordinate `(lat, lon)` | `(29.4245590, -98.4942042)`                                                          | `(29.4248225, -98.4959872)`                                                                                                          |
| OSRM coordinate `lon,lat`       | `-98.4942042,29.4245590`                                                             | `-98.4959872,29.4248225`                                                                                                             |
| Coordinate meaning              | Nominatim centroid of mapped cathedral footprint                                     | Nominatim centroid of mapped museum footprint                                                                                        |
| OSM identity                    | `way/80647022`                                                                       | `way/78601534`                                                                                                                       |
| OSM classification              | `amenity=place_of_worship`, `building=cathedral`, `historic=church`                  | `tourism=museum`, `historic=yes`, `amenity=attraction`                                                                               |
| Address evidence                | OSM: 115 West Main Plaza, 78205                                                      | OSM object has no address tags in the retrieved API response                                                                         |
| Evidence classification         | Crowd-sourced centroid/object/address; named institution website is linked on object | Crowd-sourced centroid/object; City venue identity should be retained as first-party identity evidence when acquisition is finalized |
| District label for fixture      | Downtown / Main Plaza                                                                | Downtown / Military Plaza                                                                                                            |

### Observed routing facts

Public GET request, retrieved 2026-08-30 at approximately 12:21 UTC:

```text
https://routing.openstreetmap.de/routed-foot/route/v1/foot/-98.4942042,29.4245590;-98.4959872,29.4248225?alternatives=true&overview=full&geometries=geojson&steps=false
```

Observed response facts:

- top-level code: `Ok`;
- two routes were returned;
- route 1: 265.5 m, 212.3 s, 22 GeoJSON points;
- route 2: 278.6 m, 222.8 s, 19 GeoJSON points;
- origin snap: `[-98.494195, 29.424698]`, Trevino Street, 15.43188282 m;
- destination snap: `[-98.496276, 29.424823]`, Calder, 28.04388099 m.

### Reproduced building-height computation

The calculation used the repository code directly on 2026-08-30:

- `RouteShadeService` with `corridor_buffer_m=250.0`,
  `minimum_building_coverage=0.70`, and `metres_per_level=3.0`;
- both complete returned route geometries in one `RouteSet`;
- `_shared_bbox(routes, 250.0)` for the acquisition AOI;
- `build_building_query(aoi)` for `way` and `relation` objects tagged
  `building` or `building:part`, with `out body geom`;
- the production `_normalize_buildings` and per-route projected-corridor area
  calculation, including building-part precedence and unioning to prevent
  overlap double-counting.

Exact Overpass endpoint and query:

```text
POST https://overpass-api.de/api/interpreter

[out:json][timeout:60];
(way["building"](29.422431929,-98.498865419,29.427384596,-98.491604468);relation["building"](29.422431929,-98.498865419,29.427384596,-98.491604468);way["building:part"](29.422431929,-98.498865419,29.427384596,-98.491604468);relation["building:part"](29.422431929,-98.498865419,29.427384596,-98.491604468););
out body geom;
```

Observed Overpass and computed facts:

| Fact                            |              Route 1 |              Route 2 |
| ------------------------------- | -------------------: | -------------------: |
| OSM base timestamp              | 2026-08-30T12:21:50Z | same shared response |
| Elements in shared response     |                  126 | same shared response |
| Dropped geometry count          |                    0 |                    0 |
| Explicit-height footprint count |                    7 |                    7 |
| Inferred-level footprint count  |                   16 |                   16 |
| Unknown-height footprint count  |                   87 |                   87 |
| Explicit area fraction          |             0.074934 |             0.073649 |
| Inferred-level area fraction    |             0.271482 |             0.266825 |
| Unknown-height area fraction    |             0.653584 |             0.659526 |
| Usable building-height coverage |         **0.346416** |         **0.340474** |
| Against product threshold 0.70  |         insufficient |         insufficient |

Counts are counts of effective relevant footprints; coverage is area-weighted,
not count-weighted. The result is comfortably below 0.70, so normal OSM edits to
one small object are unlikely to move it across the gate, but the fixture must
still preserve the retrieved payload and timestamp because OSM is mutable.

No modeled-shade percentage is reported here. A shade estimate additionally
depends on an exact timezone-aware recommendation instant and solar geometry;
this research was limited to the height-evidence gate.

### Optional enrichment state

Pair this observed weak-height result with a **synthesized optional hotel
enrichment failure**:

- base hotel discovery, component heat values, ranking, ties, and percentiles
  remain present;
- `OptionalEnrichment.state` is `unavailable` with a nonblank reason such as
  `optional_provider_failure`;
- no failed premium payload is represented as provider-acquired unless a real,
  metered request is later made;
- the sidecar identifies the failure response as `source: synthesized`, with
  null activity ID and retrieval time as ADR 0004 requires;
- the trip text says the optional enrichment was unavailable, not that these
  places lack enrichment data.

This combination credibly demonstrates graceful degradation while retaining all
base results. Geography supplies the weak OSM evidence; deterministic injection
supplies the optional outage.

## Recommendation C: Briscoe Western Art Museum To Tower Of The Americas

### Pinned trip

| Field                           | Origin                                                               | Destination                                                                      |
| ------------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Display name                    | Briscoe Western Art Museum                                           | Tower of the Americas                                                            |
| Direction                       | Origin                                                               | Destination                                                                      |
| Product coordinate `(lat, lon)` | `(29.4228983, -98.4888465)`                                          | `(29.4190825, -98.4835734)`                                                      |
| OSRM coordinate `lon,lat`       | `-98.4888465,29.4228983`                                             | `-98.4835734,29.4190825`                                                         |
| Coordinate meaning              | Nominatim centroid of mapped museum footprint                        | Nominatim centroid of mapped tower footprint                                     |
| OSM identity                    | `way/337650172`                                                      | `way/78485919`                                                                   |
| OSM classification              | `tourism=museum`                                                     | `man_made=tower`, `tower:type=observation`, `tourism=attraction`                 |
| OSM address                     | 210 West Market Street, 78205                                        | 739 East Cesar E. Chavez Boulevard, 78205                                        |
| Evidence classification         | Owner website linked from OSM; crowd-sourced centroid/object/address | Owner website and GNIS ID linked from OSM; crowd-sourced centroid/object/address |
| District label for fixture      | Downtown / River Walk-Hemisfair edge                                 | Downtown / Hemisfair                                                             |

Accented street spelling in OSM (`César`) is display metadata, not part of
coordinate identity. Keep the exact OSM object IDs even if display copy is
normalized to ASCII elsewhere.

### Observed routing facts

Public GET request started and completed at 2026-08-30T12:30:23Z:

```text
https://routing.openstreetmap.de/routed-foot/route/v1/foot/-98.4888465,29.4228983;-98.4835734,29.4190825?alternatives=true&overview=full&geometries=geojson&steps=false
```

Observed response facts:

- top-level code: `Ok`;
- two routes were returned;
- route 1: 895.5 m, 718.1 s, 53 GeoJSON points;
- route 2: 928.4 m, 744.3 s, 64 GeoJSON points;
- origin snap: `[-98.488889, 29.423077]`, unnamed, 20.25512782 m;
- destination snap: `[-98.483512, 29.419322]`, unnamed, 27.14468665 m.

### Synthesized whole-trip unavailability

The place and route evidence is real. The core heat failure is not.

Recommended deterministic fixture semantics:

1. Construct the normal initial TCM request at the destination and chosen
   date/window.
2. Supply a sanitized synthesized core-provider failure response through the
   same validation/error path as live execution.
3. Ensure the test's cache is empty and no matching successful heat fixture is
   configured, so ADR 0004's degradation chain is genuinely exhausted.
4. Expect `TripAnalysisResponse.state=unavailable`, with best time, hotels, and
   routes absent rather than empty-success placeholders.
5. Record a clear error kind and reason. Do not imply the provider was contacted
   at fixture replay time.
6. In acquisition metadata use `source: synthesized`, null activity ID, null
   retrieval time, a non-success status, and the complete request identity.

The route response may be committed as a genuine public routing observation for
scenario provenance, but it should not appear in the unavailable product result:
the application exits at the failed initial TCM stage before route analysis.

## Required Place-Search Additions

The current `/api/places/search` implementation exposes only Menger Hotel and
The Alamo in both FastAPI and the stdlib fixture server. These alternate fixtures
will not be selectable by name until a later implementation issue adds the six
places below to both paths and their shared tests:

| Stable application ID suggestion    | Display name                        | Pinned coordinate         |
| ----------------------------------- | ----------------------------------- | ------------------------- |
| `main-plaza`                        | Main Plaza                          | `29.4245773, -98.4935063` |
| `historic-market-square-el-mercado` | Historic Market Square (El Mercado) | `29.4254009, -98.4994785` |
| `san-fernando-cathedral`            | San Fernando Cathedral              | `29.4245590, -98.4942042` |
| `spanish-governors-palace`          | Spanish Governor's Palace           | `29.4248225, -98.4959872` |
| `briscoe-western-art-museum`        | Briscoe Western Art Museum          | `29.4228983, -98.4888465` |
| `tower-of-the-americas`             | Tower of the Americas               | `29.4190825, -98.4835734` |

Application IDs are local stable identifiers, not substitutes for OSM object
identity. Search results or fixture metadata should retain the OSM type/ID and
coordinate provenance if the contract is extended to support them.

The current exploratory analysis path may also need fixture matching by the full
trip identity. Adding search options alone does not make an offline scenario
available.

## Rejected Candidates

| Candidate                                                                     | Observed facts                                                                                                                                      | Reason rejected for the final matrix                                                                                                                                                                                                                                                                                                       |
| ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Menger Hotel -> The Alamo                                                     | Issue #40 records one route, 193.1 m / 154.7 s, for its corrected request.                                                                          | Canonical scenario already owns best-time, hotel ranking, and multi-route comparison. Reusing it would not provide a genuine alternate fixture and its synthesized second route is not routing evidence.                                                                                                                                   |
| Main Plaza -> San Fernando Cathedral                                          | One route returned, 46.6 m / 37.2 s. Supplied centroids snapped 30.4 m and 15.4 m.                                                                  | Technically meets case A at retrieval time, but the route is shorter than the endpoint snap distances are collectively informative and the places share the same plaza. Main Plaza -> Market Square is a more credible tourist trip and stronger single-route demonstration.                                                               |
| Main Plaza -> Historic Market Square for weak height coverage                 | One route and computed usable-height coverage 0.332339; 9 explicit, 17 inferred, 111 unknown effective footprints; no dropped geometry.             | Excellent secondary evidence, but using it for B would collapse cases A and B onto one route. Keep it focused on the one-route state. Its weak coverage is a useful regression cross-check, not the primary B identity.                                                                                                                    |
| La Villita marker -> Yanaguana Garden                                         | Two routes: 361.0 m / 288.8 s and 392.4 m / 313.8 s. Coverage only 0.060348 and 0.059252.                                                           | Strongest weak-height numbers, but the selected Nominatim `La Villita` object is specifically a THC marker/plaque (`node/6541326018`), not the whole arts village, and Yanaguana lies south of the configured hotel district AOI. Use only if maintainers intentionally want a marker-to-park trip and expand/redefine district semantics. |
| Briscoe Western Art Museum -> Yanaguana Garden                                | Two routes: 627.9 m / 504.2 s and 659.3 m / 529.2 s.                                                                                                | Valid trip, but Yanaguana's park centroid snapped 15.7 m and its location is outside the current hotel district AOI. Briscoe -> Tower gives clearer owner-linked landmark identities for the synthetic core-failure scenario.                                                                                                              |
| San Fernando Cathedral -> Spanish Governor's Palace as the one-route scenario | Two routes returned: 265.5 m and 278.6 m.                                                                                                           | Does not satisfy A, but its two routes and measured 0.34 height coverage make it better for B.                                                                                                                                                                                                                                             |
| River Walk as an endpoint                                                     | No single pinned object was selected. "River Walk" describes a long linear system with many entrances and segments.                                 | A generic centroid would be ambiguous and likely route to an arbitrary segment. Pin a named access point or specific OSM object in a future scenario rather than forcing the famous name.                                                                                                                                                  |
| Hemisfair as an endpoint                                                      | Nominatim's direct result was `node/5748266904`, `place=neighbourhood`, at `29.4198530, -98.4840819`, with a broad 0.01-degree search bounding box. | This is a neighborhood label, not a precise visitor entrance. Tower of the Americas or Yanaguana Garden has a stronger object-level identity.                                                                                                                                                                                              |

## Observed Facts Versus Synthesized States

| Item                                                               | Classification                                            | Permitted claim                                                                                                                                                                            |
| ------------------------------------------------------------------ | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Landmark names and addresses on owner/operator or government pages | First-party public evidence                               | The named institution/place uses that identity or address.                                                                                                                                 |
| Nominatim centroids, categories, bounding boxes, and OSM IDs       | Crowd-sourced public observation                          | Nominatim returned this WGS84 point for this OSM object on the retrieval date.                                                                                                             |
| OSM API tags and footprint geometry                                | Crowd-sourced public observation                          | The object had these tags and nodes at retrieval; not official geodesy or an owner-published entrance.                                                                                     |
| FOSSGIS route count, length, duration, geometry, and snaps         | Public routing response observation                       | This configured request returned this response at this time. Never global route existence or optimality.                                                                                   |
| 0.3464/0.3405 building-height coverage                             | Reproducible local computation from observed OSM response | Under repository corridor/model semantics and the 2026-08-30 OSM snapshot, usable area was below the product's 0.70 threshold.                                                             |
| Modeled or measured shade                                          | Not established                                           | Make no shade claim from this research.                                                                                                                                                    |
| Optional hotel enrichment unavailable                              | Synthesized response state                                | The optional provider was unavailable in this deterministic fixture; base results were retained. Not a geographic property.                                                                |
| Core heat-provider failure                                         | Synthesized response state                                | The configured core provider failed and no exact fallback answered in this deterministic fixture, producing explicit whole-trip unavailable. Not evidence of San Antonio coverage failure. |

## Public Requests And Sources

All sources in this section were retrieved on **2026-08-30** unless a more exact
time is stated above. No credential, authenticated endpoint, metered endpoint,
or private source was used.

### Repository and issue sources

- [Issue #23](https://github.com/alshawai/heat-aware-tourism-guide/issues/23)
  and its comments, read with `gh issue view 23 --comments` and structured JSON.
  The comments pin canonical coordinates and warn that date-level TCM must not
  be presented as validated interval maxima.
- [Issue #40](https://github.com/alshawai/heat-aware-tourism-guide/issues/40)
  and its comments, read with `gh`; the detailed provenance is in
  [Issue #40 coordinate research](issue-40-menger-alamo-coordinates.md).
- [`CONTEXT.md`](../../CONTEXT.md), especially route-alternative,
  building-height-coverage, degradation, and unavailable-state definitions.
- [`docs/design/design-doc.md`](../design/design-doc.md), especially external
  contracts, route flow, fallback policy, fixture matrix, and canonical trip.
- [ADR 0004](../adr/0004-fixture-cache-provenance-ledger.md), fixture truth and
  live/cache/fixture/unavailable degradation.
- [ADR 0005](../adr/0005-best-time-decision-orchestration.md), core TCM versus
  optional environmental/framing evidence.
- [ADR 0006](../adr/0006-returned-route-heat-analysis.md), one routing request,
  returned-route scope, and single-route behavior.
- [ADR 0007](../adr/0007-exact-time-modeled-shade-decisions.md), accepted weak
  daytime shade-evidence behavior.
- [`app/services/route_shade.py`](../../app/services/route_shade.py), production
  corridor, geometry normalization, area weighting, and confidence calculation.
- [`app/services/trip_adapters.py`](../../app/services/trip_adapters.py), initial
  TCM failure creating whole-trip unavailable.
- [`tests/test_route_shade_service.py`](../../tests/test_route_shade_service.py),
  threshold and no-building semantics.
- [`tests/test_execution_degradation.py`](../../tests/test_execution_degradation.py),
  exact fallback exhaustion.
- [`tests/test_application_domain.py`](../../tests/test_application_domain.py),
  optional enrichment preserving base ranking after failure.

### Place identity and coordinate sources

- Main Plaza Conservancy, [Main Plaza](https://www.mainplaza.org/): place
  identity and 115 N. Main Avenue location.
- City of San Antonio, [Historic Market Square](https://www.marketsquaresa.com/):
  official place identity and 514 W Commerce address.
- Hemisfair, [Yanaguana Garden venue](https://hemisfair.org/venue/yanaguana-garden/):
  first-party identity, 434 S. Alamo Street address, and published map point
  `29.4195672,-98.487857` used only as a cross-check, not as a selected endpoint.
- Texas Historical Commission,
  [La Villita marker record 5029003006](https://atlas.thc.texas.gov/Details/5029003006):
  official marker identity, location on Villita Road, and UTM values. The datum
  is not stated, so this research does not convert or use them as the endpoint.
- Nominatim query,
  [Main Plaza](https://nominatim.openstreetmap.org/search?q=Main+Plaza%2C+San+Antonio%2C+TX&format=jsonv2&limit=5).
- Nominatim query,
  [El Mercado](https://nominatim.openstreetmap.org/search?q=El+Mercado%2C+San+Antonio%2C+Texas&format=jsonv2&limit=5).
- Nominatim query,
  [San Fernando Cathedral](https://nominatim.openstreetmap.org/search?q=San+Fernando+Cathedral%2C+San+Antonio%2C+TX&format=jsonv2&limit=5).
- Nominatim query,
  [Spanish Governor's Palace](https://nominatim.openstreetmap.org/search?q=Spanish+Governor%27s+Palace%2C+San+Antonio%2C+TX&format=jsonv2&limit=5).
- Nominatim query,
  [Briscoe Western Art Museum](https://nominatim.openstreetmap.org/search?q=Briscoe+Western+Art+Museum%2C+San+Antonio%2C+TX&format=jsonv2&limit=5).
- Nominatim query,
  [Tower of the Americas](https://nominatim.openstreetmap.org/search?q=Tower+of+the+Americas%2C+San+Antonio%2C+TX&format=jsonv2&limit=5).
- OSM API full objects:
  [Main Plaza way 93118472](https://api.openstreetmap.org/api/0.6/way/93118472/full),
  [El Mercado way 79636475](https://api.openstreetmap.org/api/0.6/way/79636475/full),
  [San Fernando Cathedral way 80647022](https://api.openstreetmap.org/api/0.6/way/80647022/full),
  [Spanish Governor's Palace way 78601534](https://api.openstreetmap.org/api/0.6/way/78601534/full),
  [Briscoe way 337650172](https://api.openstreetmap.org/api/0.6/way/337650172/full), and
  [Tower way 78485919](https://api.openstreetmap.org/api/0.6/way/78485919/full).

### Routing and building sources

- FOSSGIS pedestrian OSRM public instance:
  `https://routing.openstreetmap.de/routed-foot/route/v1`, using the exact GET
  URLs preserved in each recommendation. This is the repository default in
  `app/settings.py`.
- Public Overpass endpoint: `https://overpass-api.de/api/interpreter`, using the
  exact POST query preserved under Recommendation B. The response reported OSM
  base timestamp `2026-08-30T12:21:50Z`.
- OpenStreetMap attribution and license were reported by Nominatim and OSM API as
  OpenStreetMap contributors, ODbL 1.0.

Several City of San Antonio deep links for Main Plaza, La Villita, the Cathedral,
and Spanish Governor's Palace returned HTTP 403 to the research client. This is
why the note uses accessible first-party pages where available and explicitly
classifies the remaining OSM identity evidence rather than pretending an
official coordinate was published.

## Mutable External-Data Risks

- OSM objects can be retagged, moved, split, merged, deleted, or superseded.
  Names and coordinates are not object identities; preserve type and ID plus the
  acquisition payload and OSM base timestamp.
- Nominatim search ranking and centroids can change independently of the
  underlying landmark's real-world identity. Preserve the selected result, not
  merely the query string.
- FOSSGIS can update OSM extracts, foot-profile configuration, routing software,
  or alternative-generation behavior. A later `alternatives=true` call may
  return a different count. Time-stamped fixture provenance prevents that from
  invalidating the original observation.
- Distances and durations are provider estimates, not measured walking traces.
- Building-height coverage can change as `height`, `building:levels`, building
  parts, or footprints change. Preserve the complete Overpass response because
  storing only 0.34 cannot reproduce the result.
- A 250 m route corridor covers a broad downtown area; its coverage describes
  relevant mapped footprint area under the current model, not the visual quality
  of the immediate sidewalk.
- First-party sites can rename venues or change addresses. Keep retrieval date
  and do not overwrite OSM provenance with owner-page claims.
- Synthesized provider failures must never gain a fake retrieval timestamp,
  activity ID, HTTP status, or provider claim during fixture maintenance.

## Settled By Implementation

1. Case B follows ADR 0007: weak height evidence preserves both routes and makes
   no daytime route recommendation. The stale shortest-route prose in the
   accepted design documents has been corrected.
2. The visitor-facing destination label is `Historic Market Square (El
Mercado)`; its selected identity remains the narrower OSM building centroid
   `way/79636475`.
3. OSRM and Overpass payloads have dedicated provider sidecars with their own
   provider identities and configuration versions.
4. Case B uses synthesized `optional_provider_failure`; case C uses synthesized
   `provider_data_missing`, exercising structured response contracts rather than
   implying provider or geographic failure.
5. Case C's genuine route observation is retained as separate provenance even
   though the product result stops at the initial TCM failure and does not return
   routes.
6. The canonical hotel AOI remains `Downtown San Antonio`; alternate route and
   building evidence remains fixture-specific. A trip can be a
   supported San Antonio trip without redefining the canonical hotel district,
   but alternate hotel-ranking fixtures need an explicit district AOI rather
   than silently reusing the canonical one.
7. Decide whether exploratory place-search additions are in Issue #23 or a
   follow-up. Fixture acquisition can proceed without UI search, but offline
   users cannot select these scenarios by name until both server paths agree.
8. At acquisition time, rerun all three OSRM requests once, preserve complete
   raw responses and exact UTC retrieval timestamps, and fail fixture generation
   rather than forcing the expected matrix if mutable public data no longer
   returns the observed state.

## Final Recommendation

Proceed with the three directed identities as pinned:

1. **Main Plaza -> Historic Market Square (El Mercado):** observed one-route
   fixture, with 635.7 m as the current recorded route length.
2. **San Fernando Cathedral -> Spanish Governor's Palace:** observed two-route,
   weak-height fixture, with repository-computed coverage near 0.34 on both
   routes; pair it with an honestly synthesized optional-enrichment outage while
   retaining base results.
3. **Briscoe Western Art Museum -> Tower of the Americas:** real supported trip
   identity paired with an honestly synthesized, degradation-chain-exhausting
   core TCM failure and explicit whole-trip unavailable.

These selections cover the agreed edge cases without claiming measured shade,
geographic enrichment failure, geographic heat-provider failure, global route
uniqueness, or provider facts that were not observed.
