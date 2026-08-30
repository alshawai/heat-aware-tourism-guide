# Explanation: Hotel Weights

How the district hotel ranking is computed, what the weights mean, and what
they must never be presented as. Code: `app/domain/hotel_heat_score.py`;
per-request configuration is documented in the
[configuration reference](../reference/configuration.md).

## The strongest proof point

One district-level heat analysis ranks every hotel; hotel lookup,
percentiles, ties, and re-weighting are computed locally. Hotel count never
multiplies provider jobs — the billable work is the district heatmap set,
not per-hotel requests.

## Components and default weights

Four heat components are acquired per district (data date `2024-07-15` for
the committed fixtures):

| Component                                  | Unit  | Default weight |
| ------------------------------------------ | ----- | -------------- |
| Night heat (`00:00-05:00` declared window) | °C    | 35 %           |
| Hot hours (exceedance above 35 °C)         | hours | 25 %           |
| Persistence (longest run above 35 °C)      | hours | 20 %           |
| Day heat (`10:00-17:00` declared window)   | °C    | 20 %           |

Each hotel receives its component values through local point-in-tile
lookup, with assignment quality, tile resolution, distance, and coverage
recorded per component.

## What the score is

- Component values are converted to **candidate-relative percentiles**
  within the discovered set; the aggregate is a weighted sum of inverted
  percentiles, normalized per correlation group.
- Hotels are ranked with **tie groups** — equal aggregates share a rank —
  and the response exposes components, percentiles, tile resolution, and
  the weights used (`product defaults` or `custom`).
- Ranking requires at least five complete usable candidates; fewer is an
  explicit unavailable state, not an empty success.

## What the score is not

- **Not objective truth.** The 35/25/20/20 split is a provisional product
  default, not a scientific or satisfaction-derived value. No absolute
  "score out of 100" is presented as if it were measured.
- **Not indoor comfort.** The ranking concerns outdoor heat exposure around
  the hotel. Room quality, service, price, and season are out of scope, and
  hotel review sentiment was explicitly rejected as evidence because those
  factors confound it.
- **Not interval maxima.** The declared night/day windows are metadata over
  date-level TCM evidence; the
  `date_level_not_interval_maximum` caveat stays attached to results.

## Re-weighting

Travelers may adjust the four weights (they must stay non-negative and sum
to 1); the client re-ranks locally without another provider request, and
the API accepts the same `weights` object on
`POST /api/hotels/rank`. Sensitivity analysis of the defaults remains open
follow-up work; the research basis is collected in
[the proposal fact check](../research/proposal-fact-check.md).
