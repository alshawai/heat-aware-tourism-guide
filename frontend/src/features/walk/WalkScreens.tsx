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
  const { walkLocation, walkDate } = useAppState();
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
    </section>
  );
}

export function RouteComparisonScreen() {
  const { trip, mode } = useAppState();
  const [selected, setSelected] = useState(trip?.routes[0]?.id ?? "");
  if (!trip) return <Navigate to="/walk/result" replace />;
  const degraded =
    mode === "degraded" ||
    trip.routes.length < 2 ||
    trip.provenance.routes.confidence === "Low";
  const active =
    trip.routes.find((route) => route.id === selected) ?? trip.routes[0];
  return (
    <section className="screen result-screen">
      <div className="screen-heading compact">
        <span className="step-label">Route comparison</span>
        <h1>Compare returned alternatives</h1>
        <p>
          The recommendation applies only to the routes returned for this
          request.
        </p>
      </div>
      {degraded && (
        <DegradedNotice>
          {trip.routes.length < 2
            ? "Only one route alternative was returned, so a comparison is not available."
            : "Building-height coverage lowers confidence in the modeled shade estimates."}
        </DegradedNotice>
      )}
      <div className="route-layout">
        <div className="route-map">
          <MapContainer
            center={[
              trip.location.latitude + 0.002,
              trip.location.longitude + 0.003,
            ]}
            zoom={14}
            scrollWheelZoom
            className="map"
          >
            <TileLayer
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {trip.routes.map((route, index) => (
              <Polyline
                key={route.id}
                positions={route.geometry}
                pathOptions={{
                  color:
                    route.id === active.id
                      ? "#b9472f"
                      : ["#237064", "#cf922d", "#67727a"][index],
                  weight: route.id === active.id ? 7 : 4,
                  opacity: route.id === active.id ? 1 : 0.72,
                }}
                eventHandlers={{ click: () => setSelected(route.id) }}
              />
            ))}
          </MapContainer>
        </div>
        <div className="route-list">
          {trip.routes.map((route, index) => (
            <button
              type="button"
              key={route.id}
              className={`route-card ${route.id === active.id ? "active" : ""}`}
              onClick={() => setSelected(route.id)}
            >
              <span className="route-index">{index + 1}</span>
              <span>
                <strong>{route.name}</strong>
                <small>
                  {(route.distanceMeters / 1000).toFixed(1)} km ·{" "}
                  {route.durationMinutes} min
                </small>
                <small>{route.heatStatus}</small>
              </span>
              {route.id === active.id && <Check size={18} />}
            </button>
          ))}
        </div>
      </div>
      <article className="route-detail">
        <div>
          <span>Modeled shade estimate</span>
          <strong>{active.shadePercent}%</strong>
          <small>
            Estimate based on building data, not measured real-world shade.
          </small>
        </div>
        <div>
          <span>Recommendation</span>
          <strong>
            {active.id === "route-2"
              ? "Best among returned alternatives"
              : "Selected route"}
          </strong>
          <small>{active.heatStatus}</small>
        </div>
        <Link className="button-link" to={`/walk/routes/${active.id}`}>
          View directions <ArrowRight size={17} />
        </Link>
      </article>
      <ProvenanceFooter value={trip.provenance.routes} />
    </section>
  );
}

export function SelectedRouteScreen() {
  const { trip } = useAppState();
  const { routeId } = useParams();
  if (!trip) return <Navigate to="/walk/result" replace />;
  const route = trip.routes.find((candidate) => candidate.id === routeId);
  if (!route) return <Navigate to="/walk/routes" replace />;
  return (
    <section className="screen narrow-screen">
      <div className="screen-heading">
        <span className="step-label">Selected route</span>
        <h1>{route.name}</h1>
        <p>
          {(route.distanceMeters / 1000).toFixed(1)} km · about{" "}
          {route.durationMinutes} minutes
        </p>
      </div>
      <div className="route-summary">
        <Footprints size={26} />
        <div>
          <strong>{route.shadePercent}% modeled shade estimate</strong>
          <p>
            Based on building data and limited to the returned route
            alternatives.
          </p>
        </div>
      </div>
      <ol className="directions">
        {route.steps.map((step, index) => (
          <li key={step}>
            <span>{index + 1}</span>
            <p>{step}</p>
          </li>
        ))}
      </ol>
      <Link className="text-link" to="/walk/routes">
        Return to route comparison
      </Link>
    </section>
  );
}
