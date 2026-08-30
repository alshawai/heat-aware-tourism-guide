# Reference: HTTP API

All product routes are served by the FastAPI application (`app/main.py`,
composed in `app/wiring.py`, routes defined in `app/api.py`). The domain
schemas behind these payloads are in
[Domain schemas](domain-schemas.md); the decision logic is explained in
[Architecture](../explanation/architecture.md) and the ADRs.

Authentication: in the `protected-live` profile, every route except
`GET /health` requires HTTP Basic authentication (`401` otherwise). In
`local` and `public-fixture` profiles, no authentication is used.

Error model (three-way split):

- Validation problems (`KeyError`/`TypeError`/`ValueError`) → **HTTP 400**
  `{"status": "error", "error": "<message>"}`.
- Budget exhaustion, provider failures, and unavailable scenarios →
  **HTTP 503** `{"status": "unavailable", "error": "<message>",
"error_kind": "<kind>"}` (kinds include `budget_exceeded`).
- Product-level "unavailable" decisions (for example a trip with no matching
  fixture) are **HTTP 200** responses with `state: "unavailable"` inside the
  payload, not errors.

## GET /health

Unauthenticated in every profile. Never calls FortyGuard, Overpass, or OSRM.

```json
{
  "status": "ok",
  "deployment_profile": "public-fixture",
  "mode": "fixture",
  "execution_capability": "fixture-only"
}
```

`mode` is `"live"` or `"fixture"`; `execution_capability` is
`"fixture-and-live"` or `"fixture-only"`.

## GET /api/places/search?q=<query>

Place search over the built-in San Antonio catalog (Menger Hotel, The Alamo,
Main Plaza, Historic Market Square (El Mercado), San Fernando Cathedral,
Spanish Governor's Palace, Briscoe Western Art Museum, Tower of the
Americas). Queries shorter than two characters return `400`. Returns
`{"places": [...]}`.

## POST /api/heatmap

Point heatmap analysis. Request body (JSON object):

| Field                     | Required                   | Notes                                                            |
| ------------------------- | -------------------------- | ---------------------------------------------------------------- |
| `analytic_type`           | yes                        | `tcm`, `exceedance`, or `persistence`.                           |
| `latitude`, `longitude`   | yes                        | Finite; must be inside the US extent.                            |
| `start_date`              | yes                        | ISO date string.                                                 |
| `forecast`                | no                         | Boolean, default `true`.                                         |
| `threshold_celsius`       | for exceedance/persistence | Framing threshold in °C.                                         |
| `direction`               | for exceedance/persistence | `above` or `below`.                                              |
| `granularity`             | no                         | 60, 80, or 100 (default 60).                                     |
| `start_hour` / `end_hour` | no                         | Both or neither; window at most 12 hours.                        |
| `execution_mode`          | no                         | `fixture` (default) or `live`; `live` is rejected when disabled. |

Response: `{"tiles": [Tile...], "provenance": {...}, "activity": {...}?}`.
Each tile carries identity, geometry, metric, `value_celsius` (tcm) or
`metric_value` + unit, source, valid time, forecast flag, threshold and
direction, and activity ID. Provenance `source` is `provider` (live),
`cache`, or `fixture`; replayed results are marked `stale`.

## POST /api/env-params

Environmental parameter series for one point. Request body:

| Field                        | Required | Notes                                                 |
| ---------------------------- | -------- | ----------------------------------------------------- |
| `latitude`, `longitude`      | yes      | Finite; US extent.                                    |
| `start_date`                 | yes      | ISO date string.                                      |
| `temperature_anchor_celsius` | yes      | The caller-supplied °C anchor the series is fixed to. |
| `hour`                       | no       | Single hour 0-23; exclusive with the window pair.     |
| `start_hour` / `end_hour`    | no       | Window pair; at most 12 hours.                        |
| `execution_mode`             | no       | `fixture` or `live`.                                  |

Response: `{"entries": [...], "timezone", "forecast", "warning",
"provenance"}`. Entries are per-hour with `valid_time`, nullable metric
values (missing stays `null`, never zero), and the canonical parameter map.
The standing `warning` states that the series is fixed to the caller-supplied
anchor and is not a real 24-hour forecast.

## POST /api/trip/analyze

The main product endpoint: one complete trip setup in, one
`trip-contract-v2` product response out. Request body:

| Field                                                                                  | Required | Notes                                 |
| -------------------------------------------------------------------------------------- | -------- | ------------------------------------- |
| `mode`                                                                                 | yes      | `curated` or `exploratory`.           |
| `origin_latitude`, `origin_longitude`, `destination_latitude`, `destination_longitude` | yes      | Finite coordinates.                   |
| `landmark_name`, `district_name`                                                       | yes      | Non-empty strings.                    |
| `date`                                                                                 | yes      | ISO date string.                      |
| `start_hour`, `end_hour`                                                               | yes      | Whole hours; window at most 12 hours. |
| `cautious`                                                                             | no       | Boolean, default `false`.             |
| `execution_mode`                                                                       | no       | `fixture` or `live`.                  |

Constraints:

- `hour` is no longer accepted (use `start_hour`/`end_hour`).
- Server-owned analysis fields (`heat_metric`, `hotels`, `routes`,
  `provenance`, ...) submitted by the caller are rejected with `400`.
- Curated mode must use the canonical scenario: landmark `The Alamo`,
  district `Downtown San Antonio`, origin `29.4245914, -98.4864288`
  (Menger Hotel), destination `29.425833, -98.485833` (The Alamo).
- Live execution additionally requires both endpoints inside the supported
  US extent; otherwise the response is an HTTP 200
  `state: "unavailable"` with code `unsupported_geography`.

Response envelope (`api`): `request_identity`, `mode`, `execution_mode`,
`state` (`success` | `degraded` | `unavailable`), and per-state `best_time`,
`hotels`, `routes`, `unavailable`, `degraded_reasons`, plus
`result_set_token` when a usable result set exists. The token authorizes
optional enrichment for fifteen minutes.

The committed fixture set answers these identities (date `2024-07-15`):

| Scenario                                           | Mode        | Window      | Outcome                                                    |
| -------------------------------------------------- | ----------- | ----------- | ---------------------------------------------------------- |
| Menger Hotel → The Alamo                           | curated     | 08:00-20:00 | Degraded: hour-only best time, single returned route.      |
| Main Plaza → Historic Market Square                | exploratory | 10:00-17:00 | Single returned route.                                     |
| San Fernando Cathedral → Spanish Governor's Palace | exploratory | 10:00-17:00 | Two routes, weak height evidence, no route recommendation. |
| Briscoe Western Art Museum → Tower of the Americas | exploratory | 10:00-17:00 | Whole-trip unavailable (`provider_data_missing`).          |

Any other identity returns `state: "unavailable"` with code
`scenario_unavailable`.

## POST /api/hotels/rank

District hotel heat ranking. Request body allows exactly
`district_name` (required, non-empty), `execution_mode`, and `weights`.
`weights` must contain exactly `night`, `hot_hours`, `persistence`, `day` —
finite, non-negative, summing to 1 (tolerance 0.001).

Response: `{"state": "available" | "unavailable", "district_name",
"execution_mode", "reason", "discovered_count", "usable_count",
"components", "ranking", "result_set_token"?}`. The ranking contains the
weights used (`weight_label`: `product defaults` or `custom`), complete
candidate count, ranked output, and hotel entries with component
assignments and percentiles. Fewer than five usable hotels is an explicit
`unavailable` state, not an empty success.

## Optional enrichment

Three drill-down routes operating on an existing result set:

| Route                                     | Kind             | Extra request fields                                             |
| ----------------------------------------- | ---------------- | ---------------------------------------------------------------- |
| `POST /api/hotels/{hotel_id}/environment` | environment      | `temperature_anchor_celsius` (required, finite).                 |
| `POST /api/routes/{route_id}/canopy`      | satellite canopy | —                                                                |
| `POST /api/routes/{route_id}/street-view` | street view      | optional `point {latitude, longitude}` within 50 m of the route. |

All three require `result_set_token` (from a prior trip or hotel response)
and accept optional `refresh`. The target must belong to the token's result
set. Responses: `{"status": "success", "kind", "target_id", "state",
"reason?", "base_result", "usage", "provenance?", "limitations", "payload"}`.
Invalid or malformed tokens return `400` (`invalid_result_set_token`);
expired tokens return `410` (`result_set_expired`); targets outside the
result set return `400` (`result_not_in_result_set`). Enrichment never
alters the base result; failure preserves it with an item-level unavailable
state.

## Static assets and SPA fallback

`GET /assets/*` serves the built frontend; `GET /{path}` falls back to the
SPA `index.html` for deep links. These exist so one service can serve the
whole product (see `render.yaml` and the [deployment guide](../how-to/deploy.md)).
