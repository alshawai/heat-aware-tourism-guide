# ADR 0001: Live provider adapter boundary

Date: 2026-08-27
Status: Accepted

## Context

Issues #6 and #9 delivered an offline-tested FortyGuard client stack (transport,
submit-once polling, error taxonomy, sanitization, normalization) and the shared
trip-analysis domain contract. But the client is never constructed in production
code: `ALLOW_LIVE=true` today reaches `RuntimeError("live execution is not
configured")`. Issue #10 wires the client behind the FastAPI service.

Issue #7's live research recorded a provider/app contract mismatch and deferred
it to "a future application change": the app transport sends `X-API-Key` while
the documented header is `api-key` (observed 401); the app emits a point-model
heatmap payload while the documented payload is `polygon_aoi` + `date_time` +
`granularity`; the app reads `activity_id` at top level while the documented
envelope nests it under `data`; the app normalizer expects
`features[].properties.value/unit/valid_time` while the documented completed
result is `data.result.map_data` (+ `stats_data`) with undocumented per-tile
properties.

## Decision

1. **The internal domain contract stays the single validated schema.** Live
   provider shapes never leak into it. A dedicated live adapter
   (`app/integrations/fortyguard/live.py`) owns all provider-specific behavior:
   documented payload construction, envelope handling, translation into the
   internal shape, and inference stamping.
2. **Envelope unwrapping is protocol-level.** `LiveFortyGuardTransport`
   subclasses `HttpFortyGuardTransport` and hoists the `data` object of every
   response so the existing client and poller (`client.py`) are untouched:
   submission yields `activity_id` at top level, status responses carry
   `status`, completion carries `result`.
3. **Documented payload construction is adapter-level.** The adapter converts
   the internal request into the documented payload: point requests are
   expanded to a square AOI (side = granularity, centered on the point,
   default 60 m; `granularity` is exposed on the public request, allowed
   60/80/100); area requests default internally to 100 m granularity. Dates are
   validated against the documented windows (historical ≥ 2019-01-01, forecast
   ≤ 12 h ahead); violations raise a classified VALIDATION error before any
   billable submission.
4. **The auth header is `api-key`** (raw key, no Bearer), per the official
   documentation and the observed live 401 with `X-API-Key`. The salvaged
   usage module already used `api-key`.
5. **Synchronous submit/poll execution model.** "Asynchronous client" refers to
   the provider's submit/poll job pattern, not asyncio. The client remains
   synchronous; FastAPI runs sync handlers in its threadpool, so bounded
   polling never blocks the event loop.
6. **Server owns credentials and wiring.** `app/settings.py` (stdlib dataclass)
   reads `FORTYGUARD_API_KEY`, `FORTYGUARD_BASE_URL`, `ALLOW_LIVE` from the
   process environment (with a minimal stdlib `.env` loader; process env wins).
   `ALLOW_LIVE=true` without a key fails fast at startup. The live client is
   injected into `create_app()` as a factory parameter (test seam, no global
   state). Live remains dual-gated: server `ALLOW_LIVE` and per-request
   `execution_mode`.
7. **Environment parameters are part of the same boundary.** A public
   `POST /api/env-params` route mirrors the heatmap gating. Requests ask for a
   full-day hourly series (filter_type 3) by default; an optional `hour`
   selects filter_type 1. A validated traveler window selects filter_type 2
   with matching `start_time` and `end_time` on both heatmap and environment
   requests. The request explicitly lists the two consumed `analysis`
   parameters (within the 3-parameter plan limit).
8. **Trip temporal preparation is a series-only contract stage.**
   `POST /api/trip/analyze` accepts a same-day half-open `start_hour` /
   `end_hour` window of at most twelve whole hours; it no longer accepts a
   selected visit `hour`. The initial `series_ready` response carries only the
   raw nullable environment series, timezone, conservative temperature anchor,
   provenance, and the fixed-anchor warning. Hotel, route, best-time, and
   comfort decisions remain outside this preparation stage.

## Consequences

- Issue #7's "resolve the transport/payload mismatch explicitly" lock is
  resolved by this ADR: the mismatch is resolved inside the adapter boundary,
  with the internal contract and its offline test suite intact.
- Cache identity (full internal request payload + endpoint + schema version)
  is unaffected: internal `to_payload()` shapes are untouched by the adapter's
  documented-payload construction (issue #11 owns cache-key policy).
- The translation adapter is the only place allowed to know the documented
  live shapes; `contracts.py` and `client.py` remain shape-neutral.
- `fixtures/env-params.json` is regenerated in the documented series shape
  (arrays + `metadata.timestamps`), built from the issue-7 recorded live
  observation; the previous scalar fixture was an invented shape.
- One risk accepted: the documented per-tile property name (`properties.temperature`)
  is undocumented; the adapter reads it from live evidence and stamps the
  inference in provenance. If the provider changes it, only the adapter
  changes.

## Alternatives considered

- Rewriting the internal contract and fixtures to the live shape: rejected —
  discards the validated offline contract and destabilizes issues #11–#18.
- asyncio rewrite with `httpx.AsyncClient`: rejected — no event-loop blocking
  (threadpool), discards tested seams, no functional gain.
- Making the client/normalizer bilingual (both shapes): rejected — mixes live
  specifics into neutral modules and encodes undocumented shapes.
