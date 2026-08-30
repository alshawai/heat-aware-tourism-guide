import { AlertTriangle } from "lucide-react";
import type { BestTimeResult } from "../../types";
import { formatClockHour, formatMetric, formatParameterName } from "./format";

/**
 * The best-time recommendation and the evidence behind it.
 *
 * Every framing figure is gated on its own threshold being present, so an
 * unavailable threshold never turns into a bare number without its meaning.
 */
export function BestTimeSummary({ result }: { result: BestTimeResult }) {
  const configuration = result.provenance.request_configuration;
  const dataMode = configuration.forecast === true ? "forecast" : "historical";
  const source =
    result.provenance.source === "fixture"
      ? "Fixture replay"
      : result.provenance.source === "cache"
        ? "Cached data"
        : "Provider data";
  const freshness = result.provenance.fresh ? "fresh" : "stale";
  const selected = result.environmental_concerns?.find(
    (profile) => profile.hour === result.recommendation_hour
  );

  return (
    <section aria-label="Best visit time">
      <h3>Recommended visit: {formatClockHour(result.recommendation_hour)}</h3>
      <p>{result.recommendation_reason}</p>
      {result.temporal_evidence === "inconsistent" && (
        <p className="series-warning" role="note">
          <AlertTriangle size={17} />
          The provider timestamp is inconsistent with local time, so this is an
          hour-only recommendation.
        </p>
      )}
      <p>
        {source}, {dataMode}, {freshness}. Data date:{" "}
        {result.provenance.data_date}.
      </p>
      {result.exceedance_hours !== null &&
        result.framing_threshold_celsius !== null && (
          <p>
            {result.exceedance_hours.toFixed(1)} hours{" "}
            {result.framing_direction}{" "}
            {result.framing_threshold_celsius.toFixed(1)} °C.
          </p>
        )}
      {result.persistence_hours !== null &&
        result.framing_threshold_celsius !== null && (
          <p>
            Longest stretch {result.framing_direction}{" "}
            {result.framing_threshold_celsius.toFixed(1)} °C:{" "}
            {result.persistence_hours.toFixed(1)} hours.
          </p>
        )}
      {selected && (
        <p>
          Environmental profile: {selected.high_count} high,{" "}
          {selected.elevated_count} elevated, {selected.not_reported_count} not
          reported.
        </p>
      )}
      {result.environmental_concerns && (
        <details className="evidence-disclosure">
          <summary>Hourly best-time evidence</summary>
          <div className="series-table-wrap">
            <table className="series-table">
              <caption>Hourly best-time evidence</caption>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Thermal metric</th>
                  <th scope="col">Environmental concerns</th>
                </tr>
              </thead>
              <tbody>
                {result.environmental_concerns.map((profile) => (
                  <tr key={profile.hour}>
                    <th scope="row">{formatClockHour(profile.hour)}</th>
                    <td>
                      {profile.primary_thermal_value.toFixed(1)} °C{" "}
                      {profile.primary_thermal_metric === "tcm"
                        ? "provider TCM"
                        : "NOAA Heat Index"}
                    </td>
                    <td>
                      {profile.concerns
                        .filter((concern) => concern.concern_level !== "none")
                        .map(
                          (concern) =>
                            `${formatParameterName(concern.parameter)}: ${
                              concern.available
                                ? `${concern.concern_level} (${formatMetric(
                                    concern.value,
                                    concern.unit
                                  )})`
                                : "not reported by provider"
                            }`
                        )
                        .join("; ") || "None"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}
