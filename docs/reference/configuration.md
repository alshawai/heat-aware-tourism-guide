# Reference: Configuration Options

This page maps the product's configurable behavior to where it lives and
what changing it means. The raw variable table is in
[Environment variables](environment-variables.md). Anything labeled
**product policy** is a team decision, not a scientific or provider
standard — the full list of such policies with citations is in
[the proposal fact check](../research/proposal-fact-check.md).

## Deployment profiles

Chosen with `APP_PROFILE`; validated at startup.

| Profile          | Purpose                                | Live capability                                                      | Authentication                                                                                   |
| ---------------- | -------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `local`          | Development and fixture-backed review. | Optional (`ALLOW_LIVE`), credential-gated.                           | None.                                                                                            |
| `public-fixture` | The public demo deployment.            | Impossible: refuses `FORTYGUARD_API_KEY`, forces `ALLOW_LIVE=false`. | None.                                                                                            |
| `protected-live` | Maintainer live instance.              | Required.                                                            | HTTP Basic on every route except `/health`, finite call budget, absolute persistent ledger path. |

A profile governs startup guarantees and access; per-result `execution_mode`
(`fixture`/`live`) governs where an individual result originates. The two
are deliberately separate ([ADR 0009](../adr/0009-separated-public-fixture-and-protected-live-deployments.md)).

## Execution mode and degradation

`ALLOW_LIVE` enables live execution. On a live-path failure the execution
layer degrades in order: exact cache entry → matching fixture (date-relaxed
for forecast mode only) → explicit unavailable error. Every replay is
labelled and marked stale; budget exhaustion (HTTP 503) is never degraded
([ADR 0004](../adr/0004-fixture-cache-provenance-ledger.md)).

Polling bounds (interval, max polls, timeout, 404 grace) are configurable;
transient failures retry as status `GET`s only — billable work is submitted
once ([ADR 0003](../adr/0003-bounded-polling-and-404-tolerance.md)).

## Heat policy thresholds

| Option                     | Default                                                | Where                             | Notes                                                    |
| -------------------------- | ------------------------------------------------------ | --------------------------------- | -------------------------------------------------------- |
| NOAA Heat Index boundaries | 80 / 90 / 105 / 130 °F (≈26.7 / 32.2 / 40.6 / 54.4 °C) | `app/domain/heat_policy.py`       | Verified NOAA/NWS boundaries; fixed, not configurable.   |
| Provider TCM bands         | 30 / 35 / 40 °C                                        | `app/domain/heat_policy.py`       | Product policy, deliberately separate from NOAA.         |
| Cautious guidance shift    | one band earlier                                       | `app/domain/heat_policy.py`       | Product safety policy, not a medical transformation.     |
| Framing threshold          | 35 °C above                                            | acquisition request configuration | Visible in provenance; not presented as a NOAA boundary. |

See [Heat metrics](../explanation/heat-metrics.md) for the interpretation
semantics.

## Hotel ranking weights

Defaults: night 35 %, hot hours 25 %, persistence 20 %, day 20 %
(`app/domain/hotel_heat_score.py`). Configurable per request through
`POST /api/hotels/rank` (`weights` object with exactly those four keys,
summing to 1). Not environment-configurable. Semantics and caveats are in
[Hotel weights](../explanation/hotel-weights.md).

## Route analysis options

| Option                        | Default | Env variable                      | Notes                                                                                                                          |
| ----------------------------- | ------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Representative route distance | 1500 m  | `ROUTE_REPRESENTATIVE_DISTANCE_M` | Routes at or below it reuse the retained landmark TCM; longer routes share one corridor AOI (ADR 0006). Engineering heuristic. |
| Minimum route heat coverage   | 0.70    | `ROUTE_MINIMUM_HEAT_COVERAGE`     | Per-route tile coverage needed to trust route heat.                                                                            |
| Area corridor buffer          | 25 m    | `FORTYGUARD_AREA_BUFFER_M`        | Buffer around route geometry for the shared AOI.                                                                               |
| Area granularity              | 100     | `FORTYGUARD_AREA_GRANULARITY`     | Provider tile granularity (60/80/100).                                                                                         |

## Modeled shade options (ADR 0007)

| Option                           | Default           | Env variable                             | Notes                                                                                  |
| -------------------------------- | ----------------- | ---------------------------------------- | -------------------------------------------------------------------------------------- |
| Building search distance         | 250 m             | `SHADE_BUILDING_SEARCH_DISTANCE_M`       | Route corridor for building acquisition.                                               |
| Minimum building-height coverage | 0.70              | `SHADE_MINIMUM_BUILDING_HEIGHT_COVERAGE` | Area-weighted explicit+inferred height coverage needed to trust shade. Product policy. |
| Metres per level                 | 3.0               | `SHADE_METRES_PER_LEVEL`                 | `building:levels` → height approximation.                                              |
| Canonical timezone               | `America/Chicago` | `TRIP_CANONICAL_TIMEZONE`                | Exact-time shade evaluation timezone.                                                  |

Shade model identity (`route-shade-v1`, solar model `astral-3.2-apparent`)
is recorded in results; assumptions are in
[Shade assumptions](../explanation/shade-assumptions.md).

## Budgets and the ledger

- `FORTYGUARD_CALL_BUDGET` — all-time core call cap; unset = record-only.
- `FORTYGUARD_ENRICHMENT_CALL_BUDGET` — per-UTC-day enrichment cap.
- `FORTYGUARD_LEDGER_PATH` — JSONL append-only ledger location.

Credit truth comes only from reconciliation, never from per-call estimates
([Cost model](../explanation/cost-model.md)).

## Hotel district and place catalog

- `HOTEL_DISTRICT_BBOX` pins the Downtown San Antonio / Alamo Plaza hotel
  AOI. The fixture hotel service is additionally district-locked to
  `Downtown San Antonio`.
- The place catalog (`app/places.py`) fixes the eight searchable San Antonio
  places and their pinned coordinates. Adding a place is a code change with
  catalog tests, not a configuration change.

## Fixture sets

Wired explicitly in `app/wiring.py`:

- Root demo fixtures: heatmap variants (including empty/failed/malformed
  error states), env-params, hotel heat analysis, enrichment payloads.
- `fixtures/providers/` — genuine issue 23 acquisitions (FortyGuard, OSRM,
  Overpass).
- `fixtures/trips/` — four `trip-contract-v2` product snapshots with
  content-addressed `derived_from` links.

Matching is by sidecar `request_configuration` only; see
[How to acquire fixtures](../how-to/acquire-fixtures.md).

## Frontend build

The Vite dev server proxies `/api` and `/health` to the backend port 8000;
in deployment the backend serves the built assets itself. The public
fixture UI pins the curated scenario (places, hours, and a fixed date).
