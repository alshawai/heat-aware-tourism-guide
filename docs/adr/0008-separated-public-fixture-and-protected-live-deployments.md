# ADR 0008: Separated public fixture and protected live deployments

Date: 2026-08-30
Status: Accepted

## Context

The application has a browser-facing demonstration and a maintainer-only live
integration. Publishing one process that can make live provider calls would
make an accidental request, credential exposure, or an unbounded request path
capable of spending the team's finite provider balance. The public demo also
needs to fit a small free hosting instance and remain useful when providers or
networking are unavailable.

## Decision

Deploy the public demonstration as a separate, single-worker fixture service.
Its explicit profile is `public-fixture`, and it has `ALLOW_LIVE=false`. The
service contains committed fixtures and the built React application, and does
not receive provider secrets. The public service is named
`heat-aware-tourism-guide-demo` and is provisioned on Render's free Docker
service in Ohio.

Provision live execution separately in the future as a paid service with a
persistent disk for the finite call ledger. It uses one worker and one instance;
its process-local cache is intentionally not durable. Live access is HTTP Basic
protected on every application route except `/health`, rather than a
user-selectable public request mode, and provider credentials are server-side
secrets only. The live service
must retain an explicit profile and a finite budget enforced by the persistent
ledger.

Render is the selected deployment provider because its Blueprint can describe
the Docker build, health check, region, free public service, and deploy-after-
checks behavior in-repository. The public service is intentionally stateless;
no disk is attached to the free demo. If a deploy fails or the demo becomes
unreliable, roll back to the last known-good image or commit and use the local
fixture flow as the recording fallback. Do not turn on live mode to repair a
public deployment.

## Consequences

- Public requests cannot consume FortyGuard credits or require provider
  availability.
- The Docker image carries both the frontend and fixtures, so one web process
  serves the complete demo.
- Free-tier sleep and limited memory make this suitable for demonstration, not
  production live traffic.
- A protected live deployment has extra cost and operational work, including a
  paid instance, disk backups/retention, secret management, and rollback.
- HTTP Basic protects the whole live service boundary; it is not a substitute
  for application-level authorization if the live service later gains users.
