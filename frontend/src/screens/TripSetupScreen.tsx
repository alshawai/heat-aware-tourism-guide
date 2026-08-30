import {
  AlertTriangle,
  CheckCircle2,
  Database,
  MapPinned,
  Radio,
  Sun,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  CircleMarker,
  MapContainer,
  TileLayer,
  useMapEvents,
} from "react-leaflet";
import { useAppState } from "../app/AppState";
import { fixtureScenarioFor } from "../features/trips/exploratoryScenarios";
import { dataClient } from "../services/dataClient";
import type {
  BestTimeResult,
  HealthResponse,
  HeatInterpretation,
  RouteComparisonResult,
  TripAnalysisRequest,
  LocationSelection,
} from "../types";

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const PUBLIC_FIXTURE_DATE = "2026-08-23";
const PUBLIC_FIXTURE_START_HOUR = 8;
const PUBLIC_FIXTURE_END_HOUR = 20;

type HealthState =
  | { status: "checking" | "unavailable" }
  | ({ status: "available" } & Omit<HealthResponse, "status">);
type RequestState = "idle" | "submitting" | "failed";

function EndpointMap({
  onSelect,
}: {
  onSelect: (point: LocationSelection) => void;
}) {
  useMapEvents({
    click(event) {
      onSelect({
        id: `map-${event.latlng.lat}-${event.latlng.lng}`,
        name: "Map selection",
        context: "Selected directly on the map",
        latitude: event.latlng.lat,
        longitude: event.latlng.lng,
      });
    },
  });
  return null;
}

function validDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value
  );
}

function formatMetric(value: number | null, unit?: string) {
  return value === null
    ? "Unavailable"
    : `${value.toFixed(1)}${unit ? ` ${unit}` : ""}`;
}

function formatHour(validTime: string, timezone: string) {
  return `${validTime.slice(11, 16)} ${timezone}`;
}

function formatParameterName(name: string) {
  return name
    .replaceAll("_", " ")
    .replaceAll(":", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function parameterUnit(name: string) {
  if (name.includes("humidity") || name.includes("cloud_cover")) return "%";
  if (name.includes("precipitation")) return "mm";
  if (name.includes("irradiance")) return "W/m2";
  if (name.includes("elevation")) return "m";
  if (name.includes("index") || name.includes("temperature")) return "C";
  return "";
}

function BestTimeSummary({ result }: { result: BestTimeResult }) {
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
      <h3>
        Recommended visit: {String(result.recommendation_hour).padStart(2, "0")}
        :00
      </h3>
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
                  <th scope="row">
                    {String(profile.hour).padStart(2, "0")}:00
                  </th>
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
      )}
    </section>
  );
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function routeDecisionHeading(result: RouteComparisonResult) {
  switch (result.decision_state) {
    case "shade_shadiest_recommended":
      return "Shadiest route recommended";
    case "shade_only_route_recommended":
      return "Only route recommended";
    case "nighttime_coolest_recommended":
      return "Coolest nighttime route recommended";
    case "mild_shortest_recommended":
      return "Shortest route recommended";
    case "insufficient_shade_comparison_required":
      return "Compare route trade-offs";
    case "shade_required":
      return "Shade analysis required";
    case "heat_unavailable":
      return "Route heat unavailable";
    default:
      return "Walking routes";
  }
}

function RouteComparison({ result }: { result: RouteComparisonResult }) {
  if (result.route_set_state === "no_suitable_returned_route") {
    return (
      <section className="route-comparison" aria-label="Walking routes">
        <h3>Walking routes unavailable</h3>
        <p>{result.reason}</p>
      </section>
    );
  }

  return (
    <section className="route-comparison" aria-label="Walking routes">
      <header className="route-comparison-heading">
        <MapPinned size={22} />
        <div>
          <h3>{routeDecisionHeading(result)}</h3>
          <p>{result.reason}</p>
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
        <div className="route-evidence-warning" role="note">
          <AlertTriangle size={18} />
          <span>
            One returned route is usable, but there are no alternatives to
            compare.
          </span>
        </div>
      )}
      <p className="shade-model-notice">
        <Sun size={17} />
        Modeled OSM building shade, not measured real-world shade. Trees,
        awnings, clouds, and temporary obstructions are excluded.
      </p>
      <div className="route-evidence-list">
        {result.alternatives.map((route, index) => (
          <article
            className={`route-evidence-row${route.recommended ? " recommended" : ""}`}
            key={route.identity}
          >
            <div className="route-evidence-title">
              <span>Route {index + 1}</span>
              <h4>
                {route.recommended ? "Recommended route" : "Alternative route"}
              </h4>
              <small>
                {(route.distance_m / 1000).toFixed(2)} km ·{" "}
                {Math.round(route.duration_s / 60)} min
              </small>
            </div>
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
                  {route.shade_confidence?.replaceAll("_", " ") ??
                    "Unavailable"}
                </dd>
              </div>
              <div>
                <dt>Route heat</dt>
                <dd>
                  {route.heat_value === null
                    ? "Unavailable"
                    : `${route.heat_value.toFixed(1)} °C`}
                </dd>
              </div>
            </dl>
            <div
              className="building-quality"
              aria-label="Building height quality"
            >
              <span>
                Explicit {formatPercent(route.building_explicit_fraction)}
              </span>
              <span>
                Inferred{" "}
                {formatPercent(route.building_inferred_levels_fraction)}
              </span>
              <span>
                Unknown {formatPercent(route.building_unknown_fraction)}
              </span>
            </div>
            {route.recommendation_reason && (
              <p>{route.recommendation_reason}</p>
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
          </article>
        ))}
      </div>
    </section>
  );
}

export function TripSetupScreen() {
  const {
    curatedTripSetup,
    setCuratedTripSetup,
    tripAnalysis,
    setTripAnalysis,
  } = useAppState();
  const [tripMode, setTripMode] = useState<"curated" | "exploratory">(
    "curated"
  );
  const [exploratoryTripSetup, setExploratoryTripSetup] =
    useState(curatedTripSetup);
  const tripSetup =
    tripMode === "curated" ? curatedTripSetup : exploratoryTripSetup;
  const setTripSetup =
    tripMode === "curated" ? setCuratedTripSetup : setExploratoryTripSetup;
  const { date, startHour, endHour, cautious } = tripSetup;
  const [origin, setOrigin] = useState<LocationSelection>({
    id: "menger",
    name: "Menger Hotel",
    context: "San Antonio, TX",
    latitude: 29.4245914,
    longitude: -98.4864288,
  });
  const [destination, setDestination] = useState<LocationSelection>({
    id: "alamo",
    name: "The Alamo",
    context: "San Antonio, TX",
    latitude: 29.425833,
    longitude: -98.485833,
  });
  const [activeEndpoint, setActiveEndpoint] = useState<
    "origin" | "destination"
  >("origin");
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<LocationSelection[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "error">(
    "idle"
  );
  const [dateError, setDateError] = useState("");
  const [startError, setStartError] = useState("");
  const [endError, setEndError] = useState("");
  const [endpointError, setEndpointError] = useState("");
  const [health, setHealth] = useState<HealthState>({ status: "checking" });
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const dateRef = useRef<HTMLInputElement>(null);
  const startRef = useRef<HTMLSelectElement>(null);
  const endRef = useRef<HTMLSelectElement>(null);

  async function checkHealth(signal?: AbortSignal) {
    setHealth({ status: "checking" });
    try {
      const value = await dataClient.getHealth({ signal });
      setHealth({
        status: "available",
        deployment_profile: value.deployment_profile,
        mode: value.mode,
        execution_capability: value.execution_capability,
      });
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setHealth({ status: "unavailable" });
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void checkHealth(controller.signal);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (
      health.status === "available" &&
      tripAnalysis &&
      tripAnalysis.execution_mode !== health.mode
    ) {
      setTripAnalysis(null);
    }
  }, [health, setTripAnalysis, tripAnalysis]);

  function clearOutcome() {
    setTripAnalysis(null);
    setRequestState("idle");
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const publicFixture =
      health.status === "available" &&
      health.deployment_profile === "public-fixture";
    const requestMode = publicFixture ? "curated" : tripMode;
    const requestDate = publicFixture ? PUBLIC_FIXTURE_DATE : date;
    const requestStartHour = publicFixture
      ? PUBLIC_FIXTURE_START_HOUR
      : startHour;
    const requestEndHour = publicFixture ? PUBLIC_FIXTURE_END_HOUR : endHour;
    const invalidDate = !validDate(requestDate);
    const invalidOrder = requestStartHour >= requestEndHour;
    const invalidLength =
      !invalidOrder && requestEndHour - requestStartHour > 12;
    const invalidEndpoints =
      requestMode === "exploratory" &&
      origin.latitude === destination.latitude &&
      origin.longitude === destination.longitude;
    setDateError(invalidDate ? "Enter a valid date." : "");
    setStartError(
      invalidOrder ? "Start time must be earlier than end time." : ""
    );
    setEndError(
      invalidOrder
        ? "End time must be later than start time."
        : invalidLength
          ? "The time window cannot exceed 12 hours."
          : ""
    );
    setEndpointError(invalidEndpoints ? "Choose two different endpoints." : "");
    if (invalidDate || invalidOrder || invalidLength || invalidEndpoints) {
      if (invalidDate) dateRef.current?.focus();
      else if (invalidOrder) startRef.current?.focus();
      else if (invalidOrder || invalidLength) endRef.current?.focus();
      else document.getElementById("endpoint-origin")?.focus();
      return;
    }
    if (health.status !== "available" || requestState === "submitting") return;

    const request: TripAnalysisRequest = {
      mode: requestMode,
      origin_latitude: requestMode === "curated" ? 29.4245914 : origin.latitude,
      origin_longitude:
        requestMode === "curated" ? -98.4864288 : origin.longitude,
      destination_latitude:
        requestMode === "curated" ? 29.425833 : destination.latitude,
      destination_longitude:
        requestMode === "curated" ? -98.485833 : destination.longitude,
      landmark_name: requestMode === "curated" ? "The Alamo" : destination.name,
      district_name: "Downtown San Antonio",
      date: requestDate,
      start_hour: requestStartHour,
      end_hour: requestEndHour,
      cautious,
      execution_mode: health.mode,
    };
    setTripAnalysis(null);
    setRequestState("submitting");
    try {
      const response = await dataClient.analyzeTripAnalysis(request);
      if (response.state === "error") {
        setRequestState("failed");
      } else {
        setTripAnalysis(response);
        setRequestState("idle");
      }
    } catch {
      setRequestState("failed");
    }
  }

  async function searchPlaces(value: string) {
    setSearch(value);
    if (value.trim().length < 2) {
      setSearchResults([]);
      setSearchState("idle");
      return;
    }
    setSearchState("loading");
    try {
      const result = await dataClient.searchPlaces(value);
      setSearchResults(result.places);
      setSearchState("idle");
    } catch {
      setSearchState("error");
      setSearchResults([]);
    }
  }

  function selectEndpoint(place: LocationSelection) {
    const nextOrigin = activeEndpoint === "origin" ? place : origin;
    const nextDestination =
      activeEndpoint === "destination" ? place : destination;
    (activeEndpoint === "origin" ? setOrigin : setDestination)(place);
    const fixtureScenario = fixtureScenarioFor(nextOrigin, nextDestination);
    if (
      health.status === "available" &&
      health.mode === "fixture" &&
      fixtureScenario
    ) {
      setExploratoryTripSetup({
        ...exploratoryTripSetup,
        date: fixtureScenario.date,
        startHour: fixtureScenario.startHour,
        endHour: fixtureScenario.endHour,
      });
    }
    setEndpointError("");
    clearOutcome();
  }

  const busy = requestState === "submitting";
  const mode = health.status === "available" ? health.mode : null;
  const publicFixture =
    health.status === "available" &&
    health.deployment_profile === "public-fixture";
  const effectiveTripMode = publicFixture ? "curated" : tripMode;

  return (
    <section className="screen trip-setup">
      <header className="trip-setup-heading">
        <span className="step-label">Curated San Antonio trip</span>
        <h1>Trip Setup</h1>
        <p>
          {publicFixture
            ? "Explore the fixed demonstration date and time window for environmental conditions at The Alamo."
            : "Select a date and time window for environmental conditions at The Alamo."}
        </p>
      </header>

      <div className="setup-layout">
        <form
          className="setup-card"
          onSubmit={submit}
          aria-busy={busy}
          noValidate
        >
          {!publicFixture && (
            <div
              className="setup-mode-toggle"
              role="group"
              aria-label="Trip mode"
            >
              <button
                type="button"
                className={tripMode === "curated" ? "active" : ""}
                onClick={() => setTripMode("curated")}
                disabled={busy}
              >
                Curated trip
              </button>
              <button
                type="button"
                className={tripMode === "exploratory" ? "active" : ""}
                onClick={() => setTripMode("exploratory")}
                disabled={busy}
              >
                Explore another trip
              </button>
            </div>
          )}
          {effectiveTripMode === "curated" ? (
            <div className="curated-trip" aria-label="Curated trip places">
              <div>
                <span>Origin</span>
                <strong>Menger Hotel</strong>
              </div>
              <div>
                <span>Destination</span>
                <strong>The Alamo</strong>
              </div>
              <div>
                <span>Area</span>
                <strong>Downtown San Antonio / Alamo Plaza</strong>
              </div>
            </div>
          ) : (
            <div className="exploratory-endpoints">
              <p>Select both endpoints by searching or clicking the map.</p>
              <label htmlFor="place-search">Search places</label>
              <input
                id="place-search"
                value={search}
                onChange={(event) => void searchPlaces(event.target.value)}
                placeholder="Search a place"
                disabled={busy}
                aria-describedby="place-search-help"
              />
              <span id="place-search-help" className="visually-hidden">
                Search results set the currently active origin or destination.
              </span>
              {searchState === "loading" && (
                <p role="status">Searching places...</p>
              )}
              {searchState === "error" && (
                <p role="alert">
                  Place search is unavailable. Select the endpoint on the map.
                </p>
              )}
              {searchResults.map((place) => (
                <button
                  type="button"
                  key={place.id}
                  onClick={() => {
                    selectEndpoint(place);
                    setSearch("");
                    setSearchResults([]);
                  }}
                  aria-label={`Set ${activeEndpoint} to ${place.name}`}
                >
                  {place.name} <small>{place.context}</small>
                </button>
              ))}
              <div className="endpoint-buttons">
                <button
                  id="endpoint-origin"
                  type="button"
                  onClick={() => setActiveEndpoint("origin")}
                  className={activeEndpoint === "origin" ? "active" : ""}
                  aria-pressed={activeEndpoint === "origin"}
                >
                  Origin: {origin.name}
                </button>
                <button
                  type="button"
                  onClick={() => setActiveEndpoint("destination")}
                  className={activeEndpoint === "destination" ? "active" : ""}
                  aria-pressed={activeEndpoint === "destination"}
                >
                  Destination: {destination.name}
                </button>
              </div>
              {endpointError && (
                <p className="field-error" role="alert">
                  {endpointError}
                </p>
              )}
              <MapContainer
                center={[29.425, -98.486]}
                zoom={14}
                className="map"
                scrollWheelZoom
              >
                <TileLayer
                  attribution="&copy; OpenStreetMap contributors"
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <EndpointMap onSelect={selectEndpoint} />
                <CircleMarker
                  center={[origin.latitude, origin.longitude]}
                  radius={8}
                  pathOptions={{ color: "#b9472f" }}
                />
                <CircleMarker
                  center={[destination.latitude, destination.longitude]}
                  radius={8}
                  pathOptions={{ color: "#245c4a" }}
                />
              </MapContainer>
            </div>
          )}

          <div className="setup-fields">
            <div className="field">
              <label htmlFor="trip-date">Date</label>
              <input
                ref={dateRef}
                id="trip-date"
                type="date"
                value={publicFixture ? PUBLIC_FIXTURE_DATE : date}
                disabled={busy || publicFixture}
                aria-invalid={Boolean(dateError)}
                aria-describedby={dateError ? "date-error" : undefined}
                onChange={(event) => {
                  setTripSetup({
                    ...tripSetup,
                    date: event.target.value,
                  });
                  setDateError("");
                  setRequestState("idle");
                }}
              />
              {dateError && (
                <span id="date-error" className="field-error">
                  {dateError}
                </span>
              )}
            </div>
            <div className="field">
              <label htmlFor="trip-start-hour">Start time</label>
              <select
                ref={startRef}
                id="trip-start-hour"
                value={publicFixture ? PUBLIC_FIXTURE_START_HOUR : startHour}
                disabled={busy || publicFixture}
                aria-invalid={Boolean(startError)}
                aria-describedby={startError ? "start-hour-error" : undefined}
                onChange={(event) => {
                  setTripSetup({
                    ...tripSetup,
                    startHour: Number(event.target.value),
                  });
                  setStartError("");
                  setEndError("");
                  setRequestState("idle");
                }}
              >
                {HOURS.map((value) => (
                  <option key={value} value={value}>
                    {String(value).padStart(2, "0")}:00
                  </option>
                ))}
              </select>
              {startError && (
                <span id="start-hour-error" className="field-error">
                  {startError}
                </span>
              )}
            </div>
            <div className="field">
              <label htmlFor="trip-end-hour">End time</label>
              <select
                ref={endRef}
                id="trip-end-hour"
                value={publicFixture ? PUBLIC_FIXTURE_END_HOUR : endHour}
                disabled={busy || publicFixture}
                aria-invalid={Boolean(endError)}
                aria-describedby={endError ? "end-hour-error" : undefined}
                onChange={(event) => {
                  setTripSetup({
                    ...tripSetup,
                    endHour: Number(event.target.value),
                  });
                  setStartError("");
                  setEndError("");
                  setRequestState("idle");
                }}
              >
                {HOURS.map((value) => (
                  <option key={value} value={value}>
                    {String(value).padStart(2, "0")}:00
                  </option>
                ))}
              </select>
              {endError && (
                <span id="end-hour-error" className="field-error">
                  {endError}
                </span>
              )}
            </div>
          </div>
          {publicFixture && (
            <p className="fixture-facts" role="note">
              Public demonstration facts are fixed to August 23, 2026, from
              08:00 to 20:00. Cautious guidance remains available below.
            </p>
          )}

          <label className="cautious-option">
            <input
              type="checkbox"
              checked={cautious}
              disabled={busy}
              onChange={(event) => {
                setTripSetup({
                  ...tripSetup,
                  cautious: event.target.checked,
                });
                setRequestState("idle");
              }}
            />
            <span>
              <strong>Cautious guidance</strong>
              <small>
                Request a more conservative interpretation of heat conditions.
              </small>
            </span>
          </label>

          {busy ? (
            <div className="busy-status" role="status">
              Analyzing trip...
            </div>
          ) : (
            <button type="submit" disabled={health.status !== "available"}>
              Analyze trip
            </button>
          )}
        </form>

        <aside className="mode-card" aria-live="polite">
          <span className="mode-label">Application mode</span>
          {health.status === "checking" && (
            <p role="status">Checking application mode...</p>
          )}
          {mode && health.status === "available" && (
            <>
              <div className={`mode-value ${mode}`}>
                {mode === "fixture" ? (
                  <Database size={18} />
                ) : (
                  <Radio size={18} />
                )}
                <strong>
                  {mode === "fixture" ? "Fixture replay" : "Live data"}
                </strong>
              </div>
              <p>
                {mode === "fixture"
                  ? "This analysis replays the committed San Antonio scenario."
                  : "This analysis requests current provider data."}
              </p>
              <p>
                Deployment profile: <strong>{health.deployment_profile}</strong>
                . Capability: <strong>{health.execution_capability}</strong>.
              </p>
            </>
          )}
          {health.status === "unavailable" && (
            <div className="mode-unavailable">
              <AlertTriangle size={20} />
              <strong>Application mode unavailable</strong>
              <p>
                We could not confirm whether analysis uses fixture replay or
                live data.
              </p>
              <button
                type="button"
                className="secondary-button"
                onClick={() => void checkHealth()}
              >
                Check again
              </button>
            </div>
          )}
          <div className="geography-note">
            <strong>Supported live-data geography</strong>
            <p>
              Live provider requests are supported in the United States. This is
              separate from this curated San Antonio trip and fixture replay.
            </p>
          </div>
        </aside>
      </div>

      {tripAnalysis && mode === tripAnalysis.execution_mode && (
        <section
          className={`setup-outcome ${tripAnalysis.state}`}
          role="status"
          aria-label="Trip analysis outcome"
        >
          <CheckCircle2 size={24} />
          <div>
            {tripAnalysis.state === "series_ready" &&
              tripAnalysis.environment && (
                <>
                  <h2>Environmental conditions</h2>
                  <div className="series-summary">
                    <div>
                      <span>Temperature anchor</span>
                      <strong>
                        {tripAnalysis.environment.temperature_anchor_celsius.toFixed(
                          1
                        )}{" "}
                        C
                      </strong>
                    </div>
                    <div>
                      <span>Data source</span>
                      <strong>
                        {tripAnalysis.environment.provenance.source}
                      </strong>
                    </div>
                    <div>
                      <span>Data date</span>
                      <strong>
                        {tripAnalysis.environment.provenance.data_date}
                      </strong>
                    </div>
                  </div>
                  <div className="series-table-wrap">
                    <table className="series-table">
                      <caption>Hourly environmental readings</caption>
                      <thead>
                        <tr>
                          <th scope="col">Time</th>
                          {Object.keys(
                            tripAnalysis.environment.entries[0].parameters
                          ).map((parameter) => (
                            <th scope="col" key={parameter}>
                              {formatParameterName(parameter)}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {tripAnalysis.environment.entries.map((entry) => (
                          <tr key={entry.valid_time}>
                            <th scope="row">
                              {formatHour(
                                entry.valid_time,
                                tripAnalysis.environment!.timezone
                              )}
                            </th>
                            {Object.keys(entry.parameters).map((parameter) => (
                              <td key={parameter}>
                                {formatMetric(
                                  entry.parameters[parameter],
                                  parameterUnit(parameter)
                                )}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="series-warning">
                    <AlertTriangle size={17} />
                    {tripAnalysis.environment.warning}
                  </p>
                </>
              )}
            {tripAnalysis.state === "success" && <h2>Trip analysis ready</h2>}
            {tripAnalysis.state === "degraded" && (
              <>
                <h2>Trip analysis ready with limitations</h2>
                <ul>
                  {Object.values(tripAnalysis.degraded_reasons ?? {}).map(
                    (reason) => (
                      <li key={reason}>{reason}</li>
                    )
                  )}
                </ul>
              </>
            )}
            {(tripAnalysis.state === "unavailable" ||
              tripAnalysis.state === "error") && (
              <>
                <h2>Trip analysis unavailable</h2>
                <p>{tripAnalysis.unavailable?.reason}</p>
                {tripAnalysis.unavailable?.code === "provider_data_missing" && (
                  <p className="action-guidance">
                    Required provider data is missing. Retry later or edit the
                    trip setup to choose a supported fixture scenario.
                  </p>
                )}
                {tripAnalysis.unavailable?.action && (
                  <p className="action-guidance">
                    {tripAnalysis.unavailable.action === "choose_us_endpoints"
                      ? "Choose origin and destination within the United States."
                      : tripAnalysis.unavailable.action ===
                          "edit_setup_or_use_live_data"
                        ? "Edit the setup, or ask a maintainer to enable live data."
                        : "Retry the analysis or edit the trip setup."}
                  </p>
                )}
              </>
            )}
            {(tripAnalysis.state === "success" ||
              tripAnalysis.state === "degraded") &&
              tripAnalysis.hotels?.enrichment?.state === "unavailable" && (
                <div className="route-evidence-warning" role="note">
                  <AlertTriangle size={18} />
                  <span>
                    {tripAnalysis.hotels.enrichment.reason} The base hotel
                    ranking remains available.
                  </span>
                </div>
              )}
            {(tripAnalysis.state === "success" ||
              tripAnalysis.state === "degraded") &&
              tripAnalysis.best_time && (
                <>
                  <BestTimeSummary result={tripAnalysis.best_time} />
                  <HeatPolicySummary
                    value={tripAnalysis.best_time.heat_interpretation}
                  />
                </>
              )}
            {(tripAnalysis.state === "success" ||
              tripAnalysis.state === "degraded") &&
              tripAnalysis.routes && (
                <>
                  <RouteComparison result={tripAnalysis.routes} />
                  <Link className="button-link" to="/walk/routes">
                    Compare returned routes
                  </Link>
                </>
              )}
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                clearOutcome();
                dateRef.current?.focus();
              }}
            >
              Edit setup
            </button>
          </div>
        </section>
      )}

      {requestState === "failed" && (
        <section className="setup-outcome failed" role="alert">
          <AlertTriangle size={24} />
          <div>
            <h2>We could not analyze this trip.</h2>
            <p>Please try the request again.</p>
            <button type="button" onClick={() => void submit()}>
              Try again
            </button>
          </div>
        </section>
      )}
    </section>
  );
}

function HeatPolicySummary({ value }: { value?: HeatInterpretation }) {
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
