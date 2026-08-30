import type { BestTimeResult, HourlyConcernProfile } from "../../types";
import { formatClockHour } from "./format";
import { isOverridableHour } from "./timeWindow";

type ConcernLevel = "high" | "elevated" | "clear" | "unknown";

/**
 * Colour band for one hour, taken from the server's own concern counts.
 *
 * No threshold is invented here: the environmental concern profile has already
 * compared every reported parameter against its declared NOAA, EPA,
 * physiological, or product threshold.
 */
function concernLevel(profile: HourlyConcernProfile | undefined): ConcernLevel {
  if (!profile) return "unknown";
  if (profile.high_count > 0) return "high";
  if (profile.elevated_count > 0) return "elevated";
  return "clear";
}

function concernSummary(profile: HourlyConcernProfile | undefined): string {
  if (!profile) return "no environmental profile reported";
  return `${profile.high_count} high, ${profile.elevated_count} elevated, ${profile.not_reported_count} not reported`;
}

function HourBar({ height, level }: { height: number; level: ConcernLevel }) {
  return (
    <svg
      className={`hour-bar ${level}`}
      viewBox="0 0 20 100"
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="2" y={100 - height} width="16" height={height} rx="3" />
    </svg>
  );
}

/**
 * The hourly thermal series as an interactive bar chart.
 *
 * Bars come from the baseline analysis only. Selecting an hour does not change
 * the chart's own data — it asks the screen to re-analyze the trip for that one
 * hour, which is a billable call, so the screen keeps the confirmation step.
 */
export function HourlyHeatChart({
  result,
  selectedHour,
  onSelectHour,
  interactive = true,
  busy = false,
}: {
  result: BestTimeResult;
  selectedHour: number;
  onSelectHour: (hour: number) => void;
  interactive?: boolean;
  busy?: boolean;
}) {
  const values = result.hourly.map((entry) => entry.metric.value);
  const lowest = Math.min(...values);
  const highest = Math.max(...values);
  const span = highest - lowest;
  const metricName =
    result.metric_label === "noaa_heat_index"
      ? "NOAA Heat Index"
      : "provider temperature metric";
  const profiles = new Map(
    (result.environmental_concerns ?? []).map((profile) => [
      profile.hour,
      profile,
    ])
  );

  // An empty series is a real backend outcome, not an error: it is reported
  // rather than drawn as a chart with no bars.
  if (result.hourly.length === 0) {
    return (
      <section className="hourly-chart-panel" aria-label="Hourly heat by hour">
        <h3>Hourly heat</h3>
        <p role="status">
          No hourly series was returned for this window, so hours cannot be
          compared or re-analyzed.
        </p>
      </section>
    );
  }

  return (
    <section className="hourly-chart-panel" aria-label="Hourly heat by hour">
      <header>
        <h3>Hourly heat</h3>
        <p>
          {metricName} in {result.hourly[0].metric.unit} for each hour in the
          analyzed window.
          {interactive
            ? " Choose another hour to re-analyze the walk for that hour."
            : " Hour selection is unavailable on the public demonstration."}
        </p>
      </header>
      <ol className="hourly-chart">
        {result.hourly.map((entry) => {
          const profile = profiles.get(entry.hour);
          const level = concernLevel(profile);
          // Guard a flat series: every hour would otherwise divide by zero.
          const height =
            span > 0 ? 12 + (88 * (entry.metric.value - lowest)) / span : 50;
          const recommended = entry.hour === result.recommendation_hour;
          const selected = entry.hour === selectedHour;
          const label = `${formatClockHour(entry.hour)}, ${entry.metric.value.toFixed(1)} ${entry.metric.unit}, ${concernSummary(profile)}${
            recommended ? ", recommended hour" : ""
          }`;
          const body = (
            <>
              <HourBar height={height} level={level} />
              <span className="hour-value">
                {entry.metric.value.toFixed(1)}
              </span>
              <span className="hour-label">{formatClockHour(entry.hour)}</span>
              {/* One flag row per column: the recommended hour is labelled
                  "Best", and an overridden hour says which one is on screen, so
                  a two- or three-hour series still shows what was chosen. */}
              {recommended ? (
                <span className="hour-flag">Best</span>
              ) : selected ? (
                <span className="hour-flag shown">Shown</span>
              ) : null}
            </>
          );
          const className = `hour-column ${level}${selected ? " selected" : ""}${
            recommended ? " recommended" : ""
          }`;
          return (
            <li key={entry.hour}>
              {interactive ? (
                <button
                  type="button"
                  className={className}
                  aria-pressed={selected}
                  aria-label={label}
                  disabled={busy || !isOverridableHour(entry.hour)}
                  onClick={() => onSelectHour(entry.hour)}
                >
                  {body}
                </button>
              ) : (
                <div className={className} aria-label={label}>
                  {body}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      <ul className="chart-legend" aria-label="Hour colour key">
        <li className="clear">No reported concern</li>
        <li className="elevated">Elevated concern</li>
        <li className="high">High concern</li>
        <li className="unknown">Not reported</li>
      </ul>
    </section>
  );
}
