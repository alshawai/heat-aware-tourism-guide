import type { HeatInterpretation } from "../../types";

/**
 * The heat band applied to a decision, with the metric it was derived from.
 *
 * A provider temperature metric is never presented as a NOAA Heat Index; when
 * the index is unavailable that is stated rather than implied.
 */
export function HeatPolicySummary({ value }: { value?: HeatInterpretation }) {
  if (!value) return null;
  return (
    <div className="heat-policy-summary">
      <strong>{value.band_label}</strong>
      <p>
        {!value.noaa_heat_index_available
          ? `${value.value_celsius === null ? "Selected Celsius metric unavailable" : `${value.value_celsius.toFixed(1)} °C provider temperature metric`} · NOAA Heat Index unavailable.`
          : `${value.value_celsius?.toFixed(1)} °C · NOAA Heat Index.`}
      </p>
      {value.guidance_policy === "cautious" && (
        <small>
          More cautious guidance selected; the action threshold is shifted one
          band earlier.
        </small>
      )}
    </div>
  );
}
