# Explanation: Architecture

How the system is put together, and why. For step-by-step material see the
[tutorial](../tutorials/first-run.md) and the
[how-to guides](../how-to/); for exact interfaces see the
[reference pages](../reference/api.md). The authoritative decision record is
the [ADR index](#adr-index) below; the product design source of truth is
[the design document](../design/design-doc.md), and the shared vocabulary is
[`CONTEXT.md`](../../CONTEXT.md).

## One service, two execution paths

```text
React/Vite build ──> FastAPI static assets and API
                            │
                            ├─ fixture/live execution ─── provenance, cache, degradation
                            ├─ FortyGuard client ─────── submit-and-poll, bounded polling
                            ├─ OSRM client ───────────── one request, returned alternatives
                            ├─ Overpass acquisition ──── hotels, buildings
                            └─ local decisions ───────── heat policy, hotel ranking, shade
```

The FastAPI server owns all provider credentials and external calls; the
frontend never calls a provider directly and never receives an API key.
Deploying one service keeps the public demo simple and makes the fixture/live
boundary server-enforced rather than UI-enforced.

## Layered layout

- `app/domain/` — pure contracts and decisions: heat policy, hotel scoring,
  route decision state machine, provenance, tokens. No I/O; fully unit
  tested.
- `app/services/` — orchestration: execution (fixture/live/cache
  degradation), trip adapters, route analysis, shade, hotel discovery,
  enrichment, ledger store, sidecars, the trip-contract-v2 codec, and
  offline snapshot generation.
- `app/integrations/fortyguard/` — the provider client stack plus the live
  adapter (transport, polling, normalization, transformations).
- `app/api.py` + `app/main.py` + `app/wiring.py` + `app/settings.py` —
  composition root: settings, profile validation, route table, app assembly.

The seam that matters is the `TripAnalysisAdapter` protocol: fixture replay
and live execution implement the same contract, so every downstream decision
is provenance-agnostic and every result carries its execution mode.

## Execution modes, provenance, and degradation

Every result records where it came from: `fixture` (committed
provider-shape JSON, offline), `live` (`provider`, authenticated call), or
`cache` (replayed earlier result). There is no unmarked fourth case — an
empty success is impossible by contract.

When live execution fails, the degradation chain runs: exact cache entry →
matching fixture → explicit unavailable error. Replays keep their true data
date and are marked stale; a forecast-mode replay is date-relaxed but never
presented as a current forecast. Budget exhaustion is deliberately outside
the chain: it returns HTTP 503 rather than degrading, because silently
serving stale data to protect a budget would hide the budget state.

## Fixtures as first-class data

Fixtures are not test doubles bolted on; they are the public deployment's
data source and the CI substrate. Each fixture is a sanitized raw provider
payload plus an acquisition sidecar that is the single authoritative match
identity. Product-level snapshots (`trip-contract-v2`) are generated
offline from normalized lower-level acquisitions through production domain
code and are linked to their inputs by content hashes. This is why the
demo, the tests, and the judges' experience all exercise the same code
path.

## Why the decisions were made

The numbered decision records, newest last:

| ADR                                                                            | Decision                                                                                     |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| [0001](../adr/0001-live-provider-adapter-boundary.md)                          | Live provider adapter boundary: server owns credentials; sync submit/poll model.             |
| [0002](../adr/0002-live-unit-and-freshness-inference.md)                       | Unit and freshness inference, with named/versioned transformations stamped in provenance.    |
| [0003](../adr/0003-bounded-polling-and-404-tolerance.md)                       | Bounded polling, a 404 tolerance window after submission, and submit-once for billable work. |
| [0004](../adr/0004-fixture-cache-provenance-ledger.md)                         | Acquisition sidecars, cache identity, the degradation chain, and the JSONL cost ledger.      |
| [0005](../adr/0005-best-time-decision-orchestration.md)                        | Best-time decision orchestration and retained route-gating evidence.                         |
| [0006](../adr/0006-returned-route-heat-analysis.md)                            | Shared route-heat AOI, conservative per-route aggregation, recommendation staging.           |
| [0007](../adr/0007-exact-time-modeled-shade-decisions.md)                      | Exact-time modeled shade, nighttime decisions, weak shade-evidence behavior.                 |
| [0008](../adr/0008-optional-enrichment-budgets-and-boundaries.md)              | Optional enrichment budgets, signed result-set tokens, base-result preservation.             |
| [0009](../adr/0009-separated-public-fixture-and-protected-live-deployments.md) | Separated public fixture and protected live deployments.                                     |
| [0010](../adr/0010-trip-v2-product-snapshots.md)                               | Trip v2 product snapshots from normalized acquisitions.                                      |

## Where the boundaries are

- **Geography.** Live provider data is supported for the United States
  only, because that is FortyGuard's documented coverage. The canonical
  scenario is San Antonio; fixture replay has no geography.
- **Routing.** OSRM is consumed, not implemented. One request per trip; the
  product compares only returned alternatives and never claims global
  optimality.
- **Heat claims.** Provider `tcm` is never labeled as NOAA Heat Index; the
  product avoids calling any condition comfortable or safe.
- **Shade.** Building-shadow percentages are model outputs from OSM data,
  not measurements; weak evidence yields no recommendation instead of a
  guess.

These boundaries and the remaining known limitations are collected in
[Limitations](limitations.md).
