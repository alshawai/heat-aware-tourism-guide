# Lidar, DSM, And Shade Feasibility For Austin And San Antonio

**Research date:** 2026-08-25
**Scope:** Authoritative elevation and surface data that could support time-dependent pedestrian route and sun/shadow analysis in Austin and San Antonio, Texas.

## Executive Recommendation

Use USGS 3DEP bare-earth elevation plus the original classified lidar point
clouds as the common baseline for both cities. The National Map catalog returns
Texas Central B1 2017 lidar tiles in the Austin area and Texas Central B2 2017
tiles in the San Antonio area, with 50 cm project naming and 2019 publication
records ([TNM product API](https://tnmaccess.nationalmap.gov/api/v1/products)).
The products are sufficient to model terrain and to derive a surface model
along a bounded route corridor, but not sufficient to claim a current,
authoritative, citywide DSM without processing and validation.

Do not subtract a standard 3DEP DEM from an assumed DSM and present the result
as measured building height. USGS defines DEMs as bare-earth products and
lidar point clouds as the 3D observations that include buildings, vegetation,
and ground ([USGS DEM versus lidar](https://www.usgs.gov/faqs/what-difference-between-lidar-data-and-digital-elevation-model-dem)).
For route-level work, derive a DSM or object-height features from classified
returns, then combine them with footprints and canopy data. Preserve source
acquisition dates, classifications, vertical reference, processing method,
and confidence for every corridor.

The practical recommendation is a staged implementation: first use the USGS
bare-earth DEM for grade and terrain exposure; next process USGS LPC only for
the route corridor; then add official city or state footprints, tree canopy,
building elevations, or 3D models where their metadata and dates are
confirmed. Report the result as modeled shade exposure, not observed shade.

## Decision Matrix

| Candidate                            | Austin coverage                                                 | San Antonio coverage                                                         | Resolution or content                                                                                                                  | Recency evidence                                                                                            | Access                                                                                                                                                                                          | Shade suitability                                                                                                       | Decision                                  |
| ------------------------------------ | --------------------------------------------------------------- | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| USGS 3DEP seamless DEM               | Nationwide 48-state coverage includes Austin                    | Nationwide 48-state coverage includes San Antonio                            | 1/3 arc-second, approximately 10 m; 1 arc-second, approximately 30 m; 1 m seamless tiles are being added as available                  | Tile metadata must be checked; 1 m seamless production began in mid-2025                                    | [DEM service](https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer), [Downloader](https://apps.nationalmap.gov/downloader/), TNM API                                | Good for terrain grade and terrain obstruction; too coarse or bare-earth for most building and tree shadows             | **Use as terrain baseline**               |
| USGS project-based 1 m DEM / OPR DEM | TNM product search is available by Austin bbox                  | TNM product search is available by San Antonio bbox                          | Project-based 1 m where available; OPR resolution follows source project                                                               | Product metadata required per tile                                                                          | [TNM product API](https://tnmaccess.nationalmap.gov/api/v1/products), [Downloader](https://apps.nationalmap.gov/downloader/)                                                                    | Better terrain surface than 10 m, but still bare earth and not an object surface                                        | **Use when available and documented**     |
| USGS classified lidar point cloud    | Texas Central B1 2017 tiles returned for Austin bbox            | Texas Central B2 2017 tiles returned for San Antonio bbox                    | Project filenames identify 50 cm source naming; LAS/LAZ point cloud with returns and classifications                                   | Austin records show 2017 collection/project and 2019 publication; San Antonio records show the same pattern | TNM API returns tile metadata and direct Rockyweb LAZ URLs; [Lidar Explorer](https://apps.nationalmap.gov/lidar-explorer/)                                                                      | Best common source for deriving route-corridor DSM, canopy returns, and object height; requires processing              | **Primary surface source**                |
| USGS packaged DSM                    | No Texas city coverage identified in 3DEP product documentation | No Texas city coverage identified in 3DEP product documentation              | 5 m IfSAR DSM is documented as Alaska-only                                                                                             | Alaska product documentation, not Texas                                                                     | [3DEP products](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services)                                                                                                         | Not a Texas option                                                                                                      | **Do not assume available**               |
| TNRIS / TxGIO lidar coverage         | State catalog can identify Texas projects and partners          | State catalog can identify Texas projects and partners                       | Coverage index, project metadata, and possible state-hosted products; exact Austin/San Antonio deliverables require catalog inspection | Coverage feature attributes must be read for dates and source                                               | [TNRIS lidar coverage item](https://www.arcgis.com/home/item.html?id=cdeaff17665e46529f52c2707b936f45), [TxGIO](https://geographic.texas.gov/), [TxGIO maps](https://geographic.texas.gov/maps) | Useful corroboration and possibly easier state delivery; not a substitute for checking source classifications and dates | **Check before duplicating USGS work**    |
| City of Austin GIS/Open Data         | Official GIS and open-data discovery channels exist             | N/A                                                                          | Potential footprints, canopy, elevation, and 3D layers; exact current layer inventory and licenses need verification                   | Layer-level metadata required                                                                               | [Austin GIS](https://www.austintexas.gov/department/gis), [Austin open data](https://data.austintexas.gov/)                                                                                     | Could improve local object completeness if authoritative and current                                                    | **Candidate supplement, unverified here** |
| City of San Antonio GIS/Open Data    | N/A                                                             | Official GIS page links downloadable GIS data and the current open-data site | Potential footprints, structures, vegetation, and planning layers; exact current layer inventory and licenses need verification        | Layer-level metadata required                                                                               | [San Antonio GIS](https://www.sanantonio.gov/GIS), [GIS data](https://www.sanantonio.gov/GIS/GISData), [Open Data SA](https://data.sanantonio.gov/)                                             | Could improve local object completeness if authoritative and current                                                    | **Candidate supplement, unverified here** |

## Findings By Requirement

### 1. Geographic Coverage

The USGS TNM product API supports a bounding-box search. Queries covering
Austin and San Antonio returned LPC products rather than a coverage assertion
based only on a map image. Austin results included `USGS Lidar Point Cloud TX
Central B1 2017`; San Antonio results included `USGS Lidar Point Cloud TX
Central B2 2017`. This is evidence of tile coverage in the queried city-area
bboxes, not proof that every municipal or metropolitan edge is covered by one
project. A production pipeline should query the full route corridor or city
boundary and require complete tile intersection.

3DEP seamless 1/3 arc-second and 1 arc-second DEMs cover the conterminous
United States, so both cities have baseline terrain coverage
([3DEP products](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services)).

### 2. Products And Spatial Resolution

USGS lists project-based 1 m DEMs, project-based 1/9 arc-second DEMs, and
seamless 1 m, 1/3 arc-second, and 1 arc-second DEMs. The 1/3 arc-second
product is approximately 10 m ground spacing; 1 arc-second is approximately
30 m. The seamless 1 m product uses 10 km by 10 km cloud-optimized GeoTIFF
tiles and has been in production since mid-2025, so availability is tile
dependent rather than guaranteed citywide ([3DEP products](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services)).

The point cloud is the more important surface product. USGS says lidar points
represent buildings, vegetation, and ground, while a DEM removes those
features. The TNM catalog results provide direct LAZ tile URLs and indicate
the Austin and San Antonio project families named above
([USGS lidar versus DEM](https://www.usgs.gov/faqs/what-difference-between-lidar-data-and-digital-elevation-model-dem)).
The 50 cm term in the project filenames should be treated as source-project
metadata, not as a promise that every derived raster or every point spacing
is exactly 0.5 m.

The 3DEP documentation describes a 5 m DSM as an IfSAR product available only
in Alaska. It should not be used as evidence of a ready-made Texas DSM
([3DEP products](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services)).

### 3. Collection Dates And Recency

The TNM catalog records Austin LPC products as the Texas Central B1 2017
project and San Antonio LPC products as the Texas Central B2 2017 project.
Representative returned records have publication dates of 2019-11-08 for
B1 and 2019-11-12 for B2, with catalog creation timestamps on 2019-11-13.
Those dates identify the available catalog records; they do not establish the
exact flight date for each tile or currentness in 2026. The project XML and
tile metadata must be retained and inspected for acquisition date, vertical
accuracy, quality level, breaklines, and processing lineage.

3DEP explicitly supplies product and spatial metadata, including XML and
GeoPackage metadata classes ([product metadata](https://www.usgs.gov/core-science-systems/ngp/ss/3dep-product-metadata),
[spatial metadata](https://www.usgs.gov/ngp-standards-and-specifications/3dep-spatial-metadata)).

### 4. Access, Download, And APIs

Use the TNM downloader for interactive acquisition and the TNM Access API for
bounded, repeatable searches. Use the dynamic 3DEP ImageServer for elevation
sampling or visualization. Use Lidar Explorer to inspect point-cloud
availability. For reproducible processing, download the LAZ tiles and their
metadata, checksum them, and create corridor-specific derivatives.

Austin and San Antonio city portals are official discovery channels for local
GIS layers. San Antonio's GIS page specifically directs users to GIS data and
the city's open-data site ([San Antonio GIS](https://www.sanantonio.gov/GIS)).
Austin provides an official GIS page and open-data portal
([Austin GIS](https://www.austintexas.gov/department/gis),
[Austin open data](https://data.austintexas.gov/)). Portal APIs should be
preferred over screen scraping, but each selected item still needs its own
service URL, fields, date, coordinate system, and license recorded.

### 5. Can Object Heights Be Derived?

Yes, conditionally. A common workflow is to classify or select non-ground
returns from the lidar cloud, rasterize a first/highest-return surface, and
subtract a co-registered bare-earth DEM. For a building polygon, a robust
estimate can use the distribution of surface-minus-ground values inside the
footprint rather than one maximum pixel. For trees, use canopy returns and
report canopy height separately from building height.

This works only when the point cloud has adequate returns, correct
classification, co-registration, vertical datum handling, and footprint
coverage. A DEM alone cannot provide above-ground height because USGS defines
it as bare earth. A surface raster derived from unfiltered highest returns
will mix roofs, trees, poles, wires, and lidar artifacts. A building footprint
alone provides planimetric obstruction but no reliable height.

USGS collection requirements and quality terminology are defined by the
current Lidar Base Specification ([LBS 2025 rev. A](https://www.usgs.gov/ngp-standards-and-specifications/lidar-base-specification-online)).
The specification is a collection requirement, not a guarantee that every
legacy or partner project has identical quality.

### 6. Licensing And Usage Constraints

USGS states that National Map services and downloaded data are free and in the
public domain with no restrictions, while requesting an originating-agency
acknowledgment ([USGS National Map terms](https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map)).
Use the requested acknowledgment: "Map services and data available from U.S.
Geological Survey, National Geospatial Program."

City and state portals can carry dataset-specific terms, disclaimers, and
third-party source notices. Do not infer that a city portal's general open-data
policy applies to every imagery, lidar, building, or 3D item. Capture the
selected item's metadata and license before redistribution or commercial use.

### 7. Processing Risks And Route-Level Suitability

The data can support a bounded, time-dependent model, but the answer is not a
direct provider field. For each route sample and time step, a plausible model
needs: route geometry and travel-time interpolation; a ground/terrain surface;
building and canopy surfaces; solar azimuth and elevation; observer height;
occlusion tests; and uncertainty handling. Terrain-only DEM analysis misses
urban objects. Raw DSM analysis can overstate shade from trees, poles, wires,
and temporary objects. A 10 m DEM cannot represent narrow sidewalks,
building setbacks, awnings, or street trees reliably.

Important risks are mixed acquisition seasons, changed buildings and trees
since collection, tile-edge seams, coordinate and vertical-datum mismatches,
voids and interpolation, classification errors, roofs represented as flat
surfaces, canopy porosity ignored, and uncertainty near the sun horizon.
Lidar is an observation at its collection time, not a time-varying surface.
Time dependence must come from solar geometry and an explicit assumption that
the mapped objects remain fixed. The output should therefore be a comparative
route exposure estimate with confidence and source-date labels, not a promise
of actual shade at every sidewalk point.

## Official Alternatives To Check

- **Building footprints:** Search the Austin and San Antonio open-data catalogs
  and TxGIO/TNRIS catalogs for authoritative building polygons. Prefer a layer
  with update date, source, unique identifier, and a documented relationship to
  lidar or address/building records.
- **Building elevations:** Search for building height, floor count, roof
  elevation, or 3D building layers. If absent, derive heights from classified
  lidar only after validating a sample against official records. Do not use
  floor count multiplied by a generic floor height as measured height.
- **Tree canopy:** Search city urban-forestry, land-cover, canopy, and lidar
  layers. A canopy-cover polygon is not a canopy-height surface; for shadow
  geometry, canopy height and crown extent are both needed.
- **3D city models:** Search city ArcGIS portals for multipatch, scene layer,
  CityGML, building level of detail, or 3D object layers. Verify whether the
  service is downloadable, whether heights are explicit, and whether the
  collection date matches the lidar/footprint source.
- **State alternative:** TNRIS/TxGIO's lidar availability layer is a useful
  authoritative index for Texas project coverage and metadata, but the indexed
  source and license must be followed to the actual point cloud or raster
  product ([TNRIS availability item](https://www.arcgis.com/home/item.html?id=cdeaff17665e46529f52c2707b936f45)).

## Explicit Unknowns

- Exact Austin and San Antonio municipal-boundary completeness of the B1 and B2
  project tiles, including holes, overlap, and metropolitan-area edges.
- Exact flight/acquisition dates, point density, quality level, vertical
  accuracy, coordinate reference system, and vertical datum for every tile
  selected for a route.
- Whether newer USGS, TNRIS, TxGIO, county, or city lidar supersedes the 2017
  project in either route corridor.
- Whether 1 m seamless DEM tiles are currently available for every corridor and
  whether their source dates are appropriate for the application.
- Whether Austin has, and publicly exposes, a current building-height,
  canopy-height, or 3D city-model layer suitable for redistribution.
- Whether San Antonio has, and publicly exposes, the equivalent current layers
  and usable service/download endpoints; the official GIS page confirms the
  portal, not the contents of every item.
- Whether city or state layers have restrictions beyond their portal-level
  open-data language, including imagery or partner-derived products.
- How to model canopy transparency, deciduous-season changes, awnings,
  arcades, parked vehicles, construction, and pedestrian-sidewalk elevation.
- What confidence threshold is acceptable for changing a recommended route.

## Corridor Prototype Results

On 2026-08-25, the repository prototype queried the official TNM Access API
using a 100 m locally projected buffer around one representative corridor in
each city. The exact query bboxes, product records, source URLs, and route
coordinates are preserved in the gitignored local artifact
`data/lidar-prototype/coverage.json`.

The San Antonio corridor intersected four catalog records representing adjacent
tiles from the Texas Central B2 2017 project. The canonical route itself was
covered by a completed 74,957,604-byte LAZ tile. The Austin corridor intersected
one Texas Central B1 2017 LAZ tile. This confirms that the common USGS source is
operationally discoverable for both test corridors, but the San Antonio result
also demonstrates that corridor buffers must be tiled and deduplicated before
processing.

The local decoder used `laspy` with `lazrs` and did not change application
dependencies. A 2 m screening grid was built from the route buffer: class 2
returns were treated as ground, and non-ground classes were screened as object
returns. The output is stored locally in `san_antonio-stats.json` and
`austin/stats.json` and is not committed because the source LAZ files are large.

| Corridor    | Points in 100 m buffer | Ground cells | Object cells | Positive object-height cells | Median surface-minus-ground |  Maximum |
| ----------- | ---------------------: | -----------: | -----------: | ---------------------------: | --------------------------: | -------: |
| San Antonio |              1,163,514 |       23,886 |       24,471 |                       12,178 |                      8.30 m | 108.39 m |
| Austin      |              1,891,003 |       49,548 |       44,717 |                       23,165 |                      8.37 m | 105.43 m |

These numbers establish processing feasibility, not building-height accuracy.
The approximately 105-108 m maxima are a direct warning that a raw
non-ground-minus-ground maximum is not suitable for shade geometry: it can
include tall objects, mixed cells, artifacts, or mismatched ground estimates.
The next prototype must mask against authoritative footprints, separate
building and canopy classes, reject outliers, retain tile metadata and vertical
reference, and validate representative heights against imagery or another
authoritative layer before projecting shadows.

## Sources

Primary sources consulted:

- [USGS, About 3DEP Products & Services](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services)
- [USGS, Difference Between Lidar Data And DEM](https://www.usgs.gov/faqs/what-difference-between-lidar-data-and-digital-elevation-model-dem)
- [USGS, Lidar Base Specification Online](https://www.usgs.gov/ngp-standards-and-specifications/lidar-base-specification-online)
- [USGS, 3DEP Product Metadata](https://www.usgs.gov/core-science-systems/ngp/ss/3dep-product-metadata)
- [USGS, 3DEP Spatial Metadata](https://www.usgs.gov/ngp-standards-and-specifications/3dep-spatial-metadata)
- [USGS, National Map Terms Of Use/Licensing](https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map)
- [USGS, TNM Access API](https://tnmaccess.nationalmap.gov/api/v1/products)
- [USGS, 3DEP Elevation ImageServer](https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer)
- [USGS, National Map Downloader](https://apps.nationalmap.gov/downloader/)
- [USGS, Lidar Explorer](https://apps.nationalmap.gov/lidar-explorer/)
- [City of Austin, GIS](https://www.austintexas.gov/department/gis)
- [City of Austin, Open Data](https://data.austintexas.gov/)
- [City of San Antonio, GIS](https://www.sanantonio.gov/GIS)
- [City of San Antonio, GIS Data](https://www.sanantonio.gov/GIS/GISData)
- [City of San Antonio, Open Data SA](https://data.sanantonio.gov/)
- [TNRIS lidar availability ArcGIS item](https://www.arcgis.com/home/item.html?id=cdeaff17665e46529f52c2707b936f45)
- [Texas Geographic Information Office](https://geographic.texas.gov/)
- [Texas Geographic Information Office map catalog](https://geographic.texas.gov/maps)
