# Explanation: Heat Metrics

How the product turns temperatures into bands, decisions, and wording. The
code is `app/domain/heat_policy.py`; thresholds are fixed there rather than
configured. External facts are cited in
[the proposal fact check](../research/proposal-fact-check.md).

## Two metrics, never conflated

| Metric               | Source                | Meaning                                               |
| -------------------- | --------------------- | ----------------------------------------------------- |
| `tcm`                | FortyGuard heatmap    | Provider tile temperature in °C.                      |
| `heat_index_celsius` | FortyGuard env-params | Actual NOAA Heat Index, when the provider returns it. |

`tcm` is **not** a Heat Index and is never labeled as one. When an actual
Heat Index value is available it is preferred for NOAA classification; when
it is not, the UI shows the Celsius metric with a separately named product
band. The two band families below exist precisely so the labels cannot
collide.

## NOAA Heat Index bands (verified)

Boundaries 80 / 90 / 105 / 130 °F — approximately 26.7, 32.2, 40.6, and
54.4 °C — from [NWS Heat Index](https://www.weather.gov/safety/heat-index):

| Band            | Heat index    |
| --------------- | ------------- |
| Below caution   | below 26.7 °C |
| Caution         | 26.7-32.2 °C  |
| Extreme caution | 32.2-40.6 °C  |
| Danger          | 40.6-54.4 °C  |
| Extreme danger  | above 54.4 °C |

Heat Index assumes shady, light-wind conditions and is distinct from WBGT.
"Comfortable" is not an NOAA category, and the product never uses it.

## Product TCM bands (product policy)

Boundaries 30 / 35 / 40 °C, chosen by the team, not derived from any
standard:

| Band                           | TCM             |
| ------------------------------ | --------------- |
| Lower provider temperature     | below 30 °C     |
| Moderate provider temperature  | 30-35 °C        |
| Higher provider temperature    | 35-40 °C        |
| Very high provider temperature | 40 °C and above |

## Guidance policies

`classify_heat` assigns a band, then an action threshold:

- **Standard guidance** acts from the third band (Extreme caution for NOAA;
  Higher provider temperature for TCM).
- **Cautious guidance** — the optional traveler preference — shifts the
  action threshold one band earlier (Caution; Moderate). The measured value
  and the displayed observation band do not change; only the
  "action required" decision moves. `policy_applied` records which policy
  produced the decision.

This one-band-earlier shift is an explicit product safety policy informed
by general public-health guidance (heat-vulnerable groups include older
adults and people with chronic conditions, per
[NWS heat safety](https://www.weather.gov/safety/heat) and
[WHO](https://www.who.int/news-room/fact-sheets/detail/climate-change-heat-and-health)).
It is not a clinical risk assessment, collects no medical profile, and
provides no medical advice.

## Environmental concern thresholds

The best-time decision also assesses the returned environmental parameters
hour by hour against declared thresholds (`app/domain/best_time.py`):
heat index 26.7 / 40.6 °C, apparent temperature 30 / 40 °C, wet-bulb
28 / 32 °C, EPA AQI family 51 / 101, relative humidity 60 / 80 %,
precipitation 0.1 / 5.0 mm, and solar irradiance 400 / 600 W/m². Missing
parameters are reported as `not_reported`, never assumed safe, and do not
count against an hour during best-time selection.

## Framing metrics

Exceedance and persistence heatmaps summarize a district against a declared
threshold — 35 °C, direction above, in this product. They are framing
evidence visible in provenance, not hidden substitutes for the hourly
curve, and the 35 °C value is a product choice, not an NOAA boundary.

## Wording rules

Preferred phrasing: "no elevated heat concern detected by the selected
metric" and "more cautious guidance selected". Avoided phrasing: any claim
that a condition is comfortable, safe, or clinically assessed.
