# ADR 0004: Fixture acquisition, cache identity, degradation chain, and cost ledger

Date: 2026-08-28
Status: Accepted

## Context

Issue #11 requires that live validation produce deterministic offline fixtures
and that public/CI execution never depend on metered providers. Three gaps
existed after issues #6–#10:

1. **Cache identity was incomplete.** `CacheKey` hashed endpoint + schema
   version + request payload, but not the provider configuration that produced
   the response (ADR 0001 explicitly deferred cache-key policy to this issue).
2. **There was no acquisition path.** Fixtures were hand-synthesized; nothing
   recorded where a fixture came from, under which request configuration, or
   when. The design doc promised an acquisition script under `scripts/`; it did
   not exist. The issue-#7 lock ("do not acquire or commit live fixtures until
   the unit/valid-time and caller-anchor contracts are reconciled") was
   satisfied by ADR 0002 + #10's live adapters, unblocking real acquisition.
3. **Degradation and cost accounting were partial.** Live heatmap failure fell
   back to cache only; env-params had no cache or fallback at all; the
   `CreditLedger` existed and was tested but was never constructed in
   production wiring, and it evaporated on restart. Every HTTP failure was a
   400 `{"status": "unavailable"}`, conflating client errors with provider
   unavailability.

## Decision

### 1. Cache keys carry four identity components

`CacheKey.create(endpoint, schema_version, payload, provider_config_version)`
hashes the canonical JSON of all four. The provider configuration version is
an explicit constant (`fortyguard-config-v1`, owned by the integration layer),
bumped manually when provider behavior or request-construction semantics
change. It is not derived from settings (irrelevant settings would thrash
keys; relevant ones are already in the payload) nor from transformation
versions (fixture/cache paths carry none, per ADR 0002).

### 2. Acquisition records are per-fixture sidecar JSON files

Every committed fixture has a sidecar `<stem>.acquisition.json` holding an
`AcquisitionRecord`: `source` (`provider` for real acquisitions, `synthesized`
for hand-made fixtures), `endpoint`, `request_configuration`, `retrieved_at`,
`data_date`, `status`, `schema_version`, `provider_config_version`,
`activity_id`, and `transformations`. Records tell the truth: synthesized
fixtures carry `null` activity IDs and retrieval times, never fabricated ones.

The sidecar's `request_configuration` is the **single authoritative match
identity** for every fixture kind (heatmap internal-shape, heatmap raw-shape,
env-params, trip). Embedded `request`/`scenario` blocks in existing fixtures
remain as inert, mirrored data; loaders fall back to them only when a sidecar
is absent (temporary fixtures in tests).

### 3. Acquired fixtures are raw provider payloads replayed through the live pipeline

The acquisition script commits the sanitized raw provider result (post
envelope-hoisting, minus credit metadata), not the internal shape. Fixture
replay runs the identical `translate_heatmap_response` +
`normalize_heatmap_response` pipeline as the live path, so fixture/live
parity is structural and the replayed result carries the same transformation
stamps as live data (ADR 0002's "empty transformation tuple" default applies
to internal-shaped fixtures, which are already translated; raw replay
genuinely applies the transformations). Internal-shaped synthesized fixtures
are unchanged.

### 4. Degradation chain: live → cache → fixture → explicit unavailable

On live failure (heatmap and env-params alike) the execution layer:

1. replays a matching cache entry (exact four-component key, `source="cache"`,
   `stale=True`);
2. else replays a matching fixture (sidecar match; `source="fixture"`,
   `stale=True` on fallback, with the acquisition's true `retrieved_at`,
   `data_date`, and `activity_id` in provenance — never the fallback moment);
3. else raises `UnavailableError`, preserving the provider `error_kind` when
   the original failure was a `ProviderError`.

Forecast-mode fixtures match date-relaxed (analytic type, location,
threshold/direction/granularity, forecast flag — ignoring `start_date`) so a
committed forecast fixture stays replayable beyond its calendar date; every
such replay is `stale=True` with the fixture's true data date. Historical and
env-params matching stay strict: an anchored series or historical scenario for
a different date is wrong data, not degraded data. Cache fallback stays
exact-key only — the complete request payload is part of cache identity.
`BudgetExceededError` is never caught by the chain: overspend fails loud.

### 5. The cost ledger persists as JSONL and enforces an all-time budget

`FORTYGUARD_LEDGER_PATH` (default `data/ledger.jsonl`, gitignored; explicit
empty value selects in-memory only) names an append-only JSONL store loaded at
startup — reload is idempotent thanks to activity-ID dedupe, and loaded
records never trigger enforcement (they are facts that already happened; only
new records are checked). `FORTYGUARD_CREDIT_BUDGET` is optional: unset means
record-only (usage is still recorded — recording is unconditional whenever
live is enabled); set means all-time enforcement against loaded + session
records (a spend that would exceed the remaining budget raises
`BudgetExceededError` at record time, after the provider call, mapping to a
503 `budget_exceeded` response). Budget _windowing_ policy is deliberately out
of scope here and belongs to issue #22. The acquisition script appends to the
same ledger file. Account-level usage snapshots stay a script/utility concern,
not ledger entries.

### 6. HTTP failures split three ways

Client errors (bad body, invalid mode, out-of-contract request fields) return
400 `{"status": "error", "error": ...}`. Provider-side unavailability — the
degradation chain exhausted, provider errors, missing/misconfigured live
stack, fixture file errors — returns 503 `{"status": "unavailable", "error":
..., "error_kind": ...}`. Budget exhaustion returns 503 with
`error_kind: "budget_exceeded"`. Both the FastAPI app and the stdlib fixture
server implement the same split.

### 7. Committed data is gated by a secrets scan

A test loads every committed JSON under `fixtures/` and fails on secret-shaped
key names (`api-key`, `authorization`, `token`, `bearer`, `secret`) or
key-shaped values (provider key prefixes, `Bearer` tokens, JWT prefixes).
Runtime sanitization stays defense-in-depth; the test is the commit-time gate.

## Consequences

- CI/public runs replay committed fixtures deterministically; a live-keyed
  server degrades to labelled stale data instead of empty success.
- Every fixture is self-describing: origin, request identity, and freshness
  are machine-readable, and synthesized fixtures are honestly labelled.
- Cache entries written under one provider configuration version can never be
  replayed as hits under another.
- The budget is all-time: a deployment stays over budget until the ledger
  file is cleared; windowing arrives with #22.
- The canonical acquisition (one tcm-historical run) is triggered by the
  maintainer, not by CI — real credits are spent; the script appends honest
  usage records to the same ledger the app enforces.
