# ADR 0005: Best-time decision orchestration

Date: 2026-08-29
Status: Accepted

## Context

ADR 0001 established a series-only temporal preparation stage for issue #44.
Issue #14 consumes that foundation to make the traveler-facing best-time
decision. The decision needs the reusable TCM and environmental series plus two
optional daily-burden measures: exceedance and persistence above a declared
35°C product threshold.

## Decision

`TemporalTripAnalysisAdapter` now owns the complete live best-time stage. It
runs one ranged TCM request and one identically ranged environmental-parameters
request, then assesses all 17 requested parameters per available TCM hour. It
also runs one exceedance and one persistence request at 35°C in the `above`
direction. Framing failures are non-blocking. Environmental-series failure
produces an explicit TCM-only fallback whose concern profile marks all provider
parameters `not_reported`.

The adapter returns a degraded trip analysis with `best_time` populated while
hotel and route decisions remain absent. `BestTimeResult` retains hourly
evidence, environmental concern profiles, the selected hour's raw TCM value,
optional framing metrics, and provenance so route gating can reuse the evidence
without another landmark request.

This decision supersedes ADR 0001 section 8 only where that section limits the
temporal adapter to `series_ready` preparation and excludes the best-time
decision. Its request-window, anchor, cache, and submit-once rules remain in
force.

## Consequences

- The live best-time stage uses four provider activities when all data is
  available; exceedance and persistence are independently optional.
- Missing environmental data is visible rather than assumed safe.
- The API and frontend expose recommendation reason, metric, date, source,
  freshness, concerns, and framing context.
- Hotel and route work can consume `recommended_hour_tcm_celsius` and the
  retained concern profile without another landmark heatmap call.
