import { Check } from "lucide-react";
import { Link } from "react-router-dom";
import type { RouteComparisonResult, RouteOptionResult } from "../../types";
import {
  formatDistanceAndDuration,
  formatPercent,
  heatLabel,
  heatMetricLabel,
  heatSourceLabel,
} from "./format";

function shadeLabel(route: RouteOptionResult) {
  return route.modeled_shade_percent === null
    ? "Modeled shade unavailable"
    : `${route.modeled_shade_percent.toFixed(0)}% modeled shade`;
}

/**
 * One returned route alternative: a scannable summary that links to the route
 * detail, with the full comparison evidence folded into a disclosure.
 *
 * Highlighting is driven by hover and focus so pointing at a card lights up its
 * line on the map, while the card's click goes where the traveler expects.
 */
export function RouteCard({
  route,
  index,
  comparison,
  selected,
  onHighlight,
}: {
  route: RouteOptionResult;
  index: number;
  comparison: RouteComparisonResult;
  selected: boolean;
  onHighlight: () => void;
}) {
  return (
    <article
      className={`route-card-item${route.recommended ? " recommended" : ""}${
        selected ? " selected" : ""
      }`}
    >
      <Link
        className="route-card"
        to={`/trip/routes/${encodeURIComponent(route.identity)}`}
        onMouseEnter={onHighlight}
        onFocus={onHighlight}
      >
        <span className="route-index">{index + 1}</span>
        <span className="route-card-body">
          <strong>
            {route.recommended ? "Recommended route" : "Alternative route"}
          </strong>
          <small>{route.identity}</small>
          <small>{formatDistanceAndDuration(route)}</small>
          <small>{heatLabel(route)}</small>
          <small>{shadeLabel(route)}</small>
        </span>
        {selected && <Check size={18} aria-label="Shown on map" />}
      </Link>

      <details className="evidence-disclosure">
        <summary>Route {index + 1} evidence</summary>
        <dl className="route-evidence-metrics">
          <div>
            <dt>Modeled shade</dt>
            <dd>
              {route.modeled_shade_percent === null
                ? "Unavailable"
                : `${route.modeled_shade_percent.toFixed(0)}%`}
            </dd>
          </div>
          <div>
            <dt>Building height coverage</dt>
            <dd>{formatPercent(route.building_coverage)}</dd>
          </div>
          <div>
            <dt>Shade confidence</dt>
            <dd>
              {route.shade_confidence?.replaceAll("_", " ") ?? "Unavailable"}
            </dd>
          </div>
          <div>
            <dt>Route heat</dt>
            <dd>
              {route.heat_value === null
                ? "Unavailable"
                : `${route.heat_value.toFixed(1)} °${route.heat_unit}`}
            </dd>
          </div>
          <div>
            <dt>Heat metric</dt>
            <dd>{heatMetricLabel(route.heat_metric)}</dd>
          </div>
          <div>
            <dt>Heat status</dt>
            <dd>
              {route.heat_status === null
                ? "Unavailable"
                : route.heat_status.replaceAll("_", " ")}
            </dd>
          </div>
          <div>
            <dt>Heat coverage</dt>
            <dd>
              {route.heat_coverage === null
                ? "Unavailable"
                : formatPercent(route.heat_coverage)}
            </dd>
          </div>
          <div>
            <dt>Heat source</dt>
            <dd>{heatSourceLabel(route.heat_source)}</dd>
          </div>
        </dl>
        <div className="building-quality" aria-label="Building height quality">
          <span>
            Explicit {formatPercent(route.building_explicit_fraction)}
          </span>
          <span>
            Inferred {formatPercent(route.building_inferred_levels_fraction)}
          </span>
          <span>Unknown {formatPercent(route.building_unknown_fraction)}</span>
        </div>
        <p className="building-counts">
          Footprints: {route.building_explicit_count} explicit,{" "}
          {route.building_inferred_levels_count} inferred from levels,{" "}
          {route.building_unknown_count} unknown,{" "}
          {route.dropped_building_geometry_count} dropped as unusable geometry.
        </p>
        <p className="route-geometry-count">
          {route.geometry === null
            ? "No route geometry was returned."
            : `${route.geometry.length} returned geometry points.`}
        </p>
        {route.shade_model_label && <p>{route.shade_model_label}</p>}
        {route.recommendation_reason && <p>{route.recommendation_reason}</p>}
        {!route.recommendation_reason && !route.recommended && (
          <p>{comparison.reason}</p>
        )}
        {route.shade_limitations.length > 0 && (
          <ul
            className="route-limitations"
            aria-label="Shade model limitations"
          >
            {route.shade_limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        )}
      </details>
    </article>
  );
}
