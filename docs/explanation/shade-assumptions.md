# Explanation: Shade Assumptions

What "modeled building shade" is, what feeds it, and what it must never be
claimed to be. Code: `app/domain/route_shade.py` and
`app/services/route_shade.py`; the decision policy is
[ADR 0007](../adr/0007-exact-time-modeled-shade-decisions.md).

## The model

For each returned route, the product:

1. Acquires OSM `building` and `building:part` ways and relations within a
   250 m corridor (`SHADE_BUILDING_SEARCH_DISTANCE_M`) via one bounded
   Overpass query.
2. Resolves each footprint's height: a valid explicit `height` tag first
   (feet converted at 0.3048 m/ft); otherwise a valid `building:levels`
   multiplied by the documented 3 m-per-level approximation
   (`SHADE_METRES_PER_LEVEL`); otherwise unknown. Height origin is tracked
   as `explicit`, `inferred_levels`, or `unknown`.
3. Computes the solar position (azimuth and elevation, solar model identity
   `astral-3.2-apparent`) for the exact recommended local timestamp in the
   canonical timezone.
4. Projects building-shadow geometry and reports the fraction of the route's
   length intersecting it while the sun is above the horizon.

The result is a deterministic function of the OSM snapshot, the height
rules, and the timestamp — labeled "modeled shade estimate, based on OSM
building data".

## Coverage and confidence

**Building-height coverage** is the area-weighted fraction of relevant
footprints in the route's analysis corridor with explicit or inferred
heights. A route with no mapped footprints has zero coverage. The 0.70
sufficiency default (`SHADE_MINIMUM_BUILDING_HEIGHT_COVERAGE`) is product
policy, not an OSM or scientific standard.

Measured downtown examples: the canonical corridor's 2017 USGS-lidar
validation found modeled heights for 5/5 intersecting footprints, while the
Cathedral-to-Governor's-Palace corridor computes roughly 0.34 on current
OSM tags — comfortably below the gate. Both are recorded with their methods
in [the issue 7 note](../research/issue-7-san-antonio-provider-validation.md)
and [the issue 23 scenarios note](../research/issue-23-alternate-scenarios.md).

## What the model excludes

- Trees, awnings, canopies, and other vegetation or temporary structures —
  no data source represents them here.
- Clouds and weather; shadows are clear-sky geometry.
- Terrain and sidewalk side; the model is 2D footprints extruded by height.
- OSM errors and omissions: missing, stale, moved, or split footprints, and
  inaccurate or absent `height`/`building:levels` tags.
- Sub-footprint detail such as architectural setbacks.

The lidar feasibility study ([research note](../research/lidar-dsm-shade-feasibility-austin-san-antonio.md))
established that USGS classified point clouds can supply modeled heights
where OSM tags are sparse — used as research validation, not as a
production shade source.

## Decision behavior

- **Nighttime** (sun at or below the horizon): building shade is zero and
  not applicable; the coolest returned route by retained route TCM is
  recommended, with distance breaking exact ties.
- **Sufficient coverage**: the shadiest returned route (or the only route)
  is recommended among returned alternatives.
- **Insufficient coverage**: all alternatives and available metrics stay
  visible, but the product makes **no route recommendation** — the traveler
  compares the trade-offs. There is no shortest-route fallback that would
  masquerade as a heat-informed answer.

## Wording rules

"Modeled shade estimate, based on OSM building data" — never "measured",
"observed", or "real-world" shade. Results carry the shade limitations list
and the model/provider version identities.
