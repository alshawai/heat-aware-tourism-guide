# Decision Rule: Point vs Area Heatmap Requests

Date: 2026-08-27
Status: Accepted

## Summary

The FortyGuard `POST /v1/heatmap` endpoint always receives a `polygon_aoi`
GeoJSON `FeatureCollection`. Two request paths produce that polygon:

1. **Point path** — a single (latitude, longitude) is expanded into a minimal
   square AOI (side = `granularity` meters). Returns 1–2 tiles covering the
   immediate vicinity of a coordinate. Transformation stamp:
   `point_to_aoi_expansion`.

2. **Area path** — a route polyline or arbitrary polygon is buffered into a
   corridor or used directly as the AOI. Returns a grid of tiles covering the
   full region. Transformation stamp: `route_to_aoi_buffer`.

## Decision table

| Criterion                       | Point request                                           | Area request                                                                  |
| ------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------------- |
| **Use when**                    | Single landmark, hotel, or coordinate                   | Route corridor, neighborhood, district                                        |
| **Input**                       | `(lat, lon)` + `granularity` (60/80/100 m)              | Route geometry or polygon + `buffer_m`                                        |
| **AOI construction**            | Square centered on point                                | Buffered polyline or caller polygon                                           |
| **Returned tiles**              | 1–2 (single cell)                                       | N tiles covering the full AOI grid                                            |
| **Granularity meaning**         | Side length of the expansion square AND tile resolution | Tile resolution within the submitted AOI                                      |
| **Default granularity**         | 60 m (ADR 0001)                                         | 100 m (ADR 0001)                                                              |
| **Consumer aggregation needed** | No — value is directly usable                           | Yes — tiles must be joined back to route segments or averaged over the region |
| **Provenance transformation**   | `point_to_aoi_expansion` v1                             | `route_to_aoi_buffer` v1                                                      |
| **Billable cost**               | Lower (small AOI)                                       | Higher (proportional to AOI area)                                             |

## When to use which

**Point request** — the right choice when the caller needs the heat metric at a
specific coordinate (e.g., "what is the temperature at the Alamo?"). It maps
1:1 to a coordinate, returns quickly, and the consumer uses the tile value
directly without aggregation.

**Area request** — the right choice when the caller needs spatial coverage
across a region: a walking route, a hotel neighborhood, or any geometry where
multiple tiles are needed to answer the question (e.g., "what percentage of
this route exceeds 35 °C?"). Area requests return a tile grid, and the
consumer must aggregate tiles using the spatial join infrastructure
(`join_polygon_to_tiles` in `app/domain/analysis.py`) or the route-segment
mapper (`map_tiles_to_route_segments`).

## Granularity semantics

In both request types, `granularity` controls the tile resolution of the
returned grid — how finely the provider subdivides the polygon. For point
requests, granularity also determines the side length of the expansion square
(they are the same value). For area requests, granularity only controls
subdivision; the AOI size is determined by the submitted polygon.

Allowed values are 60, 80, and 100 meters. Larger granularity means fewer,
coarser tiles (lower cost); smaller granularity means more, finer tiles
(higher resolution but higher cost). The documented heatmap area caps (Basic
10 mi², Pro 50 mi²) constrain how large the AOI can be.

## Polygon simplification

The FortyGuard documentation does not publish an explicit vertex-count limit
for `polygon_aoi`. However, large route corridors may produce polygons with
many vertices after buffering. The area adapter applies Douglas-Peucker
simplification when the buffered polygon exceeds a configurable vertex limit
(default 200), preserving the corridor shape while reducing payload size. The
simplification tolerance is chosen to keep the geometry within the buffer
width.

## Live API Validation & Test Evidence (2026-08-27)

Live verification was performed against the production FortyGuard API (`https://api.fortyguard.com`) using live maintainer credentials from `.env`.

> **Coordinate provenance note (2026-08-28):** these 2026-08-27 validations used
> the Issue-#7-era observation point `(29.4259, -98.4861)` — adjacent to the
> Alamo Church — and a southward five-point polyline from it. That point is a
> provider-observation anchor, not an official landmark geocode, and the
> polyline does not depict the canonical Menger Hotel → The Alamo journey. The
> corrected canonical identity is documented in
> [issue-40 coordinate research](../research/issue-40-menger-alamo-coordinates.md)
> and pinned in [the design doc](design-doc.md).

### 1. Point Heatmap Validation (`LiveHeatmapAdapter`)

- **Request**: Landmark `(29.4259, -98.4861)` (observation point adjacent to the Alamo Church), `TCM` analytic type, `granularity=100`.
- **Activity ID**: `07736420-f70c-4247-8bea-7c91aebff538`
- **Response**: Completed HTTP 200 after polling.
- **Returned Tiles**: 1 tile (`31.6053 °C`, `valid_time: 2024-07-15T00:00:00+00:00`).
- **Provenance Stamps**: `['live_envelope_unwrapped', 'point_to_aoi_expansion', 'valid_time_from_request', 'tcm_unit_celsius']`.

### 2. Area Heatmap Validation (`LiveAreaHeatmapAdapter`)

- **Request**: 5-point southward San Antonio polyline anchored at the observation point adjacent to the Alamo Church (recorded as "Menger Hotel to Alamo Plaza" at call time; that label was wrong — see the provenance note above), `buffer_m=25`, `granularity=100`.
- **Activity ID**: `88f8b050-d342-4f7c-90cf-ea4b351736c5`
- **Response**: Completed HTTP 200 after polling.
- **Returned Tiles**: 2 tiles (`31.6996 °C`, `valid_time: 2024-07-15T00:00:00+00:00`).
- **Provenance Stamps**: `['live_envelope_unwrapped', 'route_to_aoi_buffer', 'valid_time_from_request', 'tcm_unit_celsius']`.

### 3. Route Segment Heat Mapping (`map_tiles_to_route_segments`)

Intersected the returned multi-tile grid back with the projected route corridor segments:

- **Segment 0** (`(29.4259, -98.4861) -> (29.4250, -98.4858)`): `31.66 °C` weighted average, **`100.0%` coverage** (2 overlapping tiles).
- **Segment 1** (`(29.4250, -98.4858) -> (29.4241, -98.4853)`): `31.70 °C` weighted average, **`42.8%` coverage** (1 overlapping tile).

### 4. Spatial Grid Resolution & Coverage Findings

During live validation of route requests against FortyGuard's API, comparative tests revealed two critical indexing behaviors:

| AOI Mode                                         | Geometry Type         | Returned Tiles | Segment 0 Coverage | Segment 1 Coverage | Segment 2 Coverage | Grid Status                     |
| :----------------------------------------------- | :-------------------- | :------------- | :----------------- | :----------------- | :----------------- | :------------------------------ |
| **Thin Corridor** (`buffer_m=25m`)               | 50 m Width Polyline   | **2 tiles**    | **100.0%**         | **42.8%**          | **0.0%**           | Cell Clipping Drops Edges       |
| **Wide Corridor** (`buffer_m=60m`)               | 120 m Width Polyline  | **4 tiles**    | **100.0%**         | **96.0%**          | **48.8%**          | Partial Intersection            |
| **Full Rectangle AOI** (`use_bounding_box=True`) | Bounding Box Envelope | **6 tiles**    | **100.0%**         | **100.0%**         | **100.0%**         | **100% Full Coverage Achieved** |

- **Key Takeaway 1 (Full Bounding Box AOI)**: Setting `use_bounding_box=True` (or `FORTYGUARD_AREA_USE_BOUNDING_BOX=true` in `.env`) forces the adapter to send a full rectangular route envelope. This prevents FortyGuard's server-side spatial indexer from dropping edge tiles and achieves **100.0% full coverage** across all route segments in the provider grid.
- **Key Takeaway 2 (Provider Dataset Bounds)**: FortyGuard's historical temperature dataset for downtown San Antonio terminates at `latitude 29.42366°N`. Route coordinates south of `29.42366°N` fall outside the provider grid; `map_tiles_to_route_segments` detects these uncovered segments and logs an automated `logger.warning(...)` alert.

### 5. Transport Bug Fix

During live integration testing, a positional argument bug in `HttpFortyGuardTransport._request` was identified and resolved:

- `self._opener(request, self.timeout_seconds)` passed `timeout_seconds` positionally, causing Python's `urllib.request.urlopen` to treat the integer timeout as the HTTP POST body `data`.
- **Fix**: Updated to `self._opener(request, timeout=self.timeout_seconds)`.

## How to Use These APIs

### 1. Point Heatmap Request (Single Coordinate / Landmark)

Use `LiveHeatmapAdapter` when requesting heat for a single landmark or hotel:

```python
from datetime import date
from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.contracts import AnalyticType, HeatmapRequest
from app.integrations.fortyguard.live import LiveFortyGuardTransport, LiveHeatmapAdapter

# Initialize transport and client
transport = LiveFortyGuardTransport("https://api.fortyguard.com")
client = FortyGuardClient(transport, api_key="YOUR_API_KEY")

# Build point request (e.g., The Alamo in San Antonio)
request = HeatmapRequest(
    analytic_type=AnalyticType.TCM,
    latitude=29.425833,
    longitude=-98.485833,
    start_date=date(2026, 8, 27),
    forecast=True,
    granularity=60,  # 60m expansion square
)

adapter = LiveHeatmapAdapter(client)
result = adapter.load(request)

print("Activity ID:", result.activity_id)
print("Features (Tiles):", result.payload.get("features"))
print("Provenance:", [t.name for t in result.transformations])
```

### 2. Area Heatmap Request (Route Bounding Box / Corridor)

Use `LiveAreaHeatmapAdapter` with `use_bounding_box=True` when requesting heat across a route to ensure FortyGuard returns a complete rectangular grid covering 100% of all route segments:

```python
from datetime import date
from app.integrations.fortyguard.client import FortyGuardClient
from app.integrations.fortyguard.contracts import AnalyticType
from app.integrations.fortyguard.live import LiveFortyGuardTransport, LiveAreaHeatmapAdapter, map_tiles_to_route_segments

transport = LiveFortyGuardTransport("https://api.fortyguard.com")
client = FortyGuardClient(transport, api_key="YOUR_API_KEY")

# Sequence of (lat, lng) coordinates along the canonical route:
# Menger Hotel (29.4245914, -98.4864288) to The Alamo (29.425833, -98.485833),
# sampled from the observed FOSSGIS foot route (193.1 m)
route_coords = [
    (29.4246420, -98.4866120),
    (29.4256120, -98.4862580),
    (29.4257390, -98.4858120),
    (29.4257670, -98.4858080),
    (29.4258310, -98.4858240),
]

# Set use_bounding_box=True to submit a full rectangular route envelope
adapter = LiveAreaHeatmapAdapter(client, use_bounding_box=True)
area_result = adapter.load(
    route_coords,
    analytic_type=AnalyticType.TCM,
    start_date=date(2026, 8, 27),
    forecast=True,
    granularity=100,
)

tiles = area_result.payload.get("features", [])
print("Returned Tiles Count:", len(tiles))

# Map tiles back to route segments
segments = map_tiles_to_route_segments(route_coords, tiles)
for seg in segments:
    print(f"Segment {seg.segment_index}: value={seg.value} °C, coverage={seg.coverage:.1%}")
```

## References

- ADR 0001 §3 — point-to-AOI expansion, area granularity default
- ADR 0002 — transformation stamping
- `app/domain/analysis.py` — `build_aoi`, `join_polygon_to_tiles`
- `app/integrations/fortyguard/live.py` — `_point_square_feature_collection`,
  `build_documented_area_heatmap_payload`, `LiveAreaHeatmapAdapter`, `map_tiles_to_route_segments`
- `app/integrations/fortyguard/transport.py` — `HttpFortyGuardTransport`
