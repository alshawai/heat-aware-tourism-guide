# Proposal Fact Check

This note records externally verifiable constraints used by
`docs/design/design-doc.md`. It distinguishes provider facts from project
policies and engineering heuristics.

## FortyGuard

Sources:

- [API introduction](https://docs-api.fortyguard.com/docs/introduction)
- [Create heatmap](https://docs-api.fortyguard.com/docs/create-heatmap)
- [Environmental parameters](https://docs-api.fortyguard.com/docs/environmental-parameters)
- [Check status](https://docs-api.fortyguard.com/docs/check-status)
- [Known limitations](https://docs-api.fortyguard.com/docs/limitations)
- [API pricing](https://fortyguard.com/api-pricing)

Verified facts:

- The documented endpoints are `POST /v1/heatmap`, `POST /v1/env_params`,
  and `GET /v1/status/{activity_id}`.
- Requests are asynchronous: submit an activity, poll its status, then
  consume the completed result or record failure.
- Heatmap analysis values include `tcm`, `exceedance`, and `persistence`.
- `exceedance` and `persistence` accept a Celsius threshold and direction;
  the documented default threshold is 30 C.
- Environmental parameters include `heat_index_celsius` and return timezone
  metadata. Missing values may be `null` or legacy `-999`.
- Heatmap areas use a closed GeoJSON polygon and documented 60 m, 80 m, or
  100 m granularity. Basic/Startup areas are documented up to 10 mi2;
  Premium areas up to 50 mi2.
- The documented current release supports US locations and heatmap forecasts
  up to 12 hours ahead.
- The API uses an `api-key` header. Public documentation does not establish
  exact per-request credit costs or numeric rate limits.
- Premium-only endpoint availability includes satellite segmentation,
  street-view segmentation, and Heat Intelligence. The latter may take
  several minutes and returns a temporary download link.

Project consequences:

- `tcm` is not silently classified as NOAA Heat Index. Actual
  `heat_index_celsius` is preferred for NOAA categories.
- Every successful acquisition records observed credit usage, latency, status,
  and sanitized provenance because published costs are incomplete.
- Public deployment uses fixtures by default; live API access is a maintainer
  capability.

## OSRM, OSM, And Overpass

Sources:

- [OSRM HTTP API](https://project-osrm.org/docs/v5.24.0/api/)
- [OSRM walking profile](https://raw.githubusercontent.com/Project-OSRM/osrm-backend/master/profiles/foot.lua)
- [OSM `height`](https://wiki.openstreetmap.org/wiki/Key:height)
- [OSM `building:levels`](https://wiki.openstreetmap.org/wiki/Key:building:levels)
- [OSM `tourism=hotel`](https://wiki.openstreetmap.org/wiki/Tag:tourism%3Dhotel)
- [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)

Verified facts:

- OSRM alternatives are optional and not guaranteed. A single request can
  return the primary route and available alternatives.
- Full GeoJSON geometry should be requested for segment processing; simplified
  geometry is not sufficient for detailed shade estimates.
- OSRM's supplied foot profile is pedestrian-oriented but does not model heat,
  shade, building heights, or solar position.
- OSM `height` is normally metres and represents maximum building height.
- `building:levels` counts above-ground non-roof levels; multiplying by about
  3 m is an approximation, not a measured height.
- Hotels may be nodes, ways, or relations. `tourism=hotel` describes the
  establishment; nearby objects are not automatically duplicates.
- Public Overpass instances are shared resources. They may throttle or reject
  requests, and documented guidance includes handling HTTP 429 with a delay.

Project consequences:

- The UI says “shadiest among returned alternatives,” not “globally shadiest.”
- Height sources are tracked as explicit, inferred, or unknown.
- Hotel deduplication uses identity and metadata before proximity.
- Overpass results are bounded, cached, and never required for CI.

## NOAA And Public-Health Guidance

Sources:

- [NWS Heat Index](https://www.weather.gov/safety/heat-index)
- [NWS Heat Index calculator](https://www.wpc.ncep.noaa.gov/html/heatindex.shtml)
- [NOAA Solar Position Calculator](https://gml.noaa.gov/grad/solcalc/azel.html)
- [NOAA calculation details](https://gml.noaa.gov/grad/solcalc/calcdetails.html)
- [NWS heat safety](https://www.weather.gov/safety/heat)
- [WHO heat and health](https://www.who.int/news-room/fact-sheets/detail/climate-change-heat-and-health)

Verified facts:

- NOAA/NWS Heat Index categories use 80, 90, 105, and 130 F boundaries,
  approximately 26.7, 32.2, 40.6, and 54.4 C.
- NOAA categories are Caution, Extreme Caution, Danger, and Extreme Danger;
  “comfortable” is not a NOAA category.
- Heat Index assumes shady, light-wind conditions and is distinct from WBGT.
- NOAA solar calculations provide azimuth clockwise from north and elevation
  above the horizon, but NOAA documents them as approximate and notes the
  calculator is no longer actively maintained.
- NOAA and WHO identify older adults and people with chronic conditions as
  heat-vulnerable groups and support more cautious behavior.

Project policies and heuristics, not published standards:

- A 1,500 m short/long route threshold.
- A 35 C exceedance/persistence threshold.
- Hotel weights of 35/25/20/20 percent.
- Shifting the action threshold one band earlier for cautious guidance.
- Product-only `tcm` bands at 30, 35, and 40 C; these are not NOAA boundaries.
- Maximum corridor heat aggregation.
- A building-height coverage threshold for trusting modeled shade.

These policies must be labeled as such and tested through sensitivity analysis.
The route result is a modeled building-shadow estimate, not measured or exact
real-world shade.
