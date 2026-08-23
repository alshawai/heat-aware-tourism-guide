# FortyGuard Extraction Contracts

The application integration is server-side and supports fixture execution without
provider credentials. `app.fortyguard` owns request validation, authenticated
submit/poll behavior, provider error classification, and normalization into the
internal tile shape. A submitted activity is polled at most `max_polls` times;
the first status `404` is tolerated because the provider may not expose a newly
submitted activity immediately. The client never resubmits a billable activity.

All heat values are stored in Celsius. `tcm` is a provider temperature metric and
is not silently labeled as NOAA Heat Index. Forecast and historical results retain
separate status in the request and normalized provenance. Normalized tiles require
geometry, Celsius units, and a `valid_time` freshness field. The raw sanitized
provider payload is retained on the result for fixture/debugging use and is not
ordinary log output.

`app.cache.CacheService` hashes the complete canonical request payload together
with endpoint and schema version. Cache hits are explicitly marked `source=cache`
and `stale=true`; a replay is never presented as a current forecast. Activity IDs,
retrieval timestamps, and data dates remain available in provenance.

Spatial joins are behind an adapter boundary. Polygon joins must be area-weighted
in a projected CRS and report coverage. Point joins distinguish containing-tile,
boundary, outside-AOI, and nearest-distance fallback results. The base product
flow does not depend on optional enrichment: `EnrichmentPlanner` bounds selection
by top-N and available credits, and readiness reason codes are deterministic local
logic.

The repository intentionally does not include live acquisition scripts. Live calls
are metered manual operations. Polygon joins and AOI construction use pinned
Shapely and pyproj dependencies, select a local UTM projected CRS, reject invalid
geometry, and expose coverage or point-match quality.

The fixture-backed HTTP boundary is `POST /api/heatmap`. It accepts an analytic
type, US coordinates, start date, forecast flag, and optional threshold/direction,
then returns the same normalized tile and provenance shape used by the execution
layer. Invalid requests and unavailable fixtures return an explicit `unavailable`
error; provider credentials never cross this boundary.

## Live transport

`HttpFortyGuardTransport` is the concrete server-side HTTP adapter. It sends
JSON to the configured base URL using the `X-API-Key` header and a bounded
socket timeout. HTTP and network failures are classified without retaining a
response body. A heatmap activity is submitted once; transient status lookup
failures consume the bounded polling budget and never trigger submission again.

`HeatmapRequest.to_payload()` preserves the analytic type, US coordinates,
start date, forecast/historical status, threshold, and direction. Area requests
accept caller-supplied Polygon or MultiPolygon geometry for district or corridor
contexts and identify whether Celsius units were explicit or inferred.

## Environmental parameters

The optional `env_params` adapter is guarded by the committed
`fixtures/env-params.json` contract. Its caller must supply a Celsius temperature
anchor. The normalized result always carries the warning that a fixed-anchor
series is not a real 24-hour forecast. `heat_index_celsius`, when present, is a
separate metric and does not rename or reclassify `tcm`.

## Budget and decisions

The operational ledger records actual provider-reported credits by activity ID,
endpoint, completion time, and status. Planned optional enrichment is recorded
separately and does not count as actual spend. Budget enforcement occurs before
an actual usage record is accepted.

`POST /api/trip/analyze` is the product-level decision boundary. Hotel ranking
uses the documented provisional component weights, retains components, and
reports ties and candidate-set percentiles rather than an absolute grade. Route
comparison consumes one supplied route set, uses maximum corridor heat, avoids
shade work below the heat threshold, and recommends the shortest route when
building-height coverage is insufficient.

## Known limitations

Live acquisition remains a deliberate, metered maintainer operation outside CI.
The HTTP transport has no implicit submission retry because a failed response
does not prove that a billable activity was not created. The current trip endpoint
accepts already-acquired hotel, route, heat, and shade inputs; OSRM, Overpass,
building-height parsing, and shade modeling are separate application integrations.
P2 Fahrenheit presentation helpers and operational exports remain deferred.
