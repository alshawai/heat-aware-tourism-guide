# ADR 0003: Bounded polling and post-submit 404 tolerance

Date: 2026-08-27
Status: Accepted

## Context

The FortyGuard heatmap and environmental-parameters jobs are asynchronous:
submission returns an activity id, and the result is polled from
`GET /v1/status/{activity_id}`. The documentation states 404 can mean
"Activity not found **or temporarily unavailable immediately after
submission**", and their example code polls at 5 s intervals for up to ~10
minutes. The current implementation tolerates exactly one 404 and uses
defaults of 12 polls × 1 s with a 15 s transport timeout.

Issue #10's acceptance criteria: brief post-submit status 404s are tolerated,
while polling and retries remain bounded; transport retries are separate from
billable task resubmission.

## Decision

1. **404-tolerance window.** A 404 status response is non-terminal (counted
   against the poll budget, no resubmission) while the activity is still
   "early": the first `status_404_grace_checks` status checks (default 3) or
   until any non-404 status response is seen, whichever comes first. After the
   window, a 404 is a terminal classified VALIDATION error ("activity not
   found"). This matches the documented "immediately after submission"
   semantics without misclassifying a genuinely bad activity id as a timeout.
2. **Bounds are settings-driven with defaults** interval 5.0 s (docs example;
   avoids rate-limit hammering), max_polls 24 (~2 min overall bound),
   transport timeout 30 s. All three are overridable via
   `FortyGuardPollingSettings`.
3. **Transport retries are separate from task resubmission.** The submit-once
   rule is absolute: the client performs exactly one POST per
   `submit_and_poll` call; no transport-level retry may ever reissue a POST.
   Transient status-lookup failures (408/429/5xx) consume poll budget and are
   retried by the poller as GETs only. Billable resubmission would require an
   explicit future idempotency strategy.
4. **The same bounds and policy apply to heatmap and env-params jobs** — one
   poller, one policy.

## Consequences

- `poll_activity`'s signature gains `status_404_grace_checks` (default 3);
  existing single-404 tolerance tests are subsumed by the window.
- Worst-case request latency in live mode is bounded at ~2 min before the
  execution layer falls back to cache or raises the classified error.
- Rate-limit responses during polling never loop faster than the interval.

## Alternatives considered

- Keeping exactly-one-404 tolerance: rejected — the docs describe an
  availability window, not a single occurrence; jobs observed live took longer
  than one check to appear.
- Unbounded 404 tolerance until overall timeout (quickstart behavior):
  rejected — wastes the budget and reports timeouts for nonexistent
  activities.
- Polling shorter than 5 s: rejected — risks 429s; docs example uses 5 s.
