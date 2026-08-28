# Issue #40: Correct Canonical Menger Hotel To The Alamo Coordinates

**Research date:** 2026-08-28

**Issue:** [Correct canonical Menger Hotel to The Alamo coordinates](https://github.com/alshawai/heat-aware-tourism-guide/issues/40)

## Executive Summary

The canonical ordering is unambiguous in every repository source of truth:
origin is Menger Hotel, destination is The Alamo
([design-doc.md:55-58](../design/design-doc.md),
[CONTEXT.md:15-17](../../CONTEXT.md), and Issues #15/#40 themselves).

None of the three coordinate pairs currently associated with the journey
represents that journey:

1. The committed fixture identity
   (origin `29.421, -98.491`, destination `29.425, -98.484` in
   [`fixtures/trip-analysis.json`](../../fixtures/trip-analysis.json) and its
   sidecar) is roughly 596 m and 708 m away from the Menger Hotel and Alamo
   Church centroids respectively for its origin, and roughly 219 m and 240 m
   away for its destination (all distances computed from observed coordinates,
   see below). It matches neither landmark.
2. The 2026-08-23 OSRM request recorded in the Issue #7 research
   (`origin -98.4861,29.4259`, `destination -98.4853,29.4225`) is worse than
   imprecise: its **origin sits on the Alamo Church itself** (computed 20 m
   from the OSM church centroid, inside the observed church footprint) and its
   destination is roughly 366 m south of the Alamo. It is a southward
   roughly 600 m walk, while the canonical journey is a roughly 130 m
   northward walk. Those snapped values remain response observations, not
   official landmark geocodes, exactly as the Issue #7 note already states.
3. `docs/design/point-vs-area-heatmap.md:78` labels the point
   `(29.4259, -98.4861)` as "The Alamo", while the same document's route
   example (line 86) uses that same point as the Menger-side start of a
   "Menger Hotel to Alamo Plaza" polyline. The point cannot be both; it is at
   the Alamo Church, not the Menger. This is the "order that conflicts with
   the journey wording" the issue describes.

Recommended canonical values (full evidence below):

- **Origin, Menger Hotel:** `29.4245914, -98.4864288` — OpenStreetMap
  relation 1204761 centroid as served by Nominatim. Crowd-sourced, WGS84,
  building-specific, and the only fully specified value reachable
  non-interactively. Cross-checked by Wikipedia (15 m away) and the official
  Texas Historical Commission marker record (UTM; see datum caveat).
- **Destination, The Alamo:** `N 29°25'33" W 98°29'9"`
  (decimal `29.425833, -98.485833`) — the State Party nomination for the
  UNESCO World Heritage inscription of the San Antonio Missions, component 006
  "Mission Valero / The Alamo", "coordinates of the central point". This is
  the strongest owner-side published coordinate for the landmark. A
  building-specific crowd-sourced alternative (OSM Alamo Church way 92060042
  centroid, `29.4257216, -98.4860990`) sits 29 m away.

The true Menger-to-Alamo walk is roughly 130-150 m (computed), versus the
synthesized fixture routes of 1000 m / 1200 m and the recorded 608.6 m OSRM
route. The committed fixture identity origin (`29.421`) and the recorded OSRM
destination (`29.4225`) both lie south of the provider-grid latitude bound
`29.42366°N` documented in
[point-vs-area-heatmap.md:110](../design/point-vs-area-heatmap.md), so
correcting the identity also moves the scenario inside the observed
FortyGuard downtown grid.

## Ordering Confirmation

Repository primary sources, quoted exactly:

- `docs/design/design-doc.md:55-58`:
  "The canonical scenario is: ... - Origin: Menger Hotel. - Destination: The
  Alamo."
- `docs/design/design-doc.md:303`: "- One complete Menger Hotel to The Alamo
  scenario."
- `CONTEXT.md:15-17`: "**Canonical trip** — The validated demonstration
  journey from Menger Hotel to The Alamo, with hotel decisions scoped to
  Downtown San Antonio / Alamo Plaza."
- Issue #15 ("Implement curated trip setup flow", closed): "**Canonical
  trip:** Menger Hotel to The Alamo..." and "It displays these read-only
  curated values: - Origin: Menger Hotel. - Destination: The Alamo."
- Issue #40 itself: "Canonical scenario coordinates use Menger Hotel as origin
  and The Alamo as destination."

No repository source states the reverse ordering. The frontend already
displays the ordering correctly
([TripSetupScreen.tsx:127-140](../../frontend/src/screens/TripSetupScreen.tsx));
only the hidden request coordinates are wrong.

## Authoritative Coordinate Evidence

All web sources below were retrieved on 2026-08-28. "Computed" decimal
conversions are arithmetic from published DMS or UTM values, performed with
pyproj/hand calculation and labeled as computed; the DMS/UTM strings are what
the sources actually published.

### Menger Hotel (204 Alamo Plaza, San Antonio, TX 78205)

| Source                                                                                                                                                                | Published value                                                                                    | What the point represents                                                                                                                                                                                                                        | Datum                                                                                                                                                           | Class                           |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| Texas Historical Commission Historic Sites Atlas, RTHL record 3334, Atlas Number 5029003334 ([record](https://atlas.thc.state.tx.us/Details/5029003334))              | UTM Zone 14, Easting 549827, Northing 3255200                                                      | Recorded Texas Historic Landmark marker location for "Menger Hotel", address 204 Alamo Plaza, marker year 1965                                                                                                                                   | Not stated on the record page. Computed conversions: NAD83/WGS84 (EPSG:26914/32614) gives 29.425152, -98.486316; NAD27 (EPSG:26714) gives 29.426989, -98.486642 | Official state record           |
| OpenStreetMap relation 1204761 via Nominatim ([query](https://nominatim.openstreetmap.org/search?q=Menger+Hotel,+San+Antonio,+TX&format=json&limit=5))                | lat 29.4245914, lon -98.4864288; bounding box 29.4242103 to 29.4250438, -98.4866063 to -98.4854479 | Nominatim centroid of the hotel multipolygon (tags: name=Menger Hotel, tourism=hotel, addr 204 Alamo Plaza; members: outer way 80186437, inner ways 80187316/80187317 per the [OSM API](https://api.openstreetmap.org/api/0.6/relation/1204761)) | WGS84 (OSM stores lat/lon in the standard WGS84 projection per the [OSM wiki Node page](https://wiki.openstreetmap.org/wiki/Node))                              | Crowd-sourced observation       |
| English Wikipedia article "Menger Hotel" infobox ([parse API](https://en.wikipedia.org/w/api.php?action=parse&page=Menger_Hotel&prop=wikitext&format=json&section=0)) | 29°25'29"N 98°29'11"W (computed decimal 29.424722, -98.486389)                                     | Infobox coordinates of the hotel                                                                                                                                                                                                                 | Not stated; assumed WGS84                                                                                                                                       | Crowd-sourced                   |
| Wikidata Q6816982 ([entity data](https://www.wikidata.org/wiki/Special:EntityData/Q6816982.json))                                                                     | P625: 29.42467, -98.485986                                                                         | Item coordinate location                                                                                                                                                                                                                         | Not stated                                                                                                                                                      | Crowd-sourced                   |
| mengerhotel.com ([official site](https://www.mengerhotel.com/))                                                                                                       | Address only: "204 Alamo Plaza, San Antonio, TX 78205"                                             | No coordinates published                                                                                                                                                                                                                         | n/a                                                                                                                                                             | Owner's official site           |
| Historic Hotels of America ([property page](https://historichotels.org/hotels-resorts/the-menger-hotel/))                                                             | Address only; the schema.org `geo` fields are empty strings                                        | No coordinates published                                                                                                                                                                                                                         | n/a                                                                                                                                                             | Program site                    |
| USGS GNIS feature ID 6478249 (identified via Wikidata P1566)                                                                                                          | Not retrieved                                                                                      | Unknown                                                                                                                                                                                                                                          | n/a                                                                                                                                                             | Federal; unreachable, see below |

Disagreements worth noting: the Wikidata P625 longitude (-98.485986) is about
43 m east of the Wikipedia infobox longitude (-98.486389); the OSM relation
centroid lies between them. The THC UTM, converted under the NAD83/WGS84
assumption, lands roughly 63 m north of the OSM centroid and about 12 m north
of the observed hotel footprint's north edge (29.4250438), consistent with a
sidewalk marker position rather than a building centroid; under NAD27 it lands
267 m north in Alamo Plaza. The record page does not state its datum, so both
conversions are reported and neither is silently preferred.

### The Alamo / Alamo Church (300 Alamo Plaza, San Antonio, TX 78205)

| Source                                                                                                                                                                                                           | Published value                                                                                                                                                                                                                                                                                                                          | What the point represents                                                                                                                                            | Datum                                                          | Class                                                        |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------ |
| UNESCO World Heritage nomination "San Antonio Missions" (State Party: United States; [nomination file](https://whc.unesco.org/uploads/nominations/1466.pdf), 176,418,411 bytes, retrieved in full)               | Section 1.d, component 006 "Mission Valero", region San Antonio: "W 98° 29' 9" N 29° 25' 33"" (computed decimal 29.425833, -98.485833); component area 1.7 ha                                                                                                                                                                            | "Coordinates of the central point" of the Mission Valero / The Alamo World Heritage component (the Alamo Complex, owned by the State of Texas per the same document) | Not stated in the extracted text; assumed WGS84 for comparison | Official State Party nomination to the World Heritage Centre |
| UNESCO World Heritage List entry 1466 ([property page](https://whc.unesco.org/en/list/1466))                                                                                                                     | No per-component coordinates on the page; confirms "The State of Texas owns the property of Mission Valero/The Alamo" and that Mission Valero is a National Historic Landmark                                                                                                                                                            | n/a                                                                                                                                                                  | n/a                                                            | Official                                                     |
| OpenStreetMap way 92060042 "Alamo Church" via Nominatim ([query](https://nominatim.openstreetmap.org/search?q=Alamo+Church,+San+Antonio,+TX&format=json&limit=3))                                                | lat 29.4257216, lon -98.4860990; bounding box 29.4256086 to 29.4258354, -98.4862816 to -98.4859298                                                                                                                                                                                                                                       | Nominatim centroid of the church building way (tags: building=church, building:levels=2, name=Alamo Church)                                                          | WGS84 (as above)                                               | Crowd-sourced observation                                    |
| OSM way 92060042 full node geometry ([OSM API](https://api.openstreetmap.org/api/0.6/way/92060042/full))                                                                                                         | Nodes span lat 29.4256086 to 29.4258354, lon -98.4862816 to -98.4859298; node 12223944668 (tag entrance=main) at lat 29.4257225, lon -98.4862666                                                                                                                                                                                         | Church footprint outline and main entrance                                                                                                                           | WGS84                                                          | Crowd-sourced observation                                    |
| English Wikipedia article "Alamo Mission" infobox ([parse API](https://en.wikipedia.org/w/api.php?action=parse&page=Alamo_Mission&prop=wikitext&format=json&section=0))                                          | 29°25'33"N 98°29'10"W (computed decimal 29.425833, -98.486111)                                                                                                                                                                                                                                                                           | Infobox coordinates; also records NRHP reference 66000808, NHL designation 1960-12-19, NRHP listing 1966-10-15, owner Texas General Land Office                      | Not stated; assumed WGS84                                      | Crowd-sourced                                                |
| NPS NPGallery NRHP record 66000808 "Alamo, The" ([asset detail](https://npgallery.nps.gov/AssetDetail/NRIS/66000808); [nomination PDF](https://npgallery.nps.gov/GetAsset/6ba0f2b3-fac3-4a4e-8714-513e43431ab4)) | No coordinates in the metadata. The 1966 nomination form's "UTM REFERENCES" field is illegible in OCR. Verbal boundary: "The Alamo and its grounds are contained within one block bounded on the north by Houston Street, on the east by Nacogdoches Street, on the south by East Crocket Street and on the west by North Alamo Street." | NRHP/NHL documentation                                                                                                                                               | n/a                                                            | Official federal record                                      |
| THC Atlas State Antiquities Landmark record 8200001755 "Alamo, The (41BX6)" ([record](https://atlas.thc.state.tx.us/Details/8200001755))                                                                         | No coordinates; owner "Texas General Land Office"                                                                                                                                                                                                                                                                                        | n/a                                                                                                                                                                  | n/a                                                            | Official state record                                        |
| thealamo.org ([official site](https://www.thealamo.org/))                                                                                                                                                        | Address only: "300 Alamo Plaza, San Antonio, TX 78205"; "The Alamo is the property of the State of Texas, and operated by Alamo Trust, Inc."                                                                                                                                                                                             | No coordinates published                                                                                                                                             | n/a                                                            | Operator's official site                                     |
| The Cenotaph, Alamo Plaza (same Nominatim query as above)                                                                                                                                                        | lat 29.4261578, lon -98.4866962                                                                                                                                                                                                                                                                                                          | Nearby monument, useful as context: it lies north of the church, showing the plaza's northern extent                                                                 | WGS84                                                          | Crowd-sourced observation                                    |

Cross-check: the UNESCO central point is 29 m from the OSM Alamo Church
centroid (computed) and sits just northeast of the observed church footprint,
inside the Alamo Complex grounds, which is what a 1.7 ha component centroid
should do. The Wikipedia infobox value is 12 m from the OSM church centroid.
These independent values agree to well under the fixture's needed precision.

### Unreachable or failed sources (recorded honestly)

- USGS GNIS (geonames.usgs.gov): the Apex detail URL for feature 6478249
  redirects to the Board on Geographic Names homepage for non-interactive
  clients (tested with and without a cookie session), and the documented
  state-file download endpoints returned HTTP 403. The Menger Hotel GNIS
  feature ID (6478249) is recorded for a future interactive retrieval.
- Texas General Land Office: `https://www.glo.texas.gov/history/archives/alamo/index.html`
  returned HTTP 404; no other GLO page with Alamo coordinates was located
  without a working search engine (DuckDuckGo HTML returned a bot challenge).
- NPGallery NRHP search: the search endpoint ignored query parameters and
  returned the unfiltered first page for every attempt; asset-detail deep
  links by NRIS ID do work (used above). One candidate NRIS ID fetched for
  verification (66000818) resolved to "Lucas Gusher, Spindletop Oil Field" and
  was discarded, which is why NRIS IDs used here were verified against the
  returned record titles.
- The NPGallery copy of the Alamo Plaza Historic District (77001425) nomination
  is a one-page placeholder reading "The PDF file for this National Register
  record has not yet been digitized." The THC-hosted copy
  (`https://atlas.thc.texas.gov/NR/pdfs/77001425/77001425.pdf`,
  153,550,332 bytes) throttled every download attempt; roughly 11 MB was
  retrieved across resumed attempts and text extraction failed on the partial
  file. This district nomination (which contains the Menger Hotel as a
  contributing property) remains unexamined.
- City of San Antonio / Bexar County open GIS address data: not reachable
  without a working general web search in this session.

## What The Committed Values Actually Represent

Distances below are computed (haversine) from the observed coordinates cited
above; they are my calculations, not published values.

| Point                                          | To OSM Menger centroid | To OSM Alamo Church centroid |
| ---------------------------------------------- | ---------------------: | ---------------------------: |
| Fixture identity origin `29.421, -98.491`      |                  596 m |                        708 m |
| Fixture identity destination `29.425, -98.484` |                  240 m |                        219 m |
| Issue-7 OSRM origin `29.4259, -98.4861`        |                  149 m |                         20 m |
| Issue-7 OSRM destination `29.4225, -98.4853`   |                  257 m |                        366 m |
| UNESCO Alamo central point                     |                  150 m |                         29 m |
| Wikipedia Menger infobox                       |                   15 m |                          n/a |
| Wikipedia Alamo infobox                        |                    n/a |                         12 m |
| THC Menger UTM (NAD83/WGS84 conversion)        |                   63 m |                          n/a |
| THC Menger UTM (NAD27 conversion)              |                  267 m |                          n/a |

Additional computed facts:

- True canonical journey length, OSM Menger centroid to OSM Alamo Church
  centroid: 130 m; to the UNESCO central point: 150 m. The journey is
  northward (the hotel is south-southwest of the church).
- Fixture identity origin-to-destination straight-line distance: 811 m;
  recorded OSRM request origin-to-destination: 386 m. Both describe walks
  several times longer than the actual Menger-to-Alamo walk.
- Provider-grid bound: `docs/design/point-vs-area-heatmap.md:110` records
  that the FortyGuard historical downtown grid terminates at latitude
  29.42366°N. The committed fixture origin (29.421) and the recorded OSRM
  destination (29.4225) are south of that bound; both landmarks
  (29.42459, 29.42572/29.42583) are north of it. Correcting the identity
  moves the scenario inside the observed provider grid.

The OSRM snapped values recorded in the Issue #7 note
(`[-98.48598,29.426406]`, 57.3 m and `[-98.48533,29.422409]`, 10.5 m) remain
routing response observations and must not be described as official landmark
geocodes; this note follows and reaffirms that classification.

## Repo Impact Inventory

Grouping by which coordinate pair is embedded. "Must change in lockstep"
means the fixture stops matching (and the curated flow returns unavailable)
unless all files in the group change together, because the acquisition
sidecar is the authoritative match identity and `_fixture_matches` compares
origin/destination with `math.isclose` plus landmark/district/date/hour
equality ([app/services/trip_adapters.py:65-75,415-438](../../app/services/trip_adapters.py);
[ADR 0004 §2](../adr/0004-fixture-cache-provenance-ledger.md)).

### Group A — canonical trip fixture identity (7 files, lockstep)

| File                                       | Lines                              | What changes                                                                                                                                                                                                      |
| ------------------------------------------ | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fixtures/trip-analysis.acquisition.json`  | 9-16                               | Sidecar `request_configuration` origin/destination (authoritative match identity)                                                                                                                                 |
| `fixtures/trip-analysis.json`              | 7-8                                | Embedded mirrored `scenario` block (inert copy per ADR 0004 §2, kept in agreement)                                                                                                                                |
| `frontend/src/screens/TripSetupScreen.tsx` | 80-83                              | Curated request `origin_latitude/origin_longitude/destination_latitude/destination_longitude`                                                                                                                     |
| `frontend/src/test/tripSetup.test.tsx`     | 76-88 (coords 78-81)               | Expected POST body of the single `/api/trip/analyze` request                                                                                                                                                      |
| `tests/test_trip_adapters.py`              | 26-27                              | `_request()` origin/destination used for fixture matching                                                                                                                                                         |
| `tests/test_contracts.py`                  | 611-614                            | `_parse_trip_request` full-contract-body test                                                                                                                                                                     |
| `tests/test_api_integration.py`            | 110-113, 157-160, 198-201, 291-294 | Four request bodies that must match the fixture; also 240-243 (near-miss variants 29.4210/-98.4906/29.4255/-98.4836 in the untrusted-fields rejection test, not match-critical but derived from the old identity) |

### Group B — Issue #7 observation coordinates and their derivatives (12 files)

| File                                                       | Lines                                                                                       | What changes                                                                                                                                                                                                                               |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `docs/research/issue-7-san-antonio-provider-validation.md` | 49-53, 133, 171, 277-278, 298, 411, 467, 507                                                | Preserved live-call record: do not rewrite values. Needs a clarifying annotation that the recorded request's origin was at the Alamo, not the Menger, and its destination was south of both landmarks (this note supplies that correction) |
| `docs/design/point-vs-area-heatmap.md`                     | 78, 86, 96-97, 138-139, 168-172                                                             | Point request labeled "(The Alamo)" at `29.4259, -98.4861` and the 5-point "Menger Hotel to Alamo Plaza" route polyline; labels and/or coordinates need correcting so the start is Menger-side and the label matches the point             |
| `app/services/acquisition.py`                              | 41-42                                                                                       | `ENV_OBSERVATION_LATITUDE/LONGITUDE` (env-params acquisition scenario constants) — change only if the env fixture is reacquired at a new point                                                                                             |
| `fixtures/env-params.acquisition.json`                     | 4-10                                                                                        | Provider-sourced sidecar request identity `29.4259, -98.4861`; changeable only by new acquisition (strict matching, ADR 0004 §4)                                                                                                           |
| `tests/test_wiring.py`                                     | 26-34 (env body), 249-282 (heatmap bodies at the Group C point)                             | Env body must keep matching the committed provider fixture; heatmap bodies follow Group C                                                                                                                                                  |
| `tests/test_acquisition.py`                                | 100-109, 126, 155-163, 184-187                                                              | Acquisition scenario assertions for both the heatmap anchor and the env observation point                                                                                                                                                  |
| `tests/test_execution_degradation.py`                      | 302-310 (env request), 49-63, 190 (heatmap anchor)                                          | Env/heatmap request identities used for degradation matching                                                                                                                                                                               |
| `tests/test_area_heatmap.py`                               | 34-51 (`_SA_ROUTE` "Menger Hotel → The Alamo, simplified" and `_SHARP_TURN_ROUTE`), 253-288 | Route polylines derived from the OSRM observation; geometry tests remain valid for any polyline, but the canonical-route comment/derivation becomes false                                                                                  |
| `tests/test_lidar_corridor_probe.py`                       | 4-9                                                                                         | Corridor test inputs at the observation endpoints                                                                                                                                                                                          |
| `scripts/lidar_corridor_probe.py`                          | 26-30                                                                                       | `CORRIDORS["san_antonio"]` endpoints                                                                                                                                                                                                       |
| `scripts/validate_building_lidar_heights.py`               | 22                                                                                          | `ROUTE` over which the USGS LiDAR validation was computed                                                                                                                                                                                  |
| `scripts/derive_lidar_corridor_stats.py`                   | 21-24                                                                                       | `ROUTES["san_antonio"]`                                                                                                                                                                                                                    |

The Issue #7 research note's own statements (its acceptance-ledger hotel
list, LiDAR corridor tables at
`docs/research/issue-7-san-antonio-provider-validation.md:464-493`) were
computed over the old corridor and stay as historical records of that
corridor; re-running them over a corrected corridor would be new research,
not an edit.

### Group C — adjacent heatmap anchor `29.4241, -98.4936` (19 further files, decision-dependent)

This point matches neither landmark (roughly 700 m west of the Alamo; the
acquired provider tile polygon in `fixtures/acquired/heatmap-tcm-historical.json`
spans lon -98.4940 to -98.4934). It is not part of the trip identity, so the
Group A correction does not require touching it; aligning it with the
canonical area is a separate maintainer decision (see open questions).

Affected if aligned: `app/services/acquisition.py:39-40`
(`SAN_ANTONIO_LATITUDE/LONGITUDE`, overlaps Group B);
`fixtures/acquired/heatmap-tcm-historical.json` +
`.acquisition.json` (provider-sourced; reacquisition required);
`fixtures/heatmap-{exceedance,forecast,historical,persistence,tcm}.json` +
`.acquisition.json` (synthesized; correctable);
`frontend/src/mocks/data.ts:14-15` (fictional mock location "Harbor Arts
Quarter" happens to reuse the same coordinates);
`tests/test_env_params_series.py`, `tests/test_application_domain.py`,
`tests/test_provider_http.py`, `tests/test_fortyguard_contracts.py`,
`tests/test_fortyguard_live.py`, `tests/test_fastapi_app.py` (request
identities and fixture payloads);
plus the heatmap-related lines already listed in Group B files
(`tests/test_wiring.py:249-282`, `tests/test_acquisition.py:102-185`,
`tests/test_api_integration.py:27-60,326-327`,
`tests/test_execution_degradation.py:49-63,190`,
`tests/test_area_heatmap.py:253-288`).

`fixtures/heatmap-empty|failed|malformed.acquisition.json` contain no
coordinates; `fixtures/trip-analysis-unavailable.json` and its sidecar contain
no scenario; `frontend/src/types.ts:81` pins only the landmark name string
("The Alamo"), which does not change. `tests/test_spatial.py` uses synthetic
tile geometries, not the landmark identity. None of these are affected.

## Reacquire Versus Correct

ADR 0004 governs this decision
([docs/adr/0004-fixture-cache-provenance-ledger.md](../adr/0004-fixture-cache-provenance-ledger.md)):
sidecars are the single authoritative match identity; `source` is `provider`
for real acquisitions and `synthesized` for hand-made fixtures; synthesized
fixtures carry null activity IDs and retrieval times, "never fabricated
ones"; "Records tell the truth"; and the canonical acquisition is
maintainer-triggered because "real credits are spent" (ADR 0004 §5 and
Consequences).

Provenance split of the affected fixtures:

| Fixture                                                                              | Sidecar source                                                                     | Request identity                     | Consequence of a coordinate correction                                                                                         |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `fixtures/trip-analysis.json` (+sidecar)                                             | `synthesized`                                                                      | `29.421,-98.491` to `29.425,-98.484` | Correctable in place per ADR 0004 §2, with the correction documented (this note); no provider calls                            |
| `fixtures/env-params.json` (+sidecar)                                                | `provider` (activity `0b592283-ef6f-4783-bacb-79ea59e7254a`, retrieved 2026-08-24) | `29.4259, -98.4861`                  | Live acquisition identity. In-place editing would falsify a provider record; moving the point means a new billable acquisition |
| `fixtures/acquired/heatmap-tcm-historical.json` (+sidecar)                           | `provider` (activity `86f0ecbd-ac3a-4ffa-83bf-3915e65c425f`, retrieved 2026-08-27) | `29.4241, -98.4936`                  | Same as above                                                                                                                  |
| `fixtures/heatmap-{exceedance,forecast,historical,persistence,tcm}.json` (+sidecars) | `synthesized`                                                                      | `29.4241, -98.4936`                  | Correctable in place if Group C is aligned                                                                                     |
| `fixtures/trip-analysis-unavailable.json` (+sidecar)                                 | `synthesized`                                                                      | none                                 | Unaffected                                                                                                                     |

Option 1 — correct synthesized identities only (no billable calls):

- Update Group A atomically (sidecar, mirrored block, frontend request, five
  test files). Provenance is preserved: the sidecar remains `synthesized`
  with null activity ID and null `retrieved_at`, which stays truthful.
- The provider-sourced env-params fixture keeps its real identity at the
  observation point `29.4259, -98.4861`; its constant names in
  `app/services/acquisition.py:41-42` already say "observation", which remains
  accurate. The fixture set then intentionally mixes coordinates: trip
  identity at the landmarks, env analysis at the Alamo-side observation
  point, heatmap anchor 700 m west. That mixture is honest but leaves the
  fixture set spatially incoherent.
- Route assertions do not change: the fixture's 1000 m / 1200 m distances and
  20%/80% shade values are synthesized numbers, already fictional relative to
  the true ~130-150 m walk. Correcting the identity without re-deriving them
  keeps that fiction, now more visible.

Option 2 — correct synthesized identities and reacquire provider fixtures at
canonical coordinates:

- One billable `POST /v1/env_params` at a landmark point (plus status polls)
  and one billable `POST /v1/heatmap` over a landmark-anchored AOI, each
  producing a new raw fixture plus honest sidecar via
  `scripts/acquire_fixture.py` (maintainer-triggered, ledger-recorded,
  budget-checked per ADR 0004 §5). Old provider fixtures can be retired or
  kept as additional fixtures; they must not be edited in place.
- The heatmap AOI polygon moves: the acquired tile geometry currently spans
  lon -98.4940 to -98.4934 near `29.4241, -98.4936`; a landmark-anchored AOI
  would return different tiles. Both landmarks are north of the documented
  29.42366°N grid bound, so a landmark-anchored request stays inside the
  observed grid (unlike the current identity origin).
- Route geometry: a corrected FOSSGIS OSRM request (free, non-billable, as in
  Issue #7) between the corrected points would return routes on the order of
  130-200 m rather than 608.6 m. Any future route fixture re-derivation, and
  the LiDAR corridor research scripts (Group B), would need re-running over
  the new, much shorter corridor for research parity. The recorded
  Issue #7 evidence (608.6 m/625.9 m routes, 5/5 LiDAR footprints) stays
  valid as a record of the old corridor only.

Cost asymmetry: Option 1 spends zero credits and unblocks the acceptance
criteria about fixture/test agreement; Option 2 additionally buys spatial
coherence of the provider fixture set at the price of two billable
acquisitions (credits unknown per call; the account's plan tier is not
exposed, per the Issue #7 note) plus re-running free routing/LiDAR research.

Open questions the maintainers must answer:

1. Which Menger value is canonical: the OSM relation 1204761 centroid
   (recommended; crowd-sourced but fully specified), the THC RTHL 3334 UTM
   conversion (official but datum-ambiguous by roughly 200 m between NAD27 and
   NAD83 readings), or a deferred GNIS lookup (feature ID 6478249) performed
   interactively?
2. Which Alamo value is canonical: the UNESCO component central point
   `29.425833, -98.485833` (official, complex-level) or the OSM Alamo Church
   centroid `29.4257216, -98.4860990` (building-specific, crowd-sourced)?
   They are 29 m apart; an internally consistent all-OSM pair is also
   defensible if source-class consistency is preferred over official
   provenance for one side.
3. Are the provider-sourced env-params and acquired heatmap fixtures
   reacquired at canonical coordinates (billable), retained as
   observation-anchored fixtures with clarified wording, or retired?
4. Should the synthesized route distances/durations in
   `fixtures/trip-analysis.json` be re-derived from a real (free) FOSSGIS OSRM
   response between the corrected coordinates, so the fixture stops implying
   an ~800 m journey?
5. Do the Group B research scripts and `docs/design/point-vs-area-heatmap.md`
   example coordinates get re-derived over the corrected corridor, or are
   they frozen as Issue #7-era artifacts with an annotation?
6. Is the Group C heatmap anchor (`29.4241, -98.4936`) aligned to the
   canonical area in this issue or tracked separately?

## Recommended Canonical Values

- Origin (Menger Hotel): latitude 29.4245914, longitude -98.4864288
  (OpenStreetMap relation 1204761 centroid via Nominatim; crowd-sourced
  observation, WGS84; cross-checked by Wikipedia at 15 m and the THC RTHL 3334
  record at 63 m under NAD83/WGS84). No owner-side coordinate is published by
  the hotel itself; this is the most defensible fully specified value
  available non-interactively.
- Destination (The Alamo): N 29°25'33", W 98°29'9", decimal 29.425833,
  -98.485833 (UNESCO State Party nomination, San Antonio Missions component
  006 "Mission Valero / The Alamo", central point; official). Building-level
  alternative if a church-specific point is wanted: OSM way 92060042
  centroid 29.4257216, -98.4860990 (crowd-sourced), or its main-entrance node
  29.4257225, -98.4862666.
- Ordering: origin = Menger Hotel, destination = The Alamo, per the design
  doc, CONTEXT.md, and Issues #15/#40. The resulting journey is a roughly
  130-150 m northward walk (computed).
- The snapped OSRM values `[-98.48598,29.426406]` and
  `[-98.48533,29.422409]` remain routing response observations and are not
  landmark geocodes of any kind.

## Maintainer Resolutions, 2026-08-28

The open questions above were resolved by the maintainers; implementation
followed the same day (see "Verification Performed" below):

1. **Menger value:** the OSM relation 1204761 centroid
   `29.4245914, -98.4864288` is canonical.
2. **Alamo value:** the UNESCO component 006 central point
   `29.425833, -98.485833` is canonical.
3. **Provider fixtures:** env-params is retained as-is (an honest record ~20 m
   from the Alamo Church); no provider-sourced fixture is edited and none is
   reacquired for this issue. Group C heatmap-anchor realignment belongs to
   #23, which owns billable acquisition (cross-reference comment posted there).
4. **Route numbers:** re-derived from one free FOSSGIS OSRM foot request
   between the corrected points, observed 2026-08-28: HTTP 200, one route,
   193.1 m / 154.7 s, no alternatives at this scale. The fixture's "short"
   route now carries those observed values; the "shady" alternative is a
   synthesized 245.0 m / 196.0 s detour with placeholder shade until #19
   implements LiDAR-modeled shade (the OSM height-tag insufficiency and the
   USGS LiDAR alternative were established by Issue #7's research).
5. **Group B:** split disposition — this note and the Issue #7 note are
   immutable historical records (annotation added to the Issue #7 note);
   `docs/design/point-vs-area-heatmap.md` is living documentation and its
   labels and example coordinates were corrected; the LiDAR corridor scripts
   stay frozen as Issue-#7-era artifacts (#19 owns corridor re-derivation).
6. **Documentation home:** the pinned values live in the design doc's
   canonical-scenario block with provenance kept in this note.

## Verification Performed

- Read Issue #40 and Issue #15 in full via `gh issue view` (titles, bodies,
  states) and confirmed the quoted wording, including Issue #15's statement
  that it deliberately kept the existing fixture identity and deferred the
  correction to this issue.
- Read the repo sources of truth end to end: `docs/design/design-doc.md`,
  `CONTEXT.md`, all four ADRs (0001-0004),
  `docs/research/issue-7-san-antonio-provider-validation.md`,
  `docs/design/point-vs-area-heatmap.md`, `app/services/acquisition.py`,
  `app/services/trip_adapters.py`, `scripts/acquire_fixture.py`, the three
  LiDAR research scripts, and every fixture and sidecar named in the impact
  inventory. No file was modified; no `.env` or secret was read.
- Searched the repository with `rg` for every coordinate literal and name
  variant listed in the issue (29.421, 29.425, -98.491, -98.484, 29.4259,
  29.4225, -98.4861, -98.4853, 29.426, 29.4235, -98.4870, -98.4852) plus
  derived variants (29.4210, -98.4906, 29.4255, -98.4836, 29.4241, -98.4936,
  29.42366 grid bound) and the names "Menger" and "Alamo" (case-insensitive),
  excluding `node_modules`, `.git`, and the egg-info directory, and manually
  classified every hit into Groups A/B/C or explicitly excluded it
  (`test_spatial.py` synthetic tiles, empty/failed/malformed sidecars,
  unavailable trip fixture, types.ts name literal).
- Traced the fixture-matching mechanics in
  `app/services/trip_adapters.py` (sidecar-first identity, `math.isclose`
  coordinate comparison, strict env-params matching per ADR 0004) to confirm
  the lockstep requirement.
- Fetched primary web sources on 2026-08-28: thealamo.org (home and
  visiting-tips pages), mengerhotel.com, the UNESCO property page 1466 and
  the full 176,418,411-byte State Party nomination PDF (downloaded and
  text-extracted; Section 1.d coordinates quoted from the extracted text),
  NPGallery asset details for NRIS 66000808 and 77001425 plus the 1966 Alamo
  nomination PDF (UTM section illegible in OCR; verbal boundary quoted), THC
  Atlas records 5029003334 (Menger Hotel RTHL, UTM published) and 8200001755
  (Alamo SAL, no coordinates), the OSM API for relation 1204761 and way
  92060042/full (tags, node span, main-entrance node), Nominatim queries for
  Menger Hotel, Alamo Church, and The Alamo/Alamo Plaza, the OSM wiki Node
  page (WGS84 datum statement), Wikipedia parse-API infobox wikitext for
  Menger Hotel and Alamo Mission, the Wikidata entity for Q6816982, and the
  Historic Hotels of America property and location pages.
- Recorded failed/unreachable sources honestly: GNIS (session-gated Apex app
  and HTTP 403 downloads), a GLO Alamo URL (404), DuckDuckGo (bot challenge),
  the NPGallery search endpoint (parameters ignored), the NPGallery district
  PDF ("not yet digitized"), and the THC-hosted 153,550,332-byte district
  nomination (throttled to roughly 11 MB across resumed attempts; extraction
  failed on the partial file).
- Computed (pyproj, haversine) and clearly labeled every distance and decimal
  conversion in this note; DMS-to-decimal and UTM-to-decimal conversions are
  arithmetic on published values, and all cross-source distances are my
  calculations from observed coordinates, not published figures. Made no
  billable provider calls and consulted no routing engine.
- **Implementation follow-up, 2026-08-28 (same repository):** after the
  maintainer resolutions above, the canonical identity was applied to
  `fixtures/trip-analysis.json` and its sidecar (test-first: a request at the
  corrected coordinates previously failed fixture matching), the route block
  was re-derived with the observed OSRM values, the frontend curated request
  literals and their payload test were updated, the design-doc canonical block
  and `point-vs-area-heatmap.md` were corrected, the Issue #7 note received its
  ordering annotation, and one free FOSSGIS OSRM foot request between the
  corrected points was made and preserved (HTTP 200, one route, 193.1 m,
  154.7 s). No provider-sourced fixture, `.env` content, or billable endpoint
  was touched.
