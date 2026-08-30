# ADR 0008: Optional enrichment budgets and decision boundaries

Date: 2026-08-30
Status: Accepted

## Context

Issue #22 adds premium environmental, satellite-canopy, and street-view
enrichment to already narrowed hotel and route results. These calls must be
intentional and observable without changing the core heat, ranking, shade, or
route decisions. FortyGuard does not reliably attribute credits to individual
activities, while the existing ledger can authorize provider call submissions.

## Decision

Enrichment is an explicit, bounded drill-down operation, separate from core
analysis. It is exposed through typed endpoints and uses a short-lived,
server-signed result-set token so the server can validate selected result IDs
and use trusted coordinates/geometries without recomputing the base result.

Live enrichment is disabled by default. A separate UTC calendar-day enrichment
call budget protects core capacity. One budget unit is one submitted provider
activity; submitted activities consume capacity even when they later fail.
Configured per-kind credit values are estimates only. Individual actual credit
usage remains unknown unless exact attribution is authoritative. Cache hits and
fixture replay consume no live budget.

The three kinds are: hotel environmental parameters with a caller-supplied
temperature anchor, contextual satellite canopy for a route midpoint, and
street-view metadata for a selected route point. None is a core shade
measurement or may alter a recommendation. Provider images are not persisted.
Fixture mode never constructs or reaches the live client. Missing fixtures,
budget exhaustion, configuration failures, provider failures, and unusable
payloads return item-level unavailable states while preserving the base result.

Freshness is configured per kind (environment and street view: 24 hours;
satellite canopy: 7 days). Explicit refresh may bypass a stale/fresh cache only
when live execution is configured and budget is available.

## Alternatives considered

### Shared core budget

Rejected because optional exploration could consume capacity required for core
heat and route analysis.

### Exact per-activity credit enforcement

Rejected because the provider reports credits only in aggregate date-window
usage and does not provide reliable activity-level attribution.

### Automatic enrichment

Rejected because premium usage must follow explicit user intent and enrichment
is not required for the core result.

### Provider-specific live schemas inferred from assumptions

Rejected. Satellite and street-view live adapters remain gated until their
endpoint and response schemas are validated; fixture and normalized contract
coverage can proceed without speculative billable calls.

## Consequences

- Core result computation remains independently valid and stable.
- Operators receive truthful call records and estimated-versus-actual usage.
- Users see explicit enrichment state, limitations, provenance, and safe usage
  metadata.
- Daily scope and reservations require ledger support beyond the current
  all-time budget implementation.
- Provider-schema validation remains a release prerequisite for live satellite
  and street-view calls.
