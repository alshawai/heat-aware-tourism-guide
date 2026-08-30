# Documentation

This documentation follows the [Diátaxis](https://diataxis.fr/) structure:
tutorials (learning-oriented), how-to guides (task-oriented), reference
(information-oriented), and explanation (understanding-oriented).

## Tutorials

- [From clone to first fixture-backed run](tutorials/first-run.md) — start
  here.

## How-to guides

- [Configure live provider execution](how-to/configure-live-mode.md)
- [Acquire fixtures](how-to/acquire-fixtures.md)
- [Deploy the public fixture demo](how-to/deploy.md)
- [Record the demo](how-to/record-the-demo.md)

## Reference

- [Environment variables](reference/environment-variables.md)
- [HTTP API](reference/api.md)
- [Domain schemas](reference/domain-schemas.md)
- [Commands](reference/commands.md)
- [Configuration options](reference/configuration.md)

## Explanation

- [Architecture and ADR index](explanation/architecture.md)
- [Cost model](explanation/cost-model.md)
- [Heat metrics](explanation/heat-metrics.md)
- [Hotel weights](explanation/hotel-weights.md)
- [Shade assumptions](explanation/shade-assumptions.md)
- [Limitations](explanation/limitations.md)

## Design, research, and decisions

- [Product design document](design/design-doc.md) — the implementation
  source of truth.
- [ADR index](explanation/architecture.md#adr-index) — numbered
  architecture decision records under `docs/adr/`.
- [Research notes](research/) — externally verifiable facts and their
  citations: [proposal fact check](research/proposal-fact-check.md),
  [San Antonio provider validation](research/issue-7-san-antonio-provider-validation.md),
  [canonical coordinates](research/issue-40-menger-alamo-coordinates.md),
  [alternate scenarios](research/issue-23-alternate-scenarios.md),
  [fixture schema](research/issue-23-fixture-schema.md), and
  [lidar/shade feasibility](research/lidar-dsm-shade-feasibility-austin-san-antonio.md).
- [Demo script](demo-script.md) — narration and fallback handling for the
  submission recording.
- [`CONTEXT.md`](../CONTEXT.md) — the shared domain vocabulary.
