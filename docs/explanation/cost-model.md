# Explanation: Cost Model

How provider spending is understood, recorded, and bounded. Operations are
in [How to configure live mode](../how-to/configure-live-mode.md) and
[How to acquire fixtures](../how-to/acquire-fixtures.md); the contract is
[ADR 0004](../adr/0004-fixture-cache-provenance-ledger.md) §5.

## What is known and what is not

- The hackathon access is Premium, with roughly 2,000,000 credits per
  teammate and about 6,000,000 collectively. Published offerings list Basic
  at 1,000,000 monthly credits and Pro at 5,000,000, with heatmap area caps
  of 10 and 50 mi² ([API pricing](https://fortyguard.com/api-pricing)).
- Public documentation does not establish exact per-request credit costs or
  numeric rate limits, and responses do not carry a credit field. The
  account's plan tier is not exposed.
- Observed account-level usage for one window (2026-07-26 to 2026-08-25)
  was 108,660 credits: satellite segmentation 57,600 (4 calls), heatmap
  generation 33,760 (8), environment parameter analysis 8,700 (3),
  streetview segmentation 8,600 (1). This is recorded in
  [the issue 7 validation note](../research/issue-7-san-antonio-provider-validation.md).

The design consequence: **measure, never assume**. Every billable
submission is recorded, and credit truth comes only from the provider's own
account endpoint.

## The ledger

`data/ledger.jsonl` (gitignored) is an append-only JSONL log loaded at
startup, with two record kinds:

- **Call records** — one per submitted provider call: activity ID, endpoint,
  `credits_used` (null when the provider did not price it), completion
  time, status, and core/enrichment scope.
- **Reconciliation records** — the provider's authoritative account credit
  total for a date window, appended by `scripts/reconcile_ledger.py` from
  `POST /v1/system/fetch-api-key-custom-usage`.

Reload is idempotent (deduplication by activity ID and window).

## Why budgets count calls, not credits

The usage endpoint's breakdown is aggregated by activity name with no
activity IDs, so per-call credit attribution is impossible. A budget
expressed in credits would therefore be unenforceable. `FORTYGUARD_CALL_BUDGET`
caps the **call count** — the one thing the application can measure exactly —
and reconciliation supplies the credit facts afterwards. When the budget is
unset, the ledger records without enforcing (record-only mode).

Optional enrichment has a separate per-UTC-calendar-day budget
(`FORTYGUARD_ENRICHMENT_CALL_BUDGET`): one submitted enrichment activity
consumes one unit even if it later fails, while cache hits and fixture
replay consume none. The per-kind "estimated credits" values surfaced in
enrichment responses are declared estimates, not attributed usage.

## What spending looks like in practice

- **Public deployment and CI: zero.** Fixture replay makes no provider
  requests; automated checks run with `ALLOW_LIVE=false`.
- **Acquisition: bounded and explicit.** Maintainer-run scripts submit
  documented activities; the staged issue 23 plan was nine FortyGuard
  activities, resumable and ledger-recorded. Submit-once means a transport
  hiccup never silently double-bills.
- **Protected live deployment: capped.** A positive call budget and a
  persistent absolute ledger path are startup requirements; budget
  exhaustion is an HTTP 503 that is never converted into degradation.

## Free dependencies

OSRM (FOSSGIS pedestrian instance), Overpass, and OSM tiles are free public
services. They are treated carefully anyway — bounded queries, descriptive
User-Agents, HTTP 429 retry with delay, caching, and no CI dependency —
because they are shared resources that may throttle or fail
([proposal fact check](../research/proposal-fact-check.md)).
