# ADR 0007: Exact-time modeled shade and evidence-based route decisions

Date: 2026-08-30
Status: Accepted

## Context

Issue #19 completes ADR 0006's elevated-heat route stage with deterministic
OSM building-shadow estimates. Solar geometry depends on an exact instant, but
the current best-time contract reduces provider evidence to a whole-hour
integer. Building data can also be incomplete, and building shade is physically
irrelevant while the sun is below the horizon. A forced shortest-route fallback
would hide these distinctions and prevent travelers from evaluating the route
metrics that remain available.

## Decision

`BestTimeResult` retains the unique timezone-aware TCM `valid_time` for the
recommended period as its exact recommendation timestamp and carries the named
local timezone. Shade analysis never invents a timestamp when selected-hour
TCM tiles disagree. The canonical trip uses `America/Chicago` only as an
explicitly recorded fallback when environmental timezone metadata is
unavailable.

For positive solar elevation, the product may perform one shared OSM building
acquisition and calculate modeled building shade for every returned route.
Sufficient evidence recommends the returned route with the highest modeled
building-shade percentage, breaking ties by distance and then stable route
identity. A single sufficiently evidenced route is recommended as the only
returned route with limited-comparison wording.

For solar elevation at or below the horizon, building shade is zero and not
applicable. The product performs no OSM building acquisition and recommends the
coolest returned route from retained route TCM evidence, using distance and
then stable identity only to break equal-temperature ties.

Weak or uncomputable daytime shade evidence preserves every valid returned
alternative and all available distance, TCM, coverage, and partial-shade
metrics, but produces no recommendation. The traveler-facing UI owns the
trade-off presentation. This deliberately replaces issue #19's original
shortest-route fallback and the legacy `RouteComparator` prototype rule.

## Consequences

- Exact temporal evidence becomes part of the best-time and route contracts.
- Shade confidence has `sufficient`, `insufficient`, and `not_applicable`
  states; nighttime is not represented as missing data.
- Final route states distinguish shadiest, only-route, nighttime-coolest, and
  insufficient-comparison outcomes.
- OSM acquisition, cache, fixtures, and building-height quality affect daytime
  confidence without erasing partial evidence.
- Issue #20 can present unresolved route trade-offs without reverse-engineering
  them from missing recommendation fields.
