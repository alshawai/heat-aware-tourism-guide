# Reference: Domain Schemas

The product's contracts live in `app/domain/` — pure dataclasses and enums
with no I/O — so fixture replay, live execution, and HTTP responses all share
one validated shape. This page is the reading guide for the enums and the
response models you meet in the API and the fixtures. Provenance rules are
in [ADR 0004](../adr/0004-fixture-cache-provenance-ledger.md); the snapshot
codec is [ADR 0010](../adr/0010-trip-v2-product-snapshots.md).

## Core enums (`app/domain/contracts.py`)

| Enum                    | Values                                                                                                                                                                                                                                   | Meaning                                                                                                                       |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `TripMode`              | `curated`, `exploratory`                                                                                                                                                                                                                 | Fixed canonical trip vs traveler-chosen places.                                                                               |
| `ExecutionMode`         | `fixture`, `live`                                                                                                                                                                                                                        | Where a result comes from, per request.                                                                                       |
| `ResultState`           | `series_ready`, `success`, `degraded`, `unavailable`, `error`                                                                                                                                                                            | Product response state; trip-contract-v2 permits only `success`, `degraded`, `unavailable`.                                   |
| `HeatStatus`            | `elevated`, `not_elevated`                                                                                                                                                                                                               | Whether the applicable heat interpretation crosses the action threshold.                                                      |
| `RouteSetState`         | `alternatives_returned`, `single_route`, `no_suitable_returned_route`                                                                                                                                                                    | What the routing provider returned.                                                                                           |
| `RouteDecisionState`    | `mild_shortest_recommended`, `shade_required`, `shade_shadiest_recommended`, `shade_only_route_recommended`, `nighttime_coolest_recommended`, `insufficient_shade_comparison_required`, `heat_unavailable`, `no_suitable_returned_route` | The route comparison's explicit decision (ADR 0006/0007).                                                                     |
| `TemporalEvidenceState` | `exact`, `inconsistent`, `unavailable`                                                                                                                                                                                                   | Whether best-time evidence is an exact timestamp.                                                                             |
| `RouteHeatSource`       | `landmark_reuse`, `shared_corridor`                                                                                                                                                                                                      | Whether route heat reuses the landmark TCM or comes from a shared corridor AOI.                                               |
| `Confidence`            | `sufficient`, `insufficient`                                                                                                                                                                                                             | Evidence confidence for recommendations.                                                                                      |
| `MetricLabel`           | `provider_tcm`, `noaa_heat_index`                                                                                                                                                                                                        | Which metric the interpretation used.                                                                                         |
| `HeatBand`              | `below_caution`, `caution`, `extreme_caution`, `danger`, `extreme_danger`, `provider_lower`, `provider_moderate`, `provider_higher`, `provider_very_high`                                                                                | NOAA Heat Index bands (first five) vs product-only TCM bands (last four). See [Heat metrics](../explanation/heat-metrics.md). |
| `GuidancePolicy`        | `standard`, `cautious`                                                                                                                                                                                                                   | Whether the action threshold shifts one band earlier.                                                                         |
| `EnrichmentState`       | `available`, `unavailable`, `not_requested`                                                                                                                                                                                              | Optional enrichment outcome.                                                                                                  |

## Provenance

Service-level provenance (`app/domain/provenance.py`): `source`
(`provider`/`cache`/`fixture`), `retrieved_at`, `data_date`, `stale`,
`forecast`, optional `activity_id`, sanitized `raw_payload`, and
`transformations` (named, versioned inference steps such as
`tcm_unit_celsius` or `live_envelope_unwrapped`). Cache and fixture replays
are always marked `stale: true` with the true data date.

The acquisition sidecar `AcquisitionRecord` carries the full match identity:
`source` (`provider` or `synthesized`), provider identity, endpoint,
`request_configuration`, retrieval time, data date, status, schema version,
provider configuration version, safe activity ID, `derived_from` references
(fixture path, role, payload and sidecar SHA-256), and transformations.

## Heat interpretation

`HeatInterpretation` is the typed classification attached to best-time and
route results: metric, °C value, band, band label, action threshold band,
guidance policy, whether the value is an actual heat index, NOAA
availability, `action_required`, and the applied policy string. Provider TCM
values never claim to be NOAA Heat Index.

## Best time

`BestTimeResult`: hourly entries with metric values, `recommendation_hour`,
`recommendation_reason`, metric label, provenance, `hourly_coverage`,
`heat_interpretation`, optional `environmental_concerns`,
`recommended_hour_tcm_celsius`, framing `exceedance_hours` /
`persistence_hours` with the declared 35 °C threshold and direction,
optional `recommendation_time` + timezone, and `temporal_evidence`. The
environmental concern profile assesses all requested parameters per hour
against declared NOAA, EPA, physiological, and product thresholds; missing
parameters are `not_reported`, never assumed safe.

## Hotel ranking

`HotelRankingResult`: ranked hotels with four components (`night`,
`hot_hours`, `persistence`, `day`), score, percentile, and tie groups;
weights actually used; usable and discovered counts; provenance; optional
enrichment; component units (°C or hours); component temporal metadata with
the `date_level_not_interval_maximum` caveat. Scoring semantics are in
[Hotel weights](../explanation/hotel-weights.md).

## Route comparison

`RouteOption` per returned route: identity, distance, duration, heat value
and status, optional `modeled_shade_percent` with confidence and model
label, building coverage (explicit/inferred/unknown fractions and counts),
recommendation flag and reason, geometry, heat coverage and source, heat
interpretation, and shade limitations.

`RouteComparisonResult`: alternatives, `recommended_id`, reason, heat
status, corridor heat value, metric and unit, coverage, confidence,
comparison scope (`returned alternatives`), provenance, fallback reason,
route-set and decision states, plus routing/heat/building/solar provenance.

## Trip response and the v2 codec

`TripAnalysisResponse` enforces per-state invariants: `success` carries
best time, hotels, and routes; `degraded` additionally carries non-empty
`degraded_reasons` keyed by `best_time`/`hotels`/`routes`; `unavailable`
carries `unavailable` with reason, recoverable flag, code (default
`scenario_unavailable`), and optional action.

`app/services/trip_contract_v2.py` is the strict shared codec
(`SCHEMA_VERSION = "trip-contract-v2"`). `encode_trip_analysis_v2` produces
the snapshot shape (`schema_version`, `state`, `best_time`, `hotels`,
`routes`, `unavailable`, `degraded_reasons`); the API envelope adds
`request_identity`, `mode`, `execution_mode`. The decoder validates exact
key sets, types, finite numbers, and ISO datetimes, and re-checks request
alignment. The same codec is used for live, fixture, and HTTP responses;
v1 compatibility is intentionally absent. Product snapshots under
`fixtures/trips/` are generated offline from normalized acquisitions and are
never hand-authored.

## Result-set tokens

`app/domain/result_tokens.py` issues HMAC-SHA256-signed, URL-safe tokens
(default TTL 15 minutes) embedding the request identity, trusted base
result IDs, and route geometry. They authorize optional enrichment without
recomputing the base result or trusting caller-supplied coordinates
([ADR 0008](../adr/0008-optional-enrichment-budgets-and-boundaries.md)).

## Credit ledger records

`data/ledger.jsonl` holds two record kinds (`app/domain/ledger.py`): `call`
records (activity ID, endpoint, `credits_used` when the provider prices it,
completion time, status, core/enrichment scope) and `reconciliation`
records (authoritative account totals for a date window). Reload is
idempotent. See [Cost model](../explanation/cost-model.md).
