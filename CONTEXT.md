# CONTEXT — Heat-Aware Tourism Guide

Single-context repository. This file is the shared vocabulary for issues,
ADRs, code, and tests. Domain decisions live in `docs/adr/`.

## What this product is

A San Antonio tourism guide that ranks hotels, compares walking routes, and
recommends visit times using urban-heat data. The FastAPI server owns all
provider credentials and external calls; the frontend never calls providers
directly.

## Glossary

- **Canonical trip** — The validated demonstration journey from Menger Hotel
  to The Alamo, with hotel decisions scoped to Downtown San Antonio / Alamo
  Plaza. Synonyms to avoid: "default walk", "demo location".
- **Trip setup** — The traveler-selected inputs shared by the best-time, hotel,
  and route decisions for one trip. It is one setup, not separate walk and
  hotel configurations.
- **Curated trip** — A trip whose places are fixed to the canonical trip while
  the traveler may choose its date, same-day time window, and guidance
  preference. An **exploratory trip** permits place selection and is outside
  the curated flow.
- **Cautious guidance** — An optional traveler preference requesting the
  product's more conservative heat interpretation. The interpretation policy
  belongs to the heat-classification domain; trip setup only captures the
  preference. Synonym to avoid: "cautious mode".
- **Trip analysis request** — One product-level request containing a complete
  trip setup. Its temporal-preparation stage asks the server for one ranged
  point heatmap followed by one identically ranged env-params series; later
  issues consume that series for best-time, hotel, and route decisions. It is
  not a collection of traveler-visible provider requests.
- **Supported live-data geography** — The United States, the geographic area
  in which the product may request live provider data. This is distinct from
  the canonical trip's San Antonio location and from fixture replay.
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
- **Temperature anchor** — The °C value required by the
  environmental-parameters request. Direct env-params callers supply it; the
  temporal trip pipeline derives it conservatively as the maximum TCM value
  in the traveler's range. The returned series is fixed to this anchor and is
  never a real 24-hour forecast; results carry the standing warning.
- **Env-params series** — Environmental parameters normalized as per-hour
  entries (`valid_time`, nullable metric values) aligned with the provider's
  `metadata.timestamps`. Missing values stay `None`, never zero. The best-time
  decision reuses this series without another provider request.
- **Environmental concern profile** — The per-hour assessment of all requested
  provider parameters against declared NOAA, EPA, physiological, and product
  thresholds. Missing parameters are reported as `not_reported`, never assumed
  safe, and do not count against an hour during best-time selection.
- **Framing threshold** — The product-declared 35°C threshold used for
  exceedance and persistence heatmap calls. It is visible in provenance with
  its `above` direction and is not presented as a NOAA boundary.
- **Submit-once** — The billable-submission rule: one POST per
  `submit_and_poll`; transient failures are retried as status GETs only
  (ADR 0003). Transport retries never resubmit billable work.
- **Coverage** — Reported fraction of a requested AOI actually covered by
  returned tiles (polygon joins use a projected CRS and report coverage;
  point lookups distinguish containing tile / boundary / outside-AOI /
  fallback). Weak coverage is surfaced, never hidden.
- **Credit ledger** — Append-only log of billable provider activity;
  `plan_optional` is separate from actual spend. Persists as JSONL
  (`data/ledger.jsonl`), loaded at startup, holding two record kinds:
  **call records** (one per completed provider call, keyed by activity ID,
  `credits_used` null when the provider did not price it) and
  **reconciliation records** (authoritative account credit totals for a date
  window). The optional `FORTYGUARD_CALL_BUDGET` enforces an all-time **call
  count** before each call (record-only when unset) — the enforced unit is
  calls, because the provider prices per account window, not per call. Budget
  windowing belongs to issue #22 (ADR 0004 §5).
- **Reconciliation** — Appending the provider's authoritative credit total for
  a date window to the ledger, via `scripts/reconcile_ledger.py` querying
  `/v1/system/fetch-api-key-custom-usage`. The only trustworthy source of
  credit cost; the breakdown is aggregated by activity name with no activity
  IDs, so per-call credit attribution is impossible (ADR 0004 §5).
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
- **OSM object identity** — The immutable pair of OpenStreetMap object type
  (`node`, `way`, or `relation`) and numeric ID. Hotel candidates preserve all
  contributing object identities after a confirmed merge; a name or location
  is not an object identity.
- **Usable hotel** — A discovered `tourism=hotel` object or confirmed merged
  group with a nonblank name and valid WGS84 node coordinates or way/relation
  center. Fewer than five usable hotels is explicitly unavailable, not an
  empty success.
- **Conservative hotel deduplication** — Hotel objects merge on identical OSM
  identity, compatible explicit relation membership, or a normalized name
  corroborated by matching address, website, or operator. Proximity and name
  alone never establish identity.
- **Route alternative** — One valid pedestrian route returned by the configured
  routing provider for the trip endpoints. The product compares only returned
  alternatives; it never fabricates a missing route or claims global optimality.
- **Shared route heat AOI** — One buffered bounding rectangle covering every
  returned route alternative when any alternative exceeds the representative
  distance threshold. One TCM activity covers the AOI; each route's heat is
  then calculated locally from the shared normalized tiles.
- **Route heat** — The conservative maximum TCM value intersecting one returned
  route at the best-time recommendation hour. It is never an average. When all
  returned routes are at or below the representative distance threshold, they
  reuse the retained landmark TCM value instead of starting another activity.
- **Route heat gate** — The heat-policy interpretation applied to route heat.
  Mild heat recommends the shortest returned route without shade work;
  elevated heat defers the final recommendation until modeled shade is
  available. Cautious guidance uses the same one-band-earlier policy as other
  heat decisions.
- **Modeled building shade** — A deterministic OSM-based estimate of the
  fraction of a returned route's length intersecting projected building-shadow
  geometry at the exact recommended local timestamp while the sun is above the
  horizon. It is not measured real-world shade and does not include trees,
  awnings, clouds, or temporary obstructions.
- **Building height quality** — The origin of a usable OSM building height:
  `explicit` from a valid `height` tag, `inferred_levels` from valid
  `building:levels` multiplied by the product approximation of 3 m per level,
  or `unknown`. A valid explicit height takes precedence.
- **Building-height coverage** — The area-weighted fraction of relevant OSM
  building and `building:part` footprints in a returned route's analysis
  corridor that have explicit or inferred heights. A route with no mapped
  building footprints has zero coverage. The configurable 0.70 sufficiency
  default is product policy, not an OSM or scientific standard.
- **Nighttime route decision** — The final elevated-heat decision when solar
  elevation is at or below the horizon. Building shade is zero and not
  applicable; the coolest returned route by retained route TCM is recommended,
  with distance used only to break equal-temperature ties.
- **Insufficient shade comparison** — The explicit daytime state when modeled
  building-shade evidence is weak or uncomputable. All returned alternatives
  and available metrics remain visible, but the product makes no route
  recommendation; the traveler compares the trade-offs.
- **No suitable returned route** — The explicit state when the routing provider
  returns no valid pedestrian routes, or when every returned route lacks enough
  evidence for a recommendation. A single valid route is instead shown as the
  only returned route with limited-comparison wording.
- **Source of truth for provider behavior** — The official FortyGuard docs
  (reconciled in `docs/research/issue-7-san-antonio-provider-validation.md`
  and ADR 0001), with the quickstart repo as reference only.

## Pointers

- ADR 0001 — live provider adapter boundary, sync submit/poll model, wiring.
- ADR 0002 — unit/freshness inference and transformation stamping.
- ADR 0003 — bounded polling, 404 tolerance window, submit-once.
- ADR 0004 — fixture acquisition sidecars, cache identity, degradation
  chain, JSONL cost ledger.
- ADR 0005 — best-time decision orchestration and retained route-gating evidence.
- ADR 0006 — returned-route heat AOI, conservative per-route aggregation, and
  recommendation staging.
- ADR 0007 — exact-time modeled shade, nighttime route decisions, and weak
  shade-evidence behavior.
- `docs/design/fortyguard-extraction.md` — extraction contract from issue #6.
- Layout: `app/domain/` (pure contracts), `app/services/` (cache, execution,
  acquisition, sidecars, ledger store), `app/integrations/fortyguard/`
  (provider client stack + live adapter), `app/api.py` + `app/main.py` +
  `app/settings.py` (composition root).
