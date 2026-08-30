import { AlertTriangle, MapPinned, Sun } from "lucide-react";
import type { ApiProvenance, RouteComparisonResult } from "../../types";
import { decisionBadge, routeDecisionHeading } from "./decisionLabels";
import { RouteCard } from "./RouteCard";

function ProvenanceRow({
  label,
  value,
}: {
  label: string;
  value: ApiProvenance | null;
}) {
  if (!value) return null;
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {value.provider} · {value.source} · {value.data_date} ·{" "}
        {value.fresh ? "fresh" : "stale"}
      </dd>
    </div>
  );
}

/**
 * The returned walking-route alternatives and the decision made about them.
 *
 * The comparison is always framed as best among returned alternatives; no route
 * is invented and no global optimum is implied.
 */
export function RouteComparison({
  result,
  selectedId,
  onHighlight,
}: {
  result: RouteComparisonResult;
  selectedId: string;
  onHighlight: (identity: string) => void;
}) {
  if (result.route_set_state === "no_suitable_returned_route") {
    return (
      <section className="route-comparison" aria-label="Walking routes">
        <h3>Walking routes unavailable</h3>
        <p>{result.reason}</p>
        {result.fallback_reason && <p>{result.fallback_reason}</p>}
      </section>
    );
  }

  const badge = decisionBadge(result.decision_state);
  return (
    <section className="route-comparison" aria-label="Walking routes">
      <header className="route-comparison-heading">
        <MapPinned size={22} />
        <div>
          <h3>{routeDecisionHeading(result)}</h3>
          <p>{result.reason}</p>
          {badge && <span className="decision-badge">{badge}</span>}
        </div>
      </header>
      {result.decision_state === "insufficient_shade_comparison_required" && (
        <div className="route-evidence-warning">
          <AlertTriangle size={18} />
          <span>
            No route is recommended because shade evidence is incomplete.
          </span>
        </div>
      )}
      {result.route_set_state === "single_route" && (
        <div className="route-evidence-warning">
          <AlertTriangle size={18} />
          <span>
            One returned route is usable, so there are no alternatives to
            compare.
          </span>
        </div>
      )}
      <p className="shade-model-notice">
        <Sun size={17} />
        Modeled OSM building shade, not measured real-world shade. Trees,
        awnings, clouds, and temporary obstructions are excluded.
      </p>
      {result.alternatives.length === 0 ? (
        <p role="status">No walking route alternatives were returned.</p>
      ) : (
        <div className="route-evidence-list">
          {result.alternatives.map((route, index) => (
            <RouteCard
              key={route.identity}
              route={route}
              index={index}
              comparison={result}
              selected={route.identity === selectedId}
              onHighlight={() => onHighlight(route.identity)}
            />
          ))}
        </div>
      )}
      <footer className="route-set-footer">
        <p>
          Comparison scope: {result.comparison_scope}. Set coverage{" "}
          {Math.round(result.coverage * 100)}% route coverage ·{" "}
          {result.confidence} confidence.
        </p>
        {result.fallback_reason && <p>{result.fallback_reason}</p>}
        <details className="evidence-disclosure">
          <summary>Route data provenance</summary>
          <dl className="provenance-list">
            <ProvenanceRow label="Route set" value={result.provenance} />
            <ProvenanceRow label="Routing" value={result.routing_provenance} />
            <ProvenanceRow label="Route heat" value={result.heat_provenance} />
            <ProvenanceRow
              label="Buildings"
              value={result.building_provenance}
            />
            <ProvenanceRow
              label="Solar position"
              value={result.solar_provenance}
            />
          </dl>
        </details>
      </footer>
    </section>
  );
}
