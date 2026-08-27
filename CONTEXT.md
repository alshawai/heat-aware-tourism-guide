# CONTEXT — Heat-Aware Tourism Guide

Single-context repository. This file is the shared vocabulary for issues,
ADRs, code, and tests. Domain decisions live in `docs/adr/`.

## What this product is

A San Antonio tourism guide that ranks hotels, compares walking routes, and
recommends visit times using urban-heat data. The FastAPI server owns all
provider credentials and external calls; the frontend never calls providers
directly.

## Glossary

- **Activity** — One asynchronous FortyGuard job. Submission returns an
  `activity_id`; the result is polled from `GET /v1/status/{activity_id}`.
  A heatmap activity is billable on completion. Synonyms to avoid: "task",
  "job".
- **Analytic type** — The heatmap metric requested: `tcm` (tile temperature,
  °C), `exceedance` (hours past a threshold), `persistence` (longest run of
  hours past a threshold). `threshold` + `direction` are required for the
  latter two and ignored by `tcm`.
- **Execution mode** — Where a result comes from: `fixture` (committed
  provider-shape JSON, offline), `live` (authenticated provider call through
  the live adapter), or `cache` (replayed earlier result). One of the three is
  always explicit in `Provenance.source`; never empty-success.
- **Provenance** — The record attached to every result: `source`
  (`fixture`/`provider`/`cache`), `retrieved_at`, `data_date`, `stale`,
  `forecast`, optional `activity_id`, sanitized `raw_payload`, and
  `transformations`.
- **Transformation** — A named, versioned inference or reshaping step applied
  on the live path (e.g. `tcm_unit_celsius`, `valid_time_from_request`,
  `point_to_aoi_expansion`, `live_envelope_unwrapped`). Recorded in
  `Provenance.transformations` per ADR 0002. Cache/fixture paths default to no
  transformations.
- **Tile** — One normalized heatmap cell: identity, geometry, metric
  (`analytic_type`), `value_celsius` (tcm) or `metric_value` + unit (`hours`),
  source, valid time, forecast flag, threshold/direction, activity id. The
  single internal heatmap shape for fixture and live data.
- **Temperature anchor** — The caller-supplied °C value required by the
  environmental-parameters request. The returned series is fixed to this
  anchor and is never a real 24-hour forecast; results carry the standing
  warning.
- **Env-params series** — Environmental parameters normalized as per-hour
  entries (`valid_time`, nullable metric values) aligned with the provider's
  `metadata.timestamps`. Missing values stay `None`, never zero.
- **Submit-once** — The billable-submission rule: one POST per
  `submit_and_poll`; transient failures are retried as status GETs only
  (ADR 0003). Transport retries never resubmit billable work.
- **Coverage** — Reported fraction of a requested AOI actually covered by
  returned tiles (polygon joins use a projected CRS and report coverage;
  point lookups distinguish containing tile / boundary / outside-AOI /
  fallback). Weak coverage is surfaced, never hidden.
- **Credit ledger** — Budget accounting for billable provider usage;
  `plan_optional` is separate from actual spend. Persists as JSONL
  (`data/ledger.jsonl`), loaded at startup with activity-ID dedupe; the
  optional `FORTYGUARD_CREDIT_BUDGET` enforces an all-time total (record-only
  when unset). Budget windowing belongs to issue #22 (ADR 0004).
- **Acquisition record** — The sidecar JSON (`<stem>.acquisition.json`) beside
  every committed fixture: source (`provider` or `synthesized`), endpoint,
  request configuration, retrieval time, data date, status, schema version,
  provider configuration version, safe activity ID, and transformations. The
  single authoritative fixture match identity (ADR 0004). Synthesized
  fixtures carry `null` activity IDs and retrieval times, never fabricated
  ones.
- **Provider configuration version** — The explicit constant
  (`fortyguard-config-v1`) naming the provider/request-construction semantics
  a response was produced under. Fourth component of cache identity alongside
  endpoint, schema version, and complete request payload (ADR 0004).
- **Degradation rule** — On a live-path failure the execution layer replays a
  matching cache entry (exact key), then a matching fixture (sidecar match;
  date-relaxed for forecast mode only), otherwise raises an explicit
  unavailable error. Every replay is labelled (`source="cache"/"fixture"`,
  `stale=True`, true data date) and never presented as a current forecast
  (ADR 0004).
- **Source of truth for provider behavior** — The official FortyGuard docs
  (reconciled in `docs/research/issue-7-san-antonio-provider-validation.md`
  and ADR 0001), with the quickstart repo as reference only.

## Pointers

- ADR 0001 — live provider adapter boundary, sync submit/poll model, wiring.
- ADR 0002 — unit/freshness inference and transformation stamping.
- ADR 0003 — bounded polling, 404 tolerance window, submit-once.
- ADR 0004 — fixture acquisition sidecars, cache identity, degradation
  chain, JSONL cost ledger.
- `docs/design/fortyguard-extraction.md` — extraction contract from issue #6.
- Layout: `app/domain/` (pure contracts), `app/services/` (cache, execution,
  acquisition, sidecars, ledger store), `app/integrations/fortyguard/`
  (provider client stack + live adapter), `app/api.py` + `app/main.py` +
  `app/settings.py` (composition root).
