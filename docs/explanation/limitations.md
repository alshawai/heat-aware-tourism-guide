# Explanation: Limitations

What the product deliberately does not claim. This page is the honest
boundary of the submission; the acceptance language behind it is audited in
[the proposal fact check](../research/proposal-fact-check.md). Detailed
reasoning lives in the linked explanation pages and ADRs.

## Coverage and geography

- **Live data is United States-only**, because that is FortyGuard's
  documented current coverage. Requests outside the supported US extent get
  an explicit `unsupported_geography` unavailable response. This is a
  provider boundary, not a product choice to ignore other regions.
- **One validated city.** San Antonio, Texas is the primary scenario;
  Austin was the validated fallback. Multi-city support is out of scope.
- **Curated public flow.** The public deployment demonstrates the fixed
  canonical trip and hotel district; exploratory trips with live providers
  are a maintainer capability.

## Data recency and honesty

- **The public demo replays fixtures** acquired for the date `2024-07-15`
  (canonical window 08:00-20:00, alternates 10:00-17:00). Results are
  labelled `fixture` with their true data date and are not presented as
  current conditions.
- **The env-params series is anchored, not forecast.** Environmental
  parameters are fixed to a caller-supplied temperature anchor and carry
  the standing warning "not a real 24-hour forecast".
- **Heat evidence has known temporal caveats.** The canonical environment
  series' provider timezone (`GMT-7`) conflicts with the canonical
  `America/Chicago` interpretation, so the best-time recommendation is
  hour-only (`temporal_evidence: "inconsistent"`). Hotel night/day windows
  are declared metadata over date-level TCM, not interval maxima
  (`date_level_not_interval_maximum`).

## Routing

- **Only returned alternatives are compared.** OSRM alternatives are not
  guaranteed; the canonical request genuinely returned one route, which is
  shown with limited-comparison wording. The product never fabricates a
  route and never claims a route is globally optimal, shortest-possible, or
  the only one that exists.
- **Distances and durations are provider estimates**, not measured walks.

## Shade

- **Modeled, not measured.** Building-shadow percentages come from OSM
  footprints, inferred or explicit heights, and solar geometry; they
  exclude trees, awnings, terrain, clouds, and temporary obstructions. See
  [Shade assumptions](shade-assumptions.md).
- **Weak evidence yields no recommendation.** When building-height coverage
  is below the product's 0.70 policy threshold, all route evidence remains
  visible but nothing is recommended.

## Heat and safety

- **No medical claims.** The product is not a clinical risk assessment,
  collects no medical profile, and gives no medical advice. NOAA category
  names are used only for actual Heat Index values; provider `tcm` gets
  separately named product bands. Nothing is called "comfortable" or
  "safe"; preferred wording is "no elevated heat concern detected by the
  selected metric".
- **Thresholds are policy.** The 35 °C framing threshold, the 30/35/40 °C
  TCM bands, the 1,500 m representative-route distance, the 0.70 coverage
  gates, the one-band-earlier cautious shift, and the 35/25/20/20 hotel
  weights are team decisions, not standards. Sensitivity analysis of the
  hotel weights remains open work.

## Product scope

Out of scope by design: booking, pricing, availability, indoor hotel
comfort, a routing engine, city-wide optimal cool-route search, medical
risk scoring, treating segmentation imagery as the core shade measurement,
and any requirement that public deployment or CI make live provider calls.

## Operational limits

- The public demo runs on Render's free tier: it sleeps after 15 idle
  minutes (about one minute to wake) and is bounded by free-tier hours and
  bandwidth. Keep-warm layers mitigate but do not remove this; see
  [How to deploy](../how-to/deploy.md).
- The cache is process-local and lost on restart; the ledger is the only
  persistent operational record.
- Enrichment estimates are declared approximations; actual credit usage is
  knowable only through account-level reconciliation
  ([Cost model](cost-model.md)).
