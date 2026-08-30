# How To Acquire Fixtures

Fixture acquisition is the explicit, maintainer-run process that turns real
provider responses into committed, replayable fixtures. Real credits are
spent on the FortyGuard paths. This guide covers the acquisition script, the
trip snapshot generator, and credit reconciliation. The design contract —
sidecars as the single match identity, the degradation chain, and the ledger
— is [ADR 0004](../adr/0004-fixture-cache-provenance-ledger.md); the Issue
#23 outcome, including hashes and network-blocked test coverage, is recorded
in
[the issue 23 fixture schema note](../research/issue-23-fixture-schema.md).

Before acquiring anything, read
[How to configure live mode](configure-live-mode.md): FortyGuard acquisition
requires `ALLOW_LIVE=true` and `FORTYGUARD_API_KEY` in the maintainer
environment.

## What a fixture is

Every fixture is a pair:

- `<stem>.json` — the sanitized raw provider payload (API keys, request IDs,
  and credit fields stripped).
- `<stem>.acquisition.json` — the acquisition sidecar, the authoritative
  record: `source` (`provider` or `synthesized`), provider identity,
  endpoint, `request_configuration` (the matching identity), retrieval time,
  data date, status, schema version, provider configuration version, safe
  activity ID, and transformations.

Two rules keep the set honest:

1. A `provider` sidecar must carry a real retrieval time, provider identity,
   and terminal status. A `synthesized` sidecar must carry `null` activity
   ID and retrieval time — never fabricated ones.
2. Provider payloads are observed, product failure states are synthesized,
   and product recommendations are computed. None of the three may be
   relabeled as another.

`tests/test_fixture_inventory.py` enforces these rules, the one-sidecar-per-
fixture invariant, exact `derived_from` content hashes, and a secret scan
over every committed fixture.

## Acquire one provider scenario

`scripts/acquire_fixture.py` runs one documented provider request, proves it
normalizes through the live pipeline, and writes the fixture pair:

```bash
# FortyGuard heatmaps (billable: requires ALLOW_LIVE=true + API key)
python scripts/acquire_fixture.py --scenario tcm-historical
python scripts/acquire_fixture.py --scenario tcm-forecast
python scripts/acquire_fixture.py --scenario exceedance-historical
python scripts/acquire_fixture.py --scenario env-params-anchor35

# OSRM routes (free; no ALLOW_LIVE required)
python scripts/acquire_fixture.py --scenario canonical-menger-alamo
python scripts/acquire_fixture.py --scenario main-plaza-market-square
python scripts/acquire_fixture.py --scenario cathedral-governors-palace

# Overpass buildings (free; requires the matching OSRM fixture first)
python scripts/acquire_fixture.py --scenario cathedral-governors-palace-buildings
```

Useful flags:

- `--out-dir` — output directory (default `fixtures/acquired` for single
  scenarios; the issue 23 modes write to `fixtures/providers/...`).
- `--ledger-path` — override `FORTYGUARD_LEDGER_PATH` for this run.

Behaviour to expect:

- The script **refuses to overwrite** an existing fixture pair; move the old
  files aside deliberately instead of clobbering history.
- The buildings scenario enforces a per-route building-height coverage gate
  and requires the referenced OSRM fixture to exist.
- FortyGuard calls are appended to the ledger and obey `FORTYGUARD_CALL_BUDGET`.
- Prints output paths, the activity ID, and the ledger call count.

## Run the staged issue 23 plan

The Issue #23 acquisitions (canonical and alternate scenarios, data date
`2024-07-15`) are a staged, resumable plan of nine FortyGuard activities:
three destination TCMs, three destination env-params series, and three
canonical-district hotel components.

```bash
# Inspect the plan without spending credits (secret-free JSON)
python scripts/acquire_fixture.py --plan-issue-23

# Execute it
python scripts/acquire_fixture.py --execute-issue-23
```

Recovery modes exist for partial completion:
`--plan-issue-23-hotels-resume` / `--execute-issue-23-hotels-resume`
(the three independent hotel activities) and
`--plan-issue-23-canonical-env-recovery` /
`--execute-issue-23-canonical-env-recovery --activity-id <id>`
(status-only recovery of a prior env-params activity; guarded so it cannot
change the ledger). The older `--*-canonical-resume` modes are superseded
and raise an error.

## Generate trip product snapshots

`fixtures/trips/*.trip.json` are product-level `trip-contract-v2` snapshots.
They are generated offline from the committed raw acquisitions — never
hand-authored — and linked to their inputs by content-addressed
`derived_from` references:

```bash
python scripts/generate_trip_snapshots.py
```

The generator SHA-256-verifies all pinned inputs, builds the four scenarios
(canonical, Main Plaza to Market Square, Cathedral to Governor's Palace,
Briscoe to Tower unavailable) through production domain code with a fixed
clock, round-trips each response through the strict shared codec, and
refuses to overwrite existing outputs unless `--overwrite` is passed.

If any input changed, regeneration is mandatory: a snapshot silently claiming
stale inputs fails the hash checks in
`tests/test_fixture_inventory.py`.

## Reconcile credits afterwards

Acquisition records calls; only the provider's account endpoint reports
credit truth. After an acquisition session, append a reconciliation record:

```bash
python scripts/reconcile_ledger.py --start 2026-08-01 --end 2026-08-30
```

The breakdown is aggregated by activity name with no activity IDs, so
per-call credit attribution is impossible by design (ADR 0004 §5). See
[Cost model](../explanation/cost-model.md).

## Committing rules

1. Commit the fixture and its sidecar together, never one without the other.
2. Never edit a `provider` fixture in place; if the request identity must
   change, acquire a new fixture. Synthesized fixtures may be corrected in
   place when the correction is documented.
3. Never commit secrets. The inventory test scans committed JSON for
   key-shaped keys and `fg_`/`sk_`/Bearer/JWT value prefixes.
4. Keep filenames descriptive but remember they are **not** matching
   identity; the sidecar `request_configuration` is.
5. Update `docs/research/issue-23-alternate-scenarios.md` or a new research
   note when a scenario's observed facts change.
