import {
  ArrowRight,
  CalendarDays,
  Check,
  Clock3,
  Footprints,
  Route,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { MapContainer, Polyline, TileLayer } from "react-leaflet";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { useAppState } from "../../app/AppState";
import {
  DegradedNotice,
  LocationPicker,
  ProvenanceFooter,
  ResultProblem,
  ResultSkeleton,
} from "../../components/Shared";
import { dataClient } from "../../services/dataClient";
import type { ResultState } from "../../types";
import type {
  ApiProvenance,
  RouteComparisonResult,
  RouteOptionResult,
} from "../../types";

export function WalkLocationScreen() {
  const navigate = useNavigate();
  const { setWalkLocation } = useAppState();
  return (
    <LocationPicker
      title="Where would you like to walk?"
      description="Search the local demonstration places or choose a point directly on the map."
      onContinue={(location) => {
        setWalkLocation(location);
        navigate("/walk/date");
      }}
    />
  );
}

export function WalkDateScreen() {
  const navigate = useNavigate();
  const { walkLocation, walkDate, setWalkDate } = useAppState();
  if (!walkLocation) return <Navigate to="/walk/location" replace />;
  return (
    <section className="screen narrow-screen">
      <div className="screen-heading">
        <span className="step-label">Plan a walk</span>
        <h1>Choose a date</h1>
        <p>Hourly mock data will be matched to your selected place and date.</p>
      </div>
      <div className="form-panel">
        <div className="selected-summary">
          <span>Destination</span>
          <strong>{walkLocation.name}</strong>
          <small>{walkLocation.context}</small>
        </div>
        <label htmlFor="walk-date">
          <CalendarDays size={18} /> Visit date
        </label>
        <input
          id="walk-date"
          type="date"
          value={walkDate}
          onChange={(event) => setWalkDate(event.target.value)}
        />
        <button
          type="button"
          disabled={!walkDate}
          onClick={() => navigate("/walk/result")}
        >
          Analyze walking conditions <ArrowRight size={18} />
        </button>
      </div>
    </section>
  );
}

function useTripRequest() {
  const { walkLocation, walkDate, mode, trip, setTrip } = useAppState();
  const [status, setStatus] = useState<ResultState>(
    trip ? (mode === "degraded" ? "degraded" : "success") : "loading"
  );
  const load = useCallback(() => {
    if (!walkLocation || !walkDate) return;
    setStatus("loading");
    dataClient
      .analyzeTrip(walkLocation, walkDate, { mode })
      .then((value) => {
        setTrip(value);
        setStatus(mode === "degraded" ? "degraded" : "success");
      })
      .catch((error: Error & { code?: string }) => {
        setStatus(error.code === "EMPTY" ? "empty" : "error");
      });
  }, [walkLocation, walkDate, mode, setTrip]);
  useEffect(() => {
    if (!trip) load();
  }, [trip, load]);
  return { status, trip, load };
}

export function BestTimeScreen() {
  const { walkLocation, walkDate, tripAnalysis } = useAppState();
  const { status, trip, load } = useTripRequest();
  if (!walkLocation || !walkDate)
    return <Navigate to="/walk/location" replace />;
  return (
    <section className="screen result-screen">
      <div className="screen-heading compact">
        <span className="step-label">Best time result</span>
        <h1>{walkLocation.name}</h1>
        <p>{walkDate}</p>
      </div>
      {status === "loading" && <ResultSkeleton rows={4} />}
      {(status === "empty" || status === "error") && (
        <ResultProblem kind={status} onRetry={load} />
      )}
      {trip && (status === "success" || status === "degraded") && (
        <>
          {status === "degraded" && (
            <DegradedNotice>
              Some hourly observations have reduced confidence. The available
              series is still shown.
            </DegradedNotice>
          )}
          <article className="recommendation">
            <div>
              <span>Recommended window</span>
              <h2>{trip.recommendation.window}</h2>
              <p>{trip.recommendation.reason}</p>
            </div>
            <Clock3 size={30} />
          </article>
          <div className="metric-heading">
            <div>
              <span>Hourly series</span>
              <h2>{trip.metric.label}</h2>
            </div>
            <span className="metric-chip">
              {trip.metric.actualHeatIndex
                ? "NOAA Heat Index"
                : "Provider metric · not NOAA Heat Index"}
            </span>
          </div>
          <div
            className="hourly-chart"
            role="img"
            aria-label={`Hourly ${trip.metric.label} values`}
          >
            {trip.hourly.map((point) => (
              <div className="hour-column" key={point.hour}>
                <span
                  className={`bar ${point.comfort}`}
                  style={{
                    height: `${Math.max(30, (point.value - 20) * 9)}px`,
                  }}
                >
                  <b>{point.value}°</b>
                </span>
                <small>{point.hour}</small>
              </div>
            ))}
          </div>
          <div className="result-actions">
            <Link className="button-link" to="/walk/routes">
              Compare returned routes <Route size={18} />
            </Link>
          </div>
          <ProvenanceFooter value={trip.provenance.bestTime} />
        </>
      )}
      {tripAnalysis?.state === "success" && tripAnalysis.routes && (
        <div className="result-actions">
          <Link className="button-link" to="/walk/routes">
            Compare returned routes <Route size={18} />
          </Link>
        </div>
      )}
    </section>
  );
}

export function RouteComparisonScreen() {
  const { tripAnalysis } = useAppState();
  const routes = tripAnalysis?.routes;
  const [selected, setSelected] = useState(
    routes?.alternatives[0]?.identity ?? ""
  );
  if (!tripAnalysis || !routes) return <Navigate to="/" replace />;
  if (routes.alternatives.length === 0) {
    return <RouteUnavailable result={routes} />;
  }
  const active =
    routes.alternatives.find((route) => route.identity === selected) ??
    routes.alternatives[0];
  const limited =
    routes.route_set_state === "single_route" ||
    routes.confidence === "insufficient";
  return (
    <section className="screen result-screen">
      <div className="screen-heading compact">
        <span className="step-label">Route comparison</span>
        <h1>Compare returned alternatives</h1>
        <p>
          {routes.reason} We compare only the routes returned for this request,
          never every possible walking route.
        </p>
      </div>
      {limited && (
        <DegradedNotice>
          {routes.route_set_state === "single_route"
            ? "One returned route is usable, but there are no alternatives to compare."
            : "Coverage is limited, so this result should not be treated as a definitive ranking."}
        </DegradedNotice>
      )}
      {routes.alternatives.length > 1 && (
        <div className="decision-banner" role="status">
          {routes.decision_state === "shade_required" &&
            "Elevated heat was found. "}
          The recommendation is{" "}
          <strong>best among returned alternatives</strong>, not globally
          optimal. Shade is modeled from building data.
        </div>
      )}
      {routes.decision_state === "heat_unavailable" && (
        <DegradedNotice>
          Route heat is unavailable. Distances and durations are shown, but no
          route recommendation is made.
        </DegradedNotice>
      )}
      {routes.decision_state === "insufficient_shade_comparison_required" && (
        <DegradedNotice>
          Building-height coverage is weak, so no route is recommended. Compare
          the returned route trade-offs directly.
        </DegradedNotice>
      )}
      <div className="route-layout">
        <div className="route-map">
          <MapContainer
            center={leafletPoint(active.geometry?.[0] ?? [0, 0])}
            zoom={14}
            scrollWheelZoom
            className="map"
          >
            <TileLayer
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {routes.alternatives.map((route, index) => (
              <Polyline
                key={route.identity}
                positions={(route.geometry ?? []).map(leafletPoint)}
                pathOptions={{
                  color:
                    route.identity === active.identity
                      ? "#b9472f"
                      : ["#237064", "#cf922d", "#67727a"][index],
                  weight: route.identity === active.identity ? 7 : 4,
                  opacity: route.identity === active.identity ? 1 : 0.72,
                }}
                eventHandlers={{ click: () => setSelected(route.identity) }}
              />
            ))}
          </MapContainer>
        </div>
        <div className="route-list">
          {routes.alternatives.map((route, index) => (
            <button
              type="button"
              key={route.identity}
              className={`route-card ${route.identity === active.identity ? "active" : ""}`}
              onClick={() => setSelected(route.identity)}
            >
              <span className="route-index">{index + 1}</span>
              <span>
                <strong>{route.identity}</strong>
                <small>
                  {(route.distance_m / 1000).toFixed(2)} km ·{" "}
                  {Math.round(route.duration_s / 60)} min
                </small>
                <small>{heatLabel(route)}</small>
                <small>
                  {route.modeled_shade_percent === null
                    ? "Modeled shade unavailable"
                    : `${route.modeled_shade_percent}% modeled shade`}
                </small>
                <small>{coverageLabel(route, routes)}</small>
              </span>
              {route.identity === active.identity && (
                <Check size={18} aria-label="Selected" />
              )}
            </button>
          ))}
        </div>
      </div>
      <article className="route-detail">
        <div>
          <span>Modeled shade estimate</span>
          <strong>
            {active.modeled_shade_percent === null
              ? "Unavailable"
              : `${active.modeled_shade_percent}%`}
          </strong>
          <small>
            Modeled estimate based on building data, not measured real-world
            shade.
          </small>
        </div>
        <div>
          <span>Route evidence</span>
          <strong>
            {active.recommended
              ? "Recommended"
              : active.heat_status === "elevated"
                ? "Elevated heat"
                : "Returned alternative"}
          </strong>
          <small>{active.recommendation_reason ?? routes.reason}</small>
        </div>
        <Link className="button-link" to={`/walk/routes/${active.identity}`}>
          View route details <ArrowRight size={17} />
        </Link>
      </article>
      <ProvenanceFooter value={toProvenance(routes.provenance, routes)} />
    </section>
  );
}

export function SelectedRouteScreen() {
  const { tripAnalysis } = useAppState();
  const { routeId } = useParams();
  const route = tripAnalysis?.routes?.alternatives.find(
    (candidate) => candidate.identity === routeId
  );
  if (!route) return <Navigate to="/walk/routes" replace />;
  const selectedRoute = route;
  const [enrichment, setEnrichment] = useState<Awaited<
    ReturnType<typeof dataClient.requestEnrichment>
  > | null>(null);
  const [loadingKind, setLoadingKind] = useState<
    "satellite_canopy" | "street_view" | null
  >(null);
  async function load(kind: "satellite_canopy" | "street_view") {
    const token = tripAnalysis?.result_set_token;
    if (!token) return;
    setLoadingKind(kind);
    try {
      setEnrichment(
        await dataClient.requestEnrichment(kind, selectedRoute.identity, token)
      );
    } catch (error) {
      setEnrichment({
        status: "success",
        kind,
        target_id: selectedRoute.identity,
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
    <section className="screen narrow-screen">
      <div className="screen-heading">
        <span className="step-label">Selected route</span>
        <h1>{route.identity}</h1>
        <p>
          {(route.distance_m / 1000).toFixed(2)} km · about{" "}
          {Math.round(route.duration_s / 60)} minutes
        </p>
      </div>
      <div className="route-summary">
        <Footprints size={26} />
        <div>
          <strong>
            {route.modeled_shade_percent === null
              ? "Modeled shade unavailable"
              : `${route.modeled_shade_percent}% modeled shade estimate`}
          </strong>
          <p>
            Based on building data and limited to the returned route
            alternatives.
          </p>
        </div>
      </div>
      <p className="route-geometry-note">
        Turn-by-turn directions are not included in this analysis response. The
        full returned route geometry is shown on the comparison map.
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
            onClick={() => load("satellite_canopy")}
            disabled={!tripAnalysis?.result_set_token || loadingKind !== null}
          >
            {loadingKind === "satellite_canopy"
              ? "Loading canopy..."
              : "Load canopy context"}
          </button>{" "}
          <button
            type="button"
            onClick={() => load("street_view")}
            disabled={!tripAnalysis?.result_set_token || loadingKind !== null}
          >
            {loadingKind === "street_view"
              ? "Loading street view..."
              : "Load street view"}
          </button>
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
      <Link className="text-link" to="/walk/routes">
        Return to route comparison
      </Link>
    </section>
  );
}

function leafletPoint(point: [number, number]): [number, number] {
  return [point[1], point[0]];
}

function heatLabel(route: RouteOptionResult) {
  if (route.heat_value === null) return "Heat unavailable";
  return `${route.heat_value.toFixed(1)} °C · ${route.heat_status === "elevated" ? "Elevated heat" : "Mild heat"}`;
}

function coverageLabel(
  route: RouteOptionResult,
  comparison: RouteComparisonResult
) {
  const coverage =
    route.heat_coverage ?? route.building_coverage ?? comparison.coverage;
  return `Coverage ${Math.round(coverage * 100)}% · ${comparison.confidence} confidence`;
}

function toProvenance(value: ApiProvenance, comparison: RouteComparisonResult) {
  return {
    source: value.source === "fixture" ? "fixture" : "provider",
    dataDate: value.data_date,
    confidence: comparison.confidence,
    coverage: `${Math.round(comparison.coverage * 100)}% route coverage`,
    note: "Comparison is limited to returned alternatives. Shade is modeled from building data.",
  } as const;
}

function RouteUnavailable({ result }: { result: RouteComparisonResult }) {
  return (
    <section className="screen result-screen">
      <div className="screen-heading compact">
        <span className="step-label">Route comparison</span>
        <h1>No suitable returned route</h1>
        <p>
          {result.reason}. No route was fabricated and no global optimum is
          implied.
        </p>
      </div>
      <Link className="button-link" to="/">
        Return to trip setup
      </Link>
    </section>
  );
}
