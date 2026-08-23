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
