import { Footprints } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { dataClient } from "../../services/dataClient";
import type {
  EnrichmentResponse,
  RouteComparisonResult,
  RouteOptionResult,
} from "../../types";
import {
  formatDistanceAndDuration,
  formatPercent,
  heatLabel,
  heatMetricLabel,
  heatSourceLabel,
} from "./format";
import { HeatPolicySummary } from "./HeatPolicySummary";
import { RouteMap } from "./RouteMap";

type OptionalKind = "satellite_canopy" | "street_view";

/**
 * Everything the analysis returned about one route alternative.
 *
 * Turn-by-turn steps are not part of the analysis response, so the dossier says
 * so instead of implying navigation it does not have. Optional canopy and
 * street-view context is informational only and cannot change the decision.
 */
export function RouteDossier({
  route,
  comparison,
  resultSetToken,
}: {
  route: RouteOptionResult;
  comparison: RouteComparisonResult;
  resultSetToken?: string;
}) {
  const [enrichment, setEnrichment] = useState<EnrichmentResponse | null>(null);
  const [loadingKind, setLoadingKind] = useState<OptionalKind | null>(null);

  async function load(kind: OptionalKind) {
    if (!resultSetToken) return;
    setLoadingKind(kind);
    try {
      setEnrichment(
        await dataClient.requestEnrichment(kind, route.identity, resultSetToken)
      );
    } catch (error) {
      // A failed optional call is reported as unavailable, never as missing.
      setEnrichment({
        status: "success",
        kind,
        target_id: route.identity,
        state: "unavailable",
        reason: error instanceof Error ? error.message : "request_failed",
        base_result: {},
        usage: { requested_calls: 0, completed_calls: 0 },
        provenance: null,
        limitations: [],
        payload: null,
      });
    } finally {
      setLoadingKind(null);
    }
  }

  return (
    <section className="screen route-dossier">
      <div className="screen-heading">
        <span className="step-label">Route detail</span>
        <h1>{route.identity}</h1>
        <p>
          {formatDistanceAndDuration(route)} ·{" "}
          {route.recommended ? "Recommended route" : "Alternative route"}
        </p>
      </div>

      <RouteMap
        routes={comparison}
        selectedId={route.identity}
        onSelect={() => undefined}
      />

      <div className="route-summary">
        <Footprints size={26} />
        <div>
          <strong>
            {route.modeled_shade_percent === null
              ? "Modeled shade unavailable"
              : `${route.modeled_shade_percent.toFixed(0)}% modeled shade estimate`}
          </strong>
          <p>
            Modeled from OSM building data at the analyzed hour and limited to
            the returned route alternatives.
          </p>
        </div>
      </div>

      <dl className="route-evidence-metrics">
        <div>
          <dt>Route heat</dt>
          <dd>{heatLabel(route)}</dd>
        </div>
        <div>
          <dt>Heat metric</dt>
          <dd>{heatMetricLabel(route.heat_metric)}</dd>
        </div>
        <div>
          <dt>Heat source</dt>
          <dd>{heatSourceLabel(route.heat_source)}</dd>
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
          <dt>Shade confidence</dt>
          <dd>
            {route.shade_confidence?.replaceAll("_", " ") ?? "Unavailable"}
          </dd>
        </div>
        <div>
          <dt>Building height coverage</dt>
          <dd>{formatPercent(route.building_coverage)}</dd>
        </div>
      </dl>

      <div className="building-quality" aria-label="Building height quality">
        <span>Explicit {formatPercent(route.building_explicit_fraction)}</span>
        <span>
          Inferred {formatPercent(route.building_inferred_levels_fraction)}
        </span>
        <span>Unknown {formatPercent(route.building_unknown_fraction)}</span>
      </div>

      <HeatPolicySummary value={route.heat_interpretation ?? undefined} />

      {route.recommendation_reason && <p>{route.recommendation_reason}</p>}
      {route.shade_model_label && <p>{route.shade_model_label}</p>}
      {route.shade_limitations.length > 0 && (
        <ul className="route-limitations" aria-label="Shade model limitations">
          {route.shade_limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      )}

      <p className="route-geometry-note">
        Turn-by-turn directions are not included in this analysis response. The
        full returned route geometry is drawn on the map above
        {route.geometry
          ? ` from ${route.geometry.length} returned points.`
          : "; no geometry was returned for this route."}
      </p>

      <article className="route-summary" aria-live="polite">
        <div>
          <strong>Optional route context</strong>
          <p>
            Premium context is informational only and cannot change this route
            decision.
          </p>
          <button
            type="button"
            onClick={() => void load("satellite_canopy")}
            disabled={!resultSetToken || loadingKind !== null}
          >
            {loadingKind === "satellite_canopy"
              ? "Loading canopy..."
              : "Load canopy context"}
          </button>{" "}
          <button
            type="button"
            onClick={() => void load("street_view")}
            disabled={!resultSetToken || loadingKind !== null}
          >
            {loadingKind === "street_view"
              ? "Loading street view..."
              : "Load street view"}
          </button>
          {!resultSetToken && (
            <p>
              Optional context is unavailable because this result set carries no
              token.
            </p>
          )}
          {enrichment && (
            <p>
              {enrichment.state === "available"
                ? "Optional context available."
                : `Unavailable: ${enrichment.reason}`}
            </p>
          )}
          {enrichment?.payload && (
            <pre>{JSON.stringify(enrichment.payload, null, 2)}</pre>
          )}
          {enrichment?.provenance && (
            <small>
              Source: {String(enrichment.provenance.source)} · Calls:{" "}
              {enrichment.usage.completed_calls}
            </small>
          )}
          {enrichment?.limitations.map((item) => (
            <small key={item}>{item}</small>
          ))}
        </div>
      </article>

      <Link className="text-link" to="/trip/results">
        Return to trip results
      </Link>
    </section>
  );
}
