# Issue #7: San Antonio Scenario And Provider Validation

**Original research date:** 2026-08-23
**Continuation live-call date:** 2026-08-24
**Acceptance-language audit date:** 2026-08-24

**Issue:** [Validate San Antonio scenario and provider contracts](https://github.com/alshawai/heat-aware-tourism-guide/issues/7)

This single artifact preserves the 2026-08-23 OSM and OSRM observations and
adds the authorized, manually metered FortyGuard and route-corridor calls made
on 2026-08-24.

## Executive Decision

San Antonio is **final primary** and Austin is **final fallback**. San Antonio
has the stronger canonical scenario evidence: at least five conservative hotel
candidates, a profile-specific FOSSGIS foot response with two full-geometry
alternatives, and a new populated FortyGuard heatmap. The environmental
submission also completed and returned timestamped provider parameters. The
heatmap lacks an explicit unit/valid-time field, and the environmental result
is a caller-supplied-temperature analysis rather than a real provider forecast,
so the provider-to-app contract is not fully reconciled. A two-submission
historical heatmap experiment also completed with byte-identical canonical
results, so repeatability is now observed. These are app/provider follow-ups,
not reasons to make the city choice conditional.

Use the committed fixture path until the provider/app follow-up is implemented.
The original OSM-only height coverage was insufficient, but the subsequent USGS
classified-lidar corridor validation supplies modeled heights for every
intersecting OSM building footprint in the bounded sample. The current result
is sufficient modeled-height coverage for the criterion, with explicit source
date and validation caveats; it is not a claim that every projected shadow is
observed or production-validated.

## Acceptance-Criteria Ledger

| Criterion                                | Result                            | Evidence and consequence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ---------------------------------------- | --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Populated FortyGuard heatmap          | **Pass**                          | The new bounded San Antonio request completed HTTP 200 after `Processing` x4 and returned a 4,957-byte GeoJSON `FeatureCollection` with 2 Polygon features and temperatures from 36.71 to 36.7102. This satisfies the issue wording. The missing explicit unit/valid-time/data-date metadata is recorded under criterion 6 and app follow-up, not used to downgrade populated-data status.                                                                                                                                                                                                                                                                                                                                                     |
| 2. Environmental timestamps and offsets  | **Pass**                          | The documented environmental request completed HTTP 200. Metadata returned raw `2026-08-24T13:00:00-07:00`, `timezone=GMT-7`, offset `-7`, normalized UTC `2026-08-24T20:00:00Z`, interval `1h`, and count 1. Caller-supplied `temperature=35.0` means this is an analysis rather than a provider forecast, but the timestamp/offset requirement is understood and recorded.                                                                                                                                                                                                                                                                                                                                                                   |
| 3. At least five usable hotels           | **Pass**                          | A bounded rerun returned distinct OSM identities: Menger Hotel (relation `1204761`), Hilton Palacio del Rio (way `79156153`), The Emily Morgan Hotel (way `79156552`), Marriott Rivercenter (way `99940093`), Marriott Riverwalk (way `99940107`), The Crockett (way `100056533`), and Hotel Gibbs Downtown San Antonio Riverwalk (way `100361218`). Type+ID identity prevents accidental merging; names are candidate lodging identities, not availability claims.                                                                                                                                                                                                                                                                            |
| 4. Building-height corridor coverage     | **Pass, modeled source coverage** | The OSM-only sample had 1/6 explicit height-tagged ways (16.7%), but the follow-up USGS classified-lidar validation found 5 closed OSM building ways intersecting the canonical 20 m corridor and positive roof-minus-ground estimates for all 5 (`5/5 = 100%`). This exceeds the documented `>=70%` trusted coverage threshold for modeled height availability. It remains subject to 2017 source-date, footprint completeness, classification, and shadow-validation caveats; the old shortest-route fallback remains required when those confidence checks fail.                                                                                                                                                                            |
| 5. Pedestrian alternatives/full geometry | **Pass**                          | The 2026-08-23 FOSSGIS profile-specific foot request returned HTTP 200, `code=Ok`, two routes, GeoJSON LineStrings with full overview coordinates, 608.6 m/487.2 s and 625.9 m/500.8 s. The generic Project OSRM foot result remains excluded because it was byte-identical to the car response.                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 6. Operational contract                  | **Pass**                          | All named items are recorded with observed values or a defensible first-party absence: environmental metric names expose Celsius/percent/mm/octas/ppb/ppm semantics; heatmap units/valid-time fields were absent; published Basic/Pro offerings are 1M/5M monthly credits and 10/50 mi² heatmap caps; this account's tier/cost is not exposed; rate headers, latency, HTTP 401/422/200, prior timeout, completed/processing states, prior empty result, and documented environmental `null`/legacy `-999` semantics are recorded. Two identical documented historical submissions completed with byte-identical canonical results, establishing repeatability for this bounded request. No authenticated account/usage endpoint is documented. |
| 7. Final primary/fallback                | **Pass**                          | San Antonio is final primary and Austin final fallback based on the canonical hotels, populated heatmap, environmental timestamp evidence, pedestrian routing, and San Antonio scenario fit. Criterion 4's explicit insufficient-coverage result is handled by the recorded fallback policy; it does not make the city selection conditional.                                                                                                                                                                                                                                                                                                                                                                                                  |

## Canonical Scenario

The scenario is Menger Hotel to The Alamo in Downtown San Antonio / Alamo Plaza
([design source](../design/design-doc.md)). The 2026-08-23 OSRM request used
origin `-98.4861,29.4259` and destination `-98.4853,29.4225`; OSRM snapped
them to `[-98.48598,29.426406]` (57.3 m) and `[-98.48533,29.422409]` (10.5 m).
Those are response observations, not official landmark geocodes.

> **Correction, 2026-08-28 (Issue #40 research):** the request coordinates
> above do not depict the canonical journey. The recorded "origin"
> `-98.4861,29.4259` lies on the Alamo Church itself (about 20 m from its
> centroid) and the "destination" is about 366 m south of the Alamo, so the
> request walked roughly 600 m in the wrong direction; the true
> Menger-to-Alamo journey is a roughly 130-150 m northward walk. The
> authoritative coordinates for both landmarks are documented in
> [issue-40 coordinate research](issue-40-menger-alamo-coordinates.md).
> The values recorded here are preserved unmodified as historical live-call
> evidence.

## FortyGuard Evidence

### Current documented contract and source mismatch

Current first-party docs identify `POST /v1/heatmap`, `POST /v1/env_params`, and
`GET /v1/status/{activity_id}` as asynchronous endpoints, with GeoJSON polygon
AOI, `date_time`, `granularity`, and `analytic_type` fields for heatmap examples
([create heatmap](https://docs-api.fortyguard.com/docs/create-heatmap),
[environmental parameters](https://docs-api.fortyguard.com/docs/environmental-parameters),
[check status](https://docs-api.fortyguard.com/docs/check-status)). The current
first-party examples say authentication is the `api-key` header
([API introduction](https://docs-api.fortyguard.com/docs/introduction)).

The extracted application transport instead sends `X-API-Key` and its
`HeatmapRequest` emits a point/date/forecast payload
([`fortyguard-extraction.md`](../design/fortyguard-extraction.md),
[`app/fortyguard.py`](../../app/fortyguard.py)). The first continuation attempt
using the app transport received HTTP 401 and created no activity. The
successful manual call used the current documented `api-key` header and
documented polygon request shape. This discrepancy is recorded; application
code was not silently modified.

The documented request examples use `date_time.filter_type`,
`start_date`, and `start_time`; the live calls used `filter_type=1` and a
single current-hour window. The docs shell and current generated bundle expose
historical replay or idempotency procedure, but the generated heatmap schema
does document historical dates: `start_date` from `2019-01-01` through the
present is historical/real-time, while up to 12 hours ahead is forecast;
`filter_type=1` is a single hour and `granularity` accepts 60, 80, or 100.
The generated examples also document `filter_type=3` as a single day and
`filter_type=4` as a date range, with `end_date` required for type 4. The
historical experiment below therefore used the documented single-hour type 1,
the smallest allowed historical polygon, and the coarsest allowed granularity 100. No unsupported filter value was inferred. The prior environmental timeout
has no activity ID and was not resubmitted.

The pricing page lists Basic at 1,000,000 monthly credits and up to 10 mi2
heatmaps, and Pro at 5,000,000 monthly credits and up to 50 mi2; it says usage
depends on request complexity ([API pricing](https://fortyguard.com/api-pricing)).
Those published values do not identify this account's plan, cost, or payload
ceiling. The application normalizer additionally requires nonempty features,
valid geometry, Celsius `unit == "C"`, and parseable `valid_time`
([`app/fortyguard.py`](../../app/fortyguard.py)).

The current first-party pricing page also lists Basic at $79/month and Pro at
$289/month, Basic environmental parameters as up to 3 user-selected values and
Pro as full access, and describes API credits as usage currency based on request
complexity ([API pricing](https://fortyguard.com/api-pricing)). These are
published offerings, not evidence of this credential's account tier. The
current docs shell exposes no historical replay/idempotency method, null or
`-999` semantics, per-operation credit table, account/usage endpoint, or
published HTTP rate/payload header contract. No undocumented account endpoint
was guessed or called.

The generated docs bundle's quickstart-derived heatmap schema identifies the
endpoint as available to both Basic and Premium, with heatmap area caps of
10 mi² and 50 mi² respectively, and describes output as predicted or observed
temperature GeoJSON polygons plus `stats_data`. It does not expose a per-job
credit price, an account tier lookup, an idempotency key, or a historical
repeatability guarantee ([create heatmap](https://docs-api.fortyguard.com/docs/create-heatmap),
[quickstart](https://docs-api.fortyguard.com/docs/quickstart),
[check status](https://docs-api.fortyguard.com/docs/check-status)).

### Live heatmap calls, 2026-08-24

Retrieval began at `2026-08-24T00:43:11Z` (provider HTTP `Date`); the summary
was recorded at `2026-08-24T00:44:43Z`. Host was `api.fortyguard.com`; endpoint
was `POST /v1/heatmap`, followed by `GET /v1/status/{activity_id}`. The exact
sanitized request semantics were:

```json
{
  "analytic_type": "tcm",
  "date_time": {
    "filter_type": 1,
    "start_date": "2026-08-24",
    "start_time": "12:00"
  },
  "granularity": 100,
  "polygon_aoi": "closed GeoJSON FeatureCollection containing one small San Antonio Polygon around -98.4861,29.4259"
}
```

The submit response was HTTP 200, 138 bytes, 3.180 s, and returned activity ID
`42416c31-6bd3-4b64-b0dc-eac7a8ba7ccc`. Status polling was HTTP 200 on all six
checks: `Processing` x5 then `Completed`; polling response latency was 2.297,
1.353, 5.966, 1.184, 1.237, and 1.384 s, with 140 bytes for the first five
and 283 bytes for completion. Completion exposed `map_data` and `stats_data`;
`map_data` was a GeoJSON `FeatureCollection` with zero features and
`stats_data.n_cells` was zero. Therefore response mode is a completed
single-hour `tcm` request, but populated data, geometry count, observed units,
valid-time range, data date, and credits are unavailable. No credit field was
returned. The activity/request ID is safe to record; the API key is not.

Rate headers were observed: submit `x-ratelimit-limit=100`, remaining `99`;
status limit `200`, remaining `199` down to `194`; reset was the same provider
epoch on these responses. This is live header evidence, not a guaranteed
account-wide limit. The first app-transport attempt was HTTP 401 and was not
retried with that transport.

The continuation first checked the recorded activity with one safe status GET:
activity `42416c31-6bd3-4b64-b0dc-eac7a8ba7ccc` remained `Completed` with the
same empty result. No activity identifier was recorded for the prior timed-out
environmental POST, so no equivalent lookup was possible without guessing an
identifier.

The one new billable heatmap semantics used a distinct current-hour window:

```json
{
  "analytic_type": "tcm",
  "date_time": {
    "filter_type": 1,
    "start_date": "2026-08-24",
    "start_time": "13:00"
  },
  "granularity": 100,
  "polygon_aoi": "closed FeatureCollection with one Polygon: lon -98.4870 to -98.4852, lat 29.4235 to 29.4250"
}
```

Two locally malformed validation submissions produced HTTP 422 with no
activity; the second response said `polygon_aoi` must be a dictionary. The
corrected submission began at `2026-08-24T11:23:58Z` by local clock, returned
HTTP 200 in 3 s, 138 bytes, and activity
`f7413530-41e1-47df-b701-892545006d89`. Polls returned HTTP 200 with
`Processing` x4 and `Completed` on poll 5. Poll timestamps were
`11:25:58`, `11:26:24`, `11:26:46`, `11:27:08`, and `11:27:32Z`; elapsed
poll time was 98 s. Response sizes were 140 bytes while processing and 4,957
bytes at completion. The result contained 2 Polygon features and temperature
properties from 36.71 to 36.7102; `temperature_stats` reported minimum 36.71,
maximum 36.7102, and mean 36.7101. No explicit unit, valid-time/data-date,
provider metadata, `n_cells`, or credit field was returned. A safe terminal
lookup at 11:33:46Z returned HTTP 200 in 3.654 s with the same shape.

The request JSON above is sanitized input, not the returned data. The relevant
sanitized response shape was:

```json
{
  "map_data": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": { "type": "Polygon" },
        "properties": { "temperature": 36.71 }
      },
      {
        "type": "Feature",
        "geometry": { "type": "Polygon" },
        "properties": { "temperature": 36.7102 }
      }
    ]
  },
  "temperature_stats": { "min": 36.71, "max": 36.7102, "mean": 36.7101 }
}
```

Coordinates and volatile identifiers are omitted, but the two temperatures and
statistics are the observed values. The live response did not include a Celsius
unit label or a valid-time/data-date field, so those fields must not be inferred
from the request date.

Submit rate headers were `limit=100`, `remaining=97`; status polling exposed
`limit=200`, remaining 199, 198, 199, 198, 199; the terminal lookup exposed
remaining 199. Reset epochs changed with the provider window. These are live
observations, not an account-wide contract. The populated result is evidence
that this endpoint was recovered on 2026-08-24, but not evidence of Celsius
units or a complete app-normalizable record.

### Historical repeatability experiment, 2026-08-24

The two authorized submissions used exactly the same sanitized payload:

```json
{
  "analytic_type": "tcm",
  "date_time": {
    "filter_type": 1,
    "start_date": "2024-07-15",
    "start_time": "14:00"
  },
  "granularity": 100,
  "polygon_aoi": "the same small closed San Antonio Polygon used by the prior populated request"
}
```

This is a documented historical single-hour request: the generated official
schema says dates from `2019-01-01` through the present are historical/
real-time, `filter_type=1` is a single hour, and 100 is an allowed granularity.
The two submissions were intentionally identical and used the coarsest
documented granularity; no request was retried after a timeout.

Submission 1 returned HTTP 200 in 3 s, 138 bytes, with activity
`ce96ae0e-60b5-4614-90fe-b1833fa791e5`; submission 2 returned HTTP 200 in 2 s,
138 bytes, with activity `f67a5906-32b5-42e8-aab1-462d140acc25`. Submit rate
headers were `limit=100`, remaining 99 then 98. Activity 1 returned
`Processing` x16 then `Completed` on poll 17, with approximately 201 s from
first poll to completion and a 4,945-byte terminal response. Activity 2 returned
`Processing` x2 then `Completed` on poll 3, with approximately 31 s from first
poll to completion and the same 4,945-byte terminal response. Status responses
were HTTP 200 throughout; status rate limits were 200 with observed remaining
values 199 through 194, then 199 through 196/195 over the two jobs. No credit
field appeared.

After removing activity/request IDs and transport metadata, canonical result
SHA-256 was identical for both submissions:
`885730cca0c74cad3a6fc23bc2f09e1cc038d2815caf4913f125e44f892946a7`. Each
result was a GeoJSON `FeatureCollection` with 2 Polygon features. Average,
minimum, and maximum temperature values ranged from 36.11 to 36.1105; the
statistics were minimum 36.11, maximum 36.1105, mean 36.11025, and standard
deviation 0.0003535533905949619. The canonical JSON was byte-identical, so
this bounded historical request is repeatable in this experiment. This does
not prove all dates or payloads are repeatable.

### Live environmental calls, 2026-08-24

The one direct documented request was `POST /v1/env_params` with this sanitized
body:

```json
{
  "latitude": 29.4259,
  "longitude": -98.4861,
  "temperature": 35.0,
  "date_time": {
    "filter_type": 1,
    "start_date": "2026-08-24",
    "start_time": "12:00"
  }
}
```

The prior client timeout remains unresolved: it produced no activity ID, so it
was not retried or guessed at. One new documented request began at
`2026-08-24T11:28:01Z` by local clock and used the same sanitized body with
`start_time=13:00`. It returned HTTP 200 in 2 s, 162 bytes, and activity
`0b592283-ef6f-4783-bacb-79ea59e7254a`; its first status GET returned HTTP 200
and `Completed` in about 2 s, 1,204 bytes.

The result metadata supplied raw timestamp
`2026-08-24T13:00:00-07:00`, `timezone=GMT-7`, offset `-7`, normalized UTC
`2026-08-24T20:00:00Z`, interval `1h`, and count 1. The location returned
latitude 29.4259, longitude -98.4861, elevation 207 m, and temperature 35.0.
Parameter names included `heat_index_celsius`,
`apparent_temperature_celsius`, `relative_humidity_percent`,
`precipitation_mm`, `cloud_cover_octas`, `wet_bulb_temperature_celsius`, and
air-quality/greenhouse-gas metrics. Their single values were respectively 33.2
C, 40.5 C, 21.5%, 0.0 mm, 8.0 octas, and 22.3 C; clear-sky GHI/DNI/DHI were
860.41/797.36/149.46 (the response did not state an irradiance unit). Values
were arrays, and no null or `-999` value was observed. This is a provider
environmental analysis conditioned on the caller's 35.0 C temperature, not a
provider temperature forecast. The app adapter still requires a
caller-supplied Celsius anchor, rejects
`is_real_forecast=True`, and labels its series `caller-supplied temperature
anchor; not a real 24-hour forecast` ([`app/fortyguard.py`](../../app/fortyguard.py)).

The request JSON above is also sanitized input. The relevant sanitized response
shape was:

```json
{
  "timestamp": "2026-08-24T13:00:00-07:00",
  "timezone": "GMT-7",
  "offset": -7,
  "interval": "1h",
  "count": 1,
  "heat_index_celsius": [33.2],
  "apparent_temperature_celsius": [40.5],
  "relative_humidity_percent": [21.5],
  "precipitation_mm": [0.0],
  "cloud_cover_octas": [8.0],
  "wet_bulb_temperature_celsius": [22.3]
}
```

The full response also named additional air-quality, greenhouse-gas, and solar
metrics. Their values are summarized above rather than copied wholesale. The
`temperature: 35.0` request field is the caller anchor that conditions this
analysis; it is not a returned observation.

The repository contract requires environmental rows to preserve raw timestamp
strings and offsets, timezone identifier, normalized UTC instant, metric values
and units, and distinguish `null` from `-999` ([`proposal-fact-check.md`](proposal-fact-check.md)).
Those remain capture requirements, not live evidence. Do not classify `tcm` as
NOAA Heat Index; use `heat_index_celsius` only when actually returned.

### Operational limits and remaining work

The continuation used the recorded-activity lookup, five heatmap POSTs (two
HTTP 422 validation responses with no activity and one submission), five status
polls, one heatmap terminal shape lookup, two historical heatmap submissions,
twenty historical status polls, one environmental POST, one
environmental status poll, two safe terminal shape lookups, one preserved-route
OSRM GET, one successful bounded hotel rerun, and four bounded Overpass attempts (two malformed local query
serializations returning HTTP 400, one successful geometry query, then one
documented all-element route-corridor query returning HTTP 504). Along with the
earlier 10-call ledger, this is **51 live provider/routing/OSM HTTP calls in the full
continuation record; four new submitted FortyGuard activities; credits
reported: 0 / unknown because no response exposed a credit field**. The only
repeat identical billable activity was the explicitly authorized two-submission
historical experiment above. No ambiguous-timeout resubmission, payload-limit
probe, deliberate billable error, or unsafe large request was made.

Historical repeatability is **Observed for one bounded documented request**:
two identical submissions completed with identical canonical hashes, feature
counts, geometries, value ranges, and statistics. Activity completion latency
varied substantially (approximately 201 s versus 31 s), so repeatability of
content does not imply latency repeatability. Actual plan tier is **Unknown**;
published Basic and Pro offerings are recorded separately above.
Rate-limit header behavior is **observed on live responses but not published as
an account contract** from successful
heatmap/status/env calls. Payload limits are **Unknown**. New heatmap latency
was 3 s submit and 98 s to completion; environmental latency was 2 s submit
and about 2 s to completion. Error behavior includes HTTP 401, two HTTP 422
validation responses, and the prior client timeout; no deliberate billable
error was triggered. Empty provider data is preserved as the prior empty
feature collection; environmental `null`/legacy `-999` behavior was not
naturally observed in the live result, but is documented by the current
first-party generated response schema as `null` for newly missing upstream
values and legacy `-999` for older stored responses.

### Account-level credit usage, 2026-08-25

The salvaged quickstart utility now exposes the documented
`POST /v1/system/fetch-api-key-custom-usage` call as
`scripts/fortyguard_usage.py`. A live run over `2026-07-26` through
`2026-08-25` returned `total_credits_used=108660` and this activity breakdown:

| Activity                       | Credits | Calls |
| ------------------------------ | ------: | ----: |
| Tile Satellite Segmentation    |  57,600 |     4 |
| Heatmap Generation             |  33,760 |     8 |
| Environment Parameter Analysis |   8,700 |     3 |
| Streetview Segmentation        |   8,600 |     1 |

This is account-level evidence for the selected window, not per-activity
attribution for Issue #7. The response does not expose the account's named plan
tier. The key is supplied in-process and is not printed or persisted by the
utility.

## Overpass And OSM

The first-party [Overpass API documentation](https://wiki.openstreetmap.org/wiki/Overpass_API)
describes a read-only selected-OSM-data API, shared public-server behavior,
identification via `User-Agent`/`Referer`, and a 30-second pause after HTTP 429.
OSM defines `tourism=hotel` as a paid-lodging tag that may be a node, way, or
relation ([hotel tag](https://wiki.openstreetmap.org/wiki/Tag:tourism%3Dhotel)).
`height` is normally metres and `building:levels` counts above-ground non-roof
levels ([height](https://wiki.openstreetmap.org/wiki/Key:height),
[building levels](https://wiki.openstreetmap.org/wiki/Key:building:levels)).

The preserved 2026-08-23 San Antonio hotel query was:

```overpass
[out:json][timeout:60];
nwr["tourism"="hotel"](29.421,-98.490,29.429,-98.482);
out center tags;
```

It returned HTTP 200, 26 objects (24 ways, 2 relations), 14,535 bytes, and
11.184 s, with OSM base timestamp `2026-08-23T20:20:36Z`; Menger Hotel was
relation `1204761`. Austin returned 28 objects (4 nodes, 22 ways, 2 relations),
HTTP 200, 17,191 bytes, 9.659 s. These results preserve conservative
deduplication: use type+ID and metadata/relation membership before proximity;
nearby hotel objects are not automatically duplicates. They establish
candidate discovery, not availability.

The preserved San Antonio bbox proxy returned 45 building ways, 0 `height`, and
1 `building:levels` (2.2%); Austin returned 72, 4, and 17 respectively (at
most 29.2% before overlap removal). The policy is >=70% trusted, 30% to <70%
weak and shortest-route fallback, <30% insufficient. This reconciles the
threshold with the evidence but does not upgrade a bbox proxy to final
route-buffer coverage. Building parts, relations, invalid values, and duplicate
parent/part features still require a bounded geometry query before a final
route-specific percentage can be claimed. Earlier public-server 504/500
observations remain reasons to cache and avoid CI dependency.

### Live route-buffer geometry, 2026-08-24

The preserved FOSSGIS primary route was re-fetched first: HTTP 200, `code=Ok`,
2,830 bytes, two full GeoJSON LineStrings, 47 primary-route coordinates, and
the same 608.6 m / 487.2 s shortest route. One bounded Overpass request then
used `[out:json][timeout:120]`, a descriptive `User-Agent`, and one `way`
`building` query for each of those coordinates with `around:20`, followed by
`out tags geom;`. The query returned HTTP 200 in 3 s and 9,511 bytes. It
contained 6 unique closed building ways, all intersecting the 20 m corridor;
there were 0 `height` values and 1 `building:levels` value. The query was
bounded to the primary route and did not request relations or building parts,
so it cannot overstate coverage by merging uncertain parent/part records.

For the six unique closed way geometries, explicit positive numeric `height`
or positive integer `building:levels` was required. The only qualifying
feature had `building:levels=2`; invalid, absent, fractional, duplicate, and
non-closed geometries were excluded. The projected 20 m corridor area was
approximately 24,789 m2, and conservative valid-height coverage was `1/6 =
16.7%`, below the project's `<30%` insufficient threshold. This upgrades the
old bbox proxy to a route-specific measurement but does not upgrade the result
to trusted modeled shade. Two locally malformed coordinate serializations
returned Overpass HTTP 400 and were not provider/data probes; the corrected
single request is the sole geometry result used above.

A final documented all-element query used the full LineString coordinate list
directly in `nwr["building"](around:20,...)` and
`nwr["building:part"](around:20,...)`; it returned HTTP 504 after 11 s, 695
bytes. Therefore relations/parts could not be safely incorporated. The
successful six-way result remains a conservative lower-information corridor
sample, not a claim that no building parts or relations exist.

### Building-footprint LiDAR validation, 2026-08-25

The follow-up prototype used the canonical OpenStreetMap bounded map endpoint
(`https://api.openstreetmap.org/api/0.6/map?bbox=-98.4872,29.4215,-98.4842,29.4269`)
to obtain the local XML extract, then intersected closed `building` ways with
the same 20 m projected corridor around the full 47-coordinate primary OSRM
walking route. Five OSM footprints intersected the corridor. For each
footprint, the prototype read the USGS B2 LAZ tile in its
native projected/vertical reference (`NAD83(2011) / UTM zone 14N + NAVD88 height

- Geoid12B`, represented by EPSG:6343), selected class 2 ground returns and
  class 6 building returns, and compared their median elevations. All five
  footprints had both ground and class 6 returns:

|                          OSM way |        Area | Ground returns | Roof returns | Estimated height |
| -------------------------------: | ----------: | -------------: | -----------: | ---------------: |
|   68792761 (The Alamo Gift Shop) |    435.7 m2 |             50 |        2,283 |           7.54 m |
|          92060042 (Alamo Church) |    541.0 m2 |            108 |        2,621 |           7.55 m |
|                         99942673 | 20,861.6 m2 |          3,158 |      128,615 |          17.91 m |
| 360103246 (multi-storey parking) |  3,734.1 m2 |             39 |       19,805 |          18.95 m |
|                       1368841986 |    324.6 m2 |             38 |        1,601 |           4.89 m |

This gives `5/5 = 100%` modeled height availability for the bounded OSM
footprint sample, above the project's `>=70%` trusted coverage threshold. The
result is stronger than the earlier OSM-tag-only `1/6 = 16.7%` result, but it
does not prove complete building-footprint coverage, currentness relative to
2026, or correctness of every roof classification. The derived estimates are
therefore suitable to proceed to a bounded solar-shadow prototype with
provenance and fallback, not to claim observed shade without further visual
validation.

## OSRM

The official [OSRM HTTP API](https://project-osrm.org/docs/v5.24.0/api/) defines
`/route/v1/{profile}/{coordinates}`, `alternatives`, `geometries=geojson`, and
`overview=full`; distance is metres, duration seconds, alternatives are not
guaranteed, and errors include HTTP 400 `NoRoute`, `InvalidQuery`, and `TooBig`.
The official [foot profile](https://raw.githubusercontent.com/Project-OSRM/osrm-backend/master/profiles/foot.lua)
defines pedestrian access and walking speed but no heat/shade model.

The preserved 2026-08-23 request was:

```text
https://routing.openstreetmap.de/routed-foot/route/v1/foot/-98.4861,29.4259;-98.4853,29.4225?alternatives=3&geometries=geojson&overview=full&steps=false
```

It returned HTTP 200, `code=Ok`, 0.436 s, 2,830 bytes, two full GeoJSON
LineStrings, distances 608.6 m and 625.9 m, and durations 487.2 s and 500.8 s.
FOSSGIS documents its profile-specific paths on its [about page](https://routing.openstreetmap.de/about.html)
and [frontend source](https://github.com/fossgis-routing-server/osrm-frontend/blob/master/src/leaflet_options.js).
The same-coordinate car control returned one route, HTTP 200, 0.218 s, 2,398
bytes. The earlier generic-host foot response was byte-identical to car and is
not pedestrian evidence.

## Shade Coverage Recommendation

The original 16.7% result was an OSM-tag coverage failure, not a consequence of
checking at midday. Time of day changes solar azimuth and shadow length; it does
not add `height` or `building:levels` tags to OSM buildings. A noon request can
therefore be useful for a shorter-shadow stress case, but it cannot explain the
absence of usable height metadata. The follow-up LiDAR validation shows that
external surface data can supply modeled heights even when OSM tags are sparse.

Keep the shade feature, but make its confidence explicit:

1. Keep route geometry and heat data as the base result for every route.
2. Acquire building ways, `building:part` ways, and relations in bounded route
   buffers. Deduplicate parent/part geometry and accept explicit positive
   `height` first, then valid integer `building:levels` as an approximation.
3. Compute solar position and projected shadows for the requested local time,
   not only at noon. Evaluate the route at the requested time and at a small
   set of nearby times when the itinerary is flexible.
4. Require the documented 70% coverage policy for a trusted modeled shade
   ranking. Below 30%, retain the shade estimate only as unavailable/low
   confidence and recommend the shortest returned route. Between 30% and 70%,
   show the result with weak-coverage wording rather than presenting a winner as
   measured fact.
5. Treat USGS classified-lidar-derived heights as modeled enrichment, not
   observed building heights. Retain acquisition date, class selection,
   vertical reference, footprint source, and estimation method. Do not silently
   turn missing OSM heights into measured shadow.

This preserves shade as a feature without allowing sparse building metadata to
create false precision. The current San Antonio corridor can proceed to a
solar-shadow prototype using the bounded LiDAR-derived geometry, while retaining
the shortest-route fallback whenever source-date, footprint, classification, or
shadow-validation confidence is insufficient.

## Final Locks And Blockers

1. Lock San Antonio as final primary and Austin as final fallback for Issue #7.
2. Permit a bounded modeled-shade prototype using USGS classified lidar plus
   OSM footprints, but recommend the shortest returned route whenever sampled
   coverage or validation confidence is insufficient.
3. Do not acquire or commit live San Antonio FortyGuard fixtures until the
   populated heatmap's unit/valid-time contract and the environmental
   caller-anchor/forecast contract are reconciled with the app adapter.
4. Resolve the transport/payload mismatch explicitly in a future application
   change or documented adapter boundary: current first-party examples use
   `api-key` and polygon/date-time payloads, while the app uses `X-API-Key` and
   its simplified request model.
5. Criterion 4 is satisfied for modeled height availability by the follow-up
   `5/5 = 100%` LiDAR-derived estimate result, but the solar-shadow prototype
   still needs footprint, date, classification, and visual validation. Remaining
   provider/app follow-ups are no explicit heatmap unit or valid-time/data-date
   field; environmental data is a caller-supplied-temperature analysis rather
   than a real provider forecast; no natural null/`-999` observation; exact
   account tier/cost; and no idempotency guarantee beyond the one observed
   bounded historical comparison. These do not prevent the city-selection lock.

## Issue Closure Assessment

Against the exact Issue #7 acceptance wording: criteria 1 through 7 are **Pass**
for the documented validation scope. Criterion 4 passes on modeled source
coverage: the OSM-only result was 16.7%, but the follow-up USGS classified-lidar
screen found positive estimates for all five OSM footprints intersecting the
canonical 20 m corridor (`5/5 = 100%`). This closes the acceptance criterion,
but does not eliminate the separate engineering work required to validate and
ship solar-shadow geometry. The provider/app contract caveats remain recorded
and are not misclassified as failures of criteria 1 or 2.

## Verification Performed

- Read Issues #6 and #7 directly; confirmed Issue #6 is closed and its
  extracted client exists in `app/fortyguard.py`.
- Re-read the existing report, extraction design, fixtures, tests, and project
  guidance without printing `.env` contents.
- Consulted current first-party FortyGuard introduction, heatmap,
  environmental-parameters, status, and pricing pages; inspected the current
  docs shell and generated bundle. Pricing/FAQ evidence records published plan
  tiers, credits, area caps, environmental feature tiers, and complexity-based
  credit usage; no documented account endpoint, historical replay contract,
  null/`-999` semantics, or published rate/payload contract was found.
- Made the documented continuation calls on 2026-08-24, preserving only
  sanitized request semantics, statuses, activity/status transitions, response
  shape, timing, sizes, and rate headers. The new heatmap and environmental
  activities completed; no credit field or account tier was exposed. Inspected
  the generated official docs bundle to establish the historical heatmap
  contract, then made exactly two identical bounded historical submissions and
  polled both to completion. Their canonical results were byte-identical.
- Preserved and rechecked the 2026-08-23 bounded Overpass hotel/building and
  FOSSGIS foot-routing evidence, including conservative deduplication,
  threshold/fallback, profile-specific, and full-geometry conclusions. Added
  one successful bounded hotel rerun with seven explicit distinct identities,
  one bounded 20 m route-buffer geometry query, and calculated 16.7%
  conservative valid-height coverage; recorded the comparable all-element
  corridor query's HTTP 504.
- Reviewed this artifact line-by-line against all seven acceptance criteria;
  each result is marked Pass or Fail using the issue's literal wording, with
  app/provider follow-up separated from issue acceptance. Criterion 6 now has
  observed repeatability evidence rather than treating an unknown as fulfilled.
