# Reference: Environment Variables

Settings are loaded by `app/settings.py` from the process environment and an
optional `.env` file at the repository root. The process environment always
wins over the file; an explicitly set empty value unsets whatever the file
provided. `.env.example` documents the common subset and contains no secret
values.

## Deployment and execution mode

| Variable                  | Default                      | Meaning                                                                                                                                      |
| ------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `APP_PROFILE`             | `local`                      | Deployment profile: `local`, `public-fixture`, or `protected-live`. Drives startup validation, authentication, and capability guarantees.    |
| `ALLOW_LIVE`              | `false`                      | Enables live provider execution. Must be `false` for `public-fixture`, `true` for `protected-live`.                                          |
| `FORTYGUARD_API_KEY`      | (unset)                      | Provider key. Required when `ALLOW_LIVE=true` (except `public-fixture`, which forbids it). Secret — never commit.                            |
| `FORTYGUARD_BASE_URL`     | `https://api.fortyguard.com` | Provider base URL.                                                                                                                           |
| `RESULT_SET_TOKEN_SECRET` | (unset)                      | HMAC secret for signing result-set tokens. When unset, tokens are unsigned (acceptable for local fixture use; required on `protected-live`). |

## Live authentication (`protected-live` only)

| Variable             | Default | Meaning                                                                                             |
| -------------------- | ------- | --------------------------------------------------------------------------------------------------- |
| `LIVE_AUTH_USERNAME` | (unset) | HTTP Basic username. Required for `protected-live`.                                                 |
| `LIVE_AUTH_PASSWORD` | (unset) | HTTP Basic password. Required for `protected-live`. Secrets — store in the provider secret manager. |

## FortyGuard polling (ADR 0003)

| Variable                           | Default | Meaning                                                               |
| ---------------------------------- | ------- | --------------------------------------------------------------------- |
| `FORTYGUARD_POLL_INTERVAL_SECONDS` | `5.0`   | Delay between status polls. Positive number.                          |
| `FORTYGUARD_MAX_POLLS`             | `24`    | Hard cap on polls per activity. Positive integer.                     |
| `FORTYGUARD_TIMEOUT_SECONDS`       | `30.0`  | Per-request HTTP timeout.                                             |
| `FORTYGUARD_404_GRACE_CHECKS`      | `3`     | Tolerated consecutive 404 status checks immediately after submission. |

## Cost ledger and budgets (ADR 0004)

| Variable                                   | Default             | Meaning                                                                                                                                          |
| ------------------------------------------ | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `FORTYGUARD_CALL_BUDGET`                   | (unset)             | All-time cap on submitted live core calls. Unset means record-only. Enforced unit is calls, not credits. Required positive for `protected-live`. |
| `FORTYGUARD_LEDGER_PATH`                   | `data/ledger.jsonl` | Append-only JSONL ledger path. Empty value selects an in-memory ledger. Must be an absolute path on a persistent disk for `protected-live`.      |
| `FORTYGUARD_ENRICHMENT_CALL_BUDGET`        | (unset)             | Separate per-UTC-calendar-day cap on submitted enrichment activities. Unset means record-only.                                                   |
| `FORTYGUARD_ENVIRONMENT_ESTIMATED_CREDITS` | (unset)             | Estimated credits per environment enrichment submission (display only).                                                                          |
| `FORTYGUARD_SATELLITE_ESTIMATED_CREDITS`   | (unset)             | Same, satellite canopy.                                                                                                                          |
| `FORTYGUARD_STREETVIEW_ESTIMATED_CREDITS`  | (unset)             | Same, street view.                                                                                                                               |

## Area heatmap requests

| Variable                           | Default | Meaning                                        |
| ---------------------------------- | ------- | ---------------------------------------------- |
| `FORTYGUARD_AREA_BUFFER_M`         | `25.0`  | Corridor buffer around route geometry, metres. |
| `FORTYGUARD_AREA_GRANULARITY`      | `100`   | Tile granularity (60, 80, or 100).             |
| `FORTYGUARD_AREA_USE_BOUNDING_BOX` | `true`  | Use the bounding rectangle as the AOI polygon. |
| `FORTYGUARD_AREA_MAX_VERTICES`     | `200`   | Maximum AOI polygon vertices.                  |

## OSRM routing

| Variable                          | Default                                                 | Meaning                                                                                  |
| --------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `OSRM_BASE_URL`                   | `https://routing.openstreetmap.de/routed-foot/route/v1` | FOSSGIS pedestrian OSRM instance.                                                        |
| `OSRM_PROFILE`                    | `foot`                                                  | Routing profile.                                                                         |
| `OSRM_USER_AGENT`                 | `HeatAwareTourismGuide/0.1 (contact: …)`                | Descriptive User-Agent.                                                                  |
| `OSRM_TIMEOUT_SECONDS`            | `15.0`                                                  | Request timeout.                                                                         |
| `OSRM_PROVIDER_INSTANCE`          | `fossgis-routed-foot`                                   | Provider instance identity used in cache keys and sidecars.                              |
| `ROUTE_REPRESENTATIVE_DISTANCE_M` | `1500.0`                                                | Short/long route threshold: routes at or below it reuse the retained landmark TCM value. |
| `ROUTE_MINIMUM_HEAT_COVERAGE`     | `0.70`                                                  | Minimum per-route tile coverage for trusting route heat. At most 1.                      |

## Overpass (hotels, buildings)

| Variable                       | Default                                   | Meaning                                                                             |
| ------------------------------ | ----------------------------------------- | ----------------------------------------------------------------------------------- |
| `OVERPASS_ENDPOINT`            | `https://overpass-api.de/api/interpreter` | Overpass API endpoint.                                                              |
| `OVERPASS_USER_AGENT`          | `HeatAwareTourismGuide/0.1 (contact: …)`  | Descriptive User-Agent.                                                             |
| `OVERPASS_TIMEOUT_SECONDS`     | `30.0`                                    | Query timeout.                                                                      |
| `OVERPASS_MAX_ATTEMPTS`        | `2`                                       | Bounded attempts per query.                                                         |
| `OVERPASS_RETRY_DELAY_SECONDS` | `30.0`                                    | Delay before retry (HTTP 429 handling).                                             |
| `HOTEL_DISTRICT_BBOX`          | `29.421,-98.490,29.429,-98.482`           | Hotel district AOI as `south,west,north,east` (Downtown San Antonio / Alamo Plaza). |

## Modeled shade (ADR 0007)

| Variable                                 | Default                       | Meaning                                                                                                    |
| ---------------------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `SHADE_BUILDING_SEARCH_DISTANCE_M`       | `250.0`                       | Route corridor width for building acquisition.                                                             |
| `SHADE_MINIMUM_BUILDING_HEIGHT_COVERAGE` | `0.70`                        | Area-weighted building-height coverage needed to trust modeled shade. Product policy, not an OSM standard. |
| `SHADE_METRES_PER_LEVEL`                 | `3.0`                         | Approximation used to infer height from `building:levels`.                                                 |
| `TRIP_CANONICAL_TIMEZONE`                | `America/Chicago`             | Canonical trip timezone (IANA name).                                                                       |
| `SHADE_BUILDING_SCHEMA_VERSION`          | `building-v1`                 | Building fixture schema version.                                                                           |
| `SHADE_PROVIDER_CONFIG_VERSION`          | `overpass-building-config-v1` | Provider configuration identity.                                                                           |
| `SHADE_MODEL_VERSION`                    | `route-shade-v1`              | Shade model identity.                                                                                      |

## CI and repository variables

| Variable           | Where               | Meaning                                                                          |
| ------------------ | ------------------- | -------------------------------------------------------------------------------- |
| `ALLOW_LIVE=false` | CI workflow env     | All automated checks run fixture-only; no credentials present.                   |
| `KEEP_WARM_URL`    | Repository variable | Override target for the keep-warm workflow (defaults to the demo `/health` URL). |

## Profile enforcement summary

| Check                    | `local`           | `public-fixture` | `protected-live`                      |
| ------------------------ | ----------------- | ---------------- | ------------------------------------- |
| `ALLOW_LIVE`             | optional          | must be `false`  | must be `true`                        |
| `FORTYGUARD_API_KEY`     | required iff live | forbidden        | required                              |
| Basic auth               | off               | off              | required, all routes except `/health` |
| `FORTYGUARD_CALL_BUDGET` | optional          | n/a              | required, positive                    |
| `FORTYGUARD_LEDGER_PATH` | optional          | n/a              | required, absolute                    |

Validation happens at startup (`SettingsError`) and is re-enforced at the
composition boundary (`validate_profile_settings`).
