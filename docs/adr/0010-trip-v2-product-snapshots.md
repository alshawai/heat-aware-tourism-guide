# ADR 0010: Trip v2 product snapshots from normalized acquisitions

Date: 2026-08-30
Status: Accepted

## Context

Issue #23 completes the offline full-flow fixture boundary. A trip fixture must
represent a complete product response, while its provider inputs remain
auditable and reusable. The canonical trip also exposed two important truth
constraints: the corrected Menger Hotel to The Alamo request genuinely returns
one route, and the provider environment response uses `GMT-7` where the
product's canonical interpretation is `America/Chicago`. Neither fact may be
repaired by inventing route or temporal evidence.

The existing v1 trip shape cannot represent the modern route states, nullable
recommendations, separate provenance, exact or inconsistent temporal evidence,
or structured whole-trip unavailability. Raw-provider acquisition and fixture
truth rules remain those in ADR 0004; this ADR records the derived product
snapshot boundary rather than superseding those rules.

## Decision

Define `trip-contract-v2` as the complete product snapshot schema. Product
snapshots are generated offline from normalized lower-level acquisitions and
validated through the production domain orchestration. The generator performs
an encode/decode round trip and uses rollback-safe pair replacement for the
snapshot and sidecar. It does not claim filesystem-level crash atomicity.
There is no hand-authored recommendation output: recommendations and degraded
states are computed, while intentionally injected product failures are labeled
as synthesized.

Use one strict shared v2 encoder/decoder for product snapshots, live responses,
fixture responses, and HTTP serialization. The decoder rejects unknown or
malformed contract fields and preserves complete success, degraded, and
unavailable states. v1 compatibility is not provided; the semantic contract is
breaking and repository-owned snapshots can be regenerated.

Each snapshot sidecar is an `AcquisitionRecord` with provider identity and
content-addressed `derived_from` links to its lower-level inputs. Provider
acquisitions retain their provider, retrieval, status, configuration version,
and safe activity metadata. Synthesized product sections and failure states
retain synthesized identity and do not receive fabricated retrieval times or
activity IDs. A provider observation remains provider truth; a computed or
demo value remains explicitly synthesized.

The fixture adapter receives an explicit ordered set of snapshot paths and
matches only the authoritative sidecar request configuration. No match is an
explicit unavailable result. More than one match is a hard duplicate error;
names and filenames are not selection identity.

The generator has a fixed four-case matrix:

- Canonical: Menger Hotel (`way/23727574`) to The Alamo (`way/129152944`).
- Single route: Main Plaza (`way/93118472`) to Historic Market Square (El
  Mercado) (`way/79636475`).
- Weak height and optional enrichment failure: San Fernando Cathedral
  (`way/80647022`) to Spanish Governor's Palace (`way/78601534`).
- Whole-trip core failure: Briscoe Western Art Museum (`way/337650172`) to
  Tower of the Americas (`way/78485919`).

Route comparison is limited to genuine routes returned by the configured
provider. The corrected canonical acquisition is one route, so the canonical
snapshot is genuinely one-route and degraded for limited comparison; it does
not preserve the former fabricated second route. Multi-route comparison is
demonstrated by Cathedral, whose two returned routes and route distances remain
genuine. No route or provider data is fabricated. Cathedral's route and height
evidence is genuine, but its heat evidence is synthesized demo evidence because
exact provider coverage was not established. Main Plaza alternate heat and
other non-routing sections are likewise synthesized and labeled demo evidence;
the Market Square no-feature result is intentionally not committed.

The canonical snapshot preserves the valid `34.0147 C` destination TCM value
for 2024-07-15 and the recovered environment result. Its `GMT-7` versus
`America/Chicago` mismatch is temporal-inconsistent evidence: the snapshot is
complete because best time, hotels, and routes are all present, but degraded and
hour-only rather than claiming an exact local instant. The three canonical
hotel component acquisitions are valid. Their `00:00-05:00` and `10:00-17:00`
windows are declared metadata; date-level TCM is not an interval maximum.

The snapshot generator validates input content hashes, refuses to overwrite
existing snapshot or sidecar pairs unless explicitly requested, and is
offline-only. Regeneration is required when inputs or product policy change.
The committed four-scenario backend and E2E coverage run with network access
blocked and must continue to use the same codec and selection rules.

## Alternatives considered

### Extend `trip-contract-v1`

Rejected because v1 requires legacy route and heat fields and cannot truthfully
encode nullable recommendations, separate evidence, degraded states, or
structured unavailability. Keeping v1 compatibility would preserve the wrong
semantic contract without a concrete external consumer requirement.

### Replay-time full orchestration

Rejected because replay would require coordinating every lower-level provider
fixture and would make offline behavior depend on unfinished live-flow
orchestration. A generated, validated product snapshot is the stable replay
boundary; its content-addressed inputs preserve auditability.

### Fabricated route or provider data

Rejected because route cardinality, heat values, and provider status are
observations or explicit synthesized demo states, not interchangeable fixture
content. In particular, no second canonical route is invented, Cathedral heat
is not relabeled as provider data, and Briscoe failure is not presented as
geographic provider coverage evidence.

## Consequences

- Offline replay returns complete modern product states without rerunning all
  provider orchestration.
- Live, fixture, and HTTP paths share one strict schema boundary, reducing
  parity drift and making regeneration failures visible.
- Sidecar hashes provide an auditable provenance graph from product snapshots
  to normalized acquisitions; ADR 0004 remains authoritative for raw-provider
  acquisition and degradation semantics.
- The four snapshots can be complete while degraded, so completeness no longer
  implies exact temporal or route-comparison evidence.
- Product snapshots are repository-owned generated artifacts and must be
  regenerated, hash-checked, and reviewed when inputs or decision policy change.
- Inventory validation detects missing or malformed pair members after a
  crash-level interruption; pair replacement is rollback-safe for write-time
  failures only.
- The public offline matrix demonstrates honest provider and synthesis labels,
  but it does not establish provider coverage where no exact acquisition was
  made.
