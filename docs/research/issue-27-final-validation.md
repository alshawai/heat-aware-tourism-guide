# Issue #27 Final Validation Record

**Validation date:** 2026-08-30
**Scope:** release hardening for the fixture-backed public demonstration

This record separates repeatable repository checks from maintainer-only
operations. Automated product checks explicitly run with `ALLOW_LIVE=false`.

## Automated Evidence

| Check                                           | Result | Evidence                                                   |
| ----------------------------------------------- | ------ | ---------------------------------------------------------- |
| Python formatting, lint, typing, and unit tests | Pass   | Repository Python quality commands                         |
| Python integration and fixture inventory        | Pass   | `npm run python:test:integration`                          |
| Frontend quality checks and build               | Pass   | Frontend format, lint, typecheck, test, and build commands |
| Fixture flow with networking disabled           | Pass   | `npm run e2e`; non-loopback requests are blocked           |
| Responsive smoke checks                         | Pass   | Playwright projects at 1280x720 and 375x812                |
| Source fixture date consistency                 | Pass   | UI and canonical fixture use `2024-07-15`                  |
| Tracked secret/generated-file audit             | Pass   | No secret or generated artifact is tracked                 |

The browser checks cover setup, best-time, hotel location/ranking, route
comparison, alternate routes, and explicit unavailable behavior. The local
fixture run is the fallback when the hosted service is asleep or alternate
scenes are needed.

## Deterministic Demo Rehearsal

The primary scenario is Menger Hotel to The Alamo in Downtown San Antonio, using
`2024-07-15` and 08:00-20:00. Run `npm run e2e` before recording, then follow
`docs/demo-script.md`; end on the restored canonical result. Do not claim that
a live provider call occurred during this fixture rehearsal.

## Maintainer-Only Checks

Live-provider validation, quota review, deployment smoke output, and the final
recording link require maintainer credentials or external services. Record those
separately without exposing secrets. Use `scripts/fortyguard_usage.py` for a
read-only quota review and verify `/health`, canonical fixture analysis, asset
loading, and live-mode rejection on the public URL.

### Observations on 2026-08-30

- The public `/health` endpoint returned HTTP 200 with `public-fixture`,
  `fixture`, and `fixture-only` declarations.
- Root HTML and its referenced JavaScript and CSS assets returned successfully.
- The public API returned the canonical `2024-07-15` fixture analysis and
  rejected an explicit live-mode request with HTTP 400.
- The deployed frontend still represented the pre-fix revision at validation
  time. Deploy this Issue #27 revision and repeat the canonical UI smoke test
  before recording.
- A read-only FortyGuard usage query for 2026-08-01 through 2026-08-30 reported
  149,540 credits used: 71,740 heatmap generation, 57,600 satellite
  segmentation, 11,600 environmental analysis, and 8,600 street-view
  segmentation credits. The endpoint does not report remaining balance or the
  account plan, and no persistent local ledger was available for attribution.
- No billable live activity was submitted in this validation pass. Historical
  authenticated provider observations remain recorded in the Issue #7 research
  note; a new billable call requires explicit spend approval.

## Submission Checklist

- [x] README, demo script, design document, research notes, and `.env.example`
      identify the same San Antonio fixture contract.
- [x] Current product text does not claim global optimality, mean corridor
      aggregation, empty success, or fabricated routes.
- [x] No tracked generated files or secrets remain.
- [ ] Maintainer records live validation, quota review, deployment smoke output,
      and recording link when required for submission.
