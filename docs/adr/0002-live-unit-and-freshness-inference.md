# ADR 0002: Live unit and freshness inference

Date: 2026-08-27
Status: Accepted

## Context

The official FortyGuard documentation (extracted from the docs SPA bundle,
2026-08) documents no machine-readable unit field for heatmap `tcm` tiles
(°C appears only in prose) and no freshness metadata of any kind — no
`valid_time`, generation timestamp, or data-date field — in the heatmap result
schema. Issue #6's decision rule is "do not encode an undocumented assumption."
Yet live heatmap data is required to flow through the shared contract, which
makes units and valid time explicit per tile.

By contrast, environmental-parameters results do carry time metadata
(`metadata.timestamps`, `time_range`, `timezone`), and their units are embedded
in the parameter names (`heat_index_celsius`, ...).

Issue #9's contract promised a "transformation/version" field, but `Provenance`
has none. The live adapter must also transform requests (point → AOI
expansion) and responses (envelope unwrap, shape translation).

## Decision

1. **Inference is permitted only when grounded in documentation, and every
   inference is stamped as a structured transformation in `Provenance`.**
   `Provenance` gains `transformations: tuple[Transformation, ...]` where
   `Transformation` is a frozen dataclass `(name: str, version: int)`,
   serialized as `[{"name": ..., "version": ...}]` in API responses.
2. **Grounded inferences the live adapter stamps:**
   - `tcm_unit_celsius` — tcm tile values are °C per the docs' prose (the only
     documented statement); hour-based analytics carry `stats_data.units =
"hour"`.
   - `valid_time_from_request` — the heatmap result carries no freshness, so
     the requested `date_time` is used as the tile valid time. This is
     definitionally true for what we asked, though not provider-attested.
     Version 2 (point path) derives the hour from the requested window's start
     when one was submitted (`filter_type` 2), because the returned readings
     describe that window; full-day requests keep midnight. The area path stays
     at version 1 — it submits no window.
   - `point_to_aoi_expansion` — a point request was expanded to a square AOI
     before submission.
   - `live_envelope_unwrapped` — the documented `data` envelope was hoisted.
3. **Rule change = version bump.** If an inference rule changes (e.g. the
   provider adds a real unit field), the transformation's `version` increments;
   consumers and cache entries can distinguish data transformed under the old
   rule.
4. **Env-params freshness is read from the response, not inferred** — the
   documented `metadata.timestamps` are the per-entry valid times; units come
   from the fixed parameter names. Missing values (`null` / legacy `-999`) are
   preserved as `None`, never zero, per the documentation.
5. **The sanitized raw provider payload remains the debugging and contract-
   judging path** (fixture/cache), not logs. Normalized output carries only the
   stamps above.

## Consequences

- `Provenance` construction sites (fixture, live, cache replay) default to an
  empty transformation tuple; only the live adapter adds stamps.
- Live data is auditable: any consumer can see which values were inferred and
  under which rule version.
- If the provider later documents a real unit/freshness field, the adapter
  reads it and the corresponding transformation is retired with a version bump
  — a localized change.
- The `heat_index_celsius` series from env-params is always labeled with the
  caller-supplied temperature-anchor warning; it is never a real forecast.

## Alternatives considered

- Blocking live heatmap mode until the provider documents units/freshness:
  rejected — the inferences are documentation-grounded and stamped, and #10's
  acceptance criteria require server-side submission and polling now.
- Free-form transformation codes (plain strings): rejected — no versioning,
  cannot distinguish rule changes.
