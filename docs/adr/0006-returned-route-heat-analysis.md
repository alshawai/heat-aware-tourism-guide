# ADR 0006: Returned-route heat analysis and recommendation staging

Date: 2026-08-29
Status: Accepted

## Context

Issue #18 adds pedestrian route alternatives after the best-time decision. The
product must compare only routes returned by OSRM, make exactly one routing
request per trip, avoid repeated landmark heat work, and bound FortyGuard
spend. It must still expose a conservative heat value for every usable returned
route so issue #19 can decide whether modeled shade is required.

A heatmap per route would multiply billable activities. A heatmap covering only
the shortest route would not provide evidence for the other alternatives. The
existing area adapter can request a bounding-box AOI, which live validation
showed gives more complete provider-grid coverage than a thin corridor.

The route contract must also distinguish a mild-heat recommendation from an
elevated-heat result awaiting shade. Requiring issue #18 to choose a final route
under elevated heat would conflict with issue #19, which owns the modeled-shade
recommendation.

## Decision

The server makes one OSRM request with the configured pedestrian profile,
alternatives enabled, and full GeoJSON geometry. It accepts one or more valid
returned routes and never fabricates alternatives.

When every returned route is at or below the configurable representative
distance threshold, every route reuses
`BestTimeResult.recommended_hour_tcm_celsius`. No additional FortyGuard
activity is started.

When any returned route exceeds that threshold, the server creates one buffered
bounding rectangle covering all returned route geometries and requests one TCM
heatmap for the best-time recommendation hour. The complete AOI geometry,
provider instance, request options, and relevant versions participate in cache
and fixture identity. Each route is joined locally to the shared normalized
tiles in a projected CRS. Its route heat is the maximum intersecting tile or
segment value, never an average, and its coverage is reported separately. Route
heat evidence is sufficient at or above the configurable route-heat coverage
threshold, defaulting to the repository's existing 0.70 product coverage gate;
this is separate from issue #19's building-height coverage.

Mild route heat recommends the shortest returned route and skips shade.
Elevated route heat retains all route temperatures but leaves the final route
recommendation pending for issue #19. The lowest-heat route remains evidence,
not a final recommendation. Cautious guidance uses the existing one-band-earlier
heat policy.

A single valid route remains usable and is identified as the only returned
route with limited-comparison wording. `no_suitable_returned_route` is reserved
for zero valid routes or for a route set in which every route lacks sufficient
evidence for a recommendation.

OSRM and corridor-heat failures follow live to exact cache to matching fixture
to explicit unavailability. Long routes never substitute landmark heat for
missing corridor evidence.

## Consequences

- Route acquisition remains one external routing request per trip.
- Long-route heat analysis remains one billable FortyGuard activity regardless
  of the number of returned alternatives.
- A long alternative causes shared corridor analysis even when the shortest
  route is below the representative threshold. This intentionally sharpens the
  original issue wording so every compared route has valid heat evidence.
- The 0.70 route-heat coverage default is a declared, configurable product
  policy and must not be presented as a provider or scientific standard.
- The route response needs explicit decision and route-set states, nullable heat
  and recommendation fields, full geometry, per-route coverage, and separate
  routing and heat provenance.
- Issue #19 can consume all returned geometries and route temperatures without
  repeating OSRM or heatmap work, then complete an elevated-heat recommendation
  from modeled shade and coverage.
- Issue #20 can display single-route, mild-shortest, awaiting-shade,
  heat-unavailable, and no-suitable-route states without inferring them from
  missing fields.
