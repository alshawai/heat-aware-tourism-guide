import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Radio,
  RotateCcw,
} from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import {
  activeAnalysis,
  CANONICAL_DESTINATION,
  CANONICAL_ORIGIN,
  useAppState,
  type HealthState,
} from "../../app/AppState";
import type {
  ExecutionMode,
  RouteComparisonResult,
  RouteDecisionState,
  TripAnalysisResponse,
  TripSetup,
} from "../../types";
import { BestTimeSummary } from "./BestTimeSummary";
import { actionGuidance } from "./decisionLabels";
import { EndpointPicker } from "./EndpointMap";
import {
  CANONICAL_FIXTURE_SCENARIO,
  fixtureScenarioFor,
} from "./fixtureScenarios";
import {
  formatClockHour,
  formatHour,
  formatMetric,
  formatParameterName,
  parameterUnit,
} from "./format";
import { HeatPolicySummary } from "./HeatPolicySummary";
import { HourlyHeatChart } from "./HourlyHeatChart";
import { RouteComparison } from "./RouteComparison";
import { RouteDossier } from "./RouteDossier";
import { RouteMap } from "./RouteMap";
import {
  END_HOUR_OPTIONS,
  formatHourLabel,
  formatWindowLabel,
  INVALID_DATE_MESSAGE,
  isValidDate,
  lastHour,
  LIVE_EARLIEST_DATE,
  liveLatestDate,
  SAME_ENDPOINTS_MESSAGE,
  START_HOUR_OPTIONS,
  validateLiveDate,
  validateTimeWindow,
} from "./timeWindow";
import { UnavailableNotice } from "./UnavailableNotice";
import {
  buildHourOverrideRequest,
  buildTripRequest,
  useTripAnalysis,
} from "./useTripAnalysis";

function isPublicFixture(health: HealthState) {
  return (
    health.status === "available" &&
    health.deployment_profile === "public-fixture"
  );
}

/**
 * The setup the request will actually carry.
 *
 * On the public demonstration the traveler's date, window, and endpoints are
 * replaced by the acquired canonical scenario rather than merely disabled, so
 * what is validated, submitted, and reused by an hour override are the same
 * values — and they are read from the scenario catalog, so they cannot drift
 * from the fixture the deployment actually holds.
 */
function effectiveSetup(setup: TripSetup, health: HealthState): TripSetup {
  if (!isPublicFixture(health)) return setup;
  return {
    ...setup,
    origin: CANONICAL_ORIGIN,
    destination: CANONICAL_DESTINATION,
    date: CANONICAL_FIXTURE_SCENARIO.date,
    startHour: CANONICAL_FIXTURE_SCENARIO.startHour,
    endHour: CANONICAL_FIXTURE_SCENARIO.endHour,
  };
}

function ModeCard({
  health,
  onRecheck,
}: {
  health: HealthState;
  onRecheck: () => void;
}) {
  return (
    <aside className="mode-card" aria-live="polite">
      <span className="mode-label">Application mode</span>
      {health.status === "checking" && (
        <p role="status">Checking application mode...</p>
      )}
      {health.status === "available" && (
        <>
          <div className={`mode-value ${health.mode}`}>
            {health.mode === "fixture" ? (
              <Database size={18} />
            ) : (
              <Radio size={18} />
            )}
            <strong>
              {health.mode === "fixture" ? "Fixture replay" : "Live data"}
            </strong>
          </div>
          <p>
            {health.mode === "fixture"
              ? "This analysis replays the committed San Antonio scenario."
              : "This analysis requests current provider data."}
          </p>
          <p>
            Deployment profile: <strong>{health.deployment_profile}</strong>.
            Capability: <strong>{health.execution_capability}</strong>.
          </p>
        </>
      )}
      {health.status === "unavailable" && (
        <div className="mode-unavailable">
          <AlertTriangle size={20} />
          <strong>Application mode unavailable</strong>
          <p>
            We could not confirm whether analysis uses fixture replay or live
            data.
          </p>
          <button
            type="button"
            className="secondary-button"
            onClick={onRecheck}
          >
            Check again
          </button>
        </div>
      )}
      <div className="geography-note">
        <strong>Supported live-data geography</strong>
        <p>
          Live provider requests are supported in the United States. Fixture
          replay is limited to the committed San Antonio scenario.
        </p>
      </div>
    </aside>
  );
}

/**
 * Screen two: everything one analysis needs, collected before it is spent.
 *
 * Both endpoints, the date, and the window are gathered here so the results
 * screen can be reached with a single billable `/api/trip/analyze` call.
 */
export function TripSetupScreen() {
  const { health, refreshHealth, tripSetup, setTripSetup, setBaseline } =
    useAppState();
  const { phase, run, reset } = useTripAnalysis();
  const navigate = useNavigate();
  const [dateError, setDateError] = useState("");
  const [startError, setStartError] = useState("");
  const [endError, setEndError] = useState("");
  const [endpointError, setEndpointError] = useState("");
  const dateRef = useRef<HTMLInputElement>(null);
  const startRef = useRef<HTMLSelectElement>(null);
  const endRef = useRef<HTMLSelectElement>(null);

  const busy = phase === "submitting";
  const publicFixture = isPublicFixture(health);
  const effective = effectiveSetup(tripSetup, health);
  const fixtureMode =
    health.status === "available" && health.mode === "fixture";
  // Live execution reaches only the provider's own span, so the date field is
  // bounded and validated against it rather than against the calendar.
  const liveMode = health.status === "available" && health.mode === "live";
  const fixtureScenario = fixtureMode
    ? fixtureScenarioFor(effective.origin, effective.destination)
    : undefined;

  // Every edit invalidates any retained analysis, so the results screen can
  // never describe a trip the traveler has since changed.
  function edit(change: Partial<TripSetup>) {
    setTripSetup({ ...tripSetup, ...change });
    reset();
  }

  /**
   * Move one pin, and in fixture mode adopt whatever the new pair was acquired
   * with.
   *
   * Fixture replay matches a request on the date, the window, the landmark, and
   * the district as well as the coordinates, and each scenario was acquired with
   * its own (`fixtureScenarios.ts`). Snapping to them on selection is what lets a
   * traveler reach a committed scenario at all; the fields stay editable, so a
   * date fixture replay does not hold still answers with the server's refusal.
   */
  function moveEndpoint(
    role: "origin" | "destination",
    point: TripSetup["origin"]
  ) {
    setEndpointError("");
    const moved =
      role === "origin"
        ? { origin: point, destination: tripSetup.destination }
        : { origin: tripSetup.origin, destination: point };
    const scenario = fixtureMode
      ? fixtureScenarioFor(moved.origin, moved.destination)
      : undefined;
    if (!scenario) {
      edit(moved);
      return;
    }
    edit({
      ...moved,
      destination: { ...moved.destination, context: scenario.districtName },
      date: scenario.date,
      startHour: scenario.startHour,
      endHour: scenario.endHour,
    });
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    // In live mode the calendar is not the constraint the provider is: a date
    // outside its span cannot produce readings, so it must not be spendable.
    const dateProblem = liveMode
      ? validateLiveDate(effective.date)
      : isValidDate(effective.date)
        ? null
        : INVALID_DATE_MESSAGE;
    const windowError = validateTimeWindow(
      effective.startHour,
      effective.endHour
    );
    const invalidOrder = effective.startHour >= effective.endHour;
    // Either pin can be moved in this one flow, so the guard is unconditional.
    const sameEndpoints =
      effective.origin.latitude === effective.destination.latitude &&
      effective.origin.longitude === effective.destination.longitude;

    setDateError(dateProblem ?? "");
    // An out-of-order window is reported on both selects, because either one
    // can be the field the traveler wants to change.
    setStartError(
      invalidOrder ? "Start time must be earlier than end time." : ""
    );
    setEndError(
      invalidOrder
        ? "End time must be later than start time."
        : (windowError ?? "")
    );
    setEndpointError(sameEndpoints ? SAME_ENDPOINTS_MESSAGE : "");

    if (dateProblem || windowError || sameEndpoints) {
      if (dateProblem) dateRef.current?.focus();
      else if (invalidOrder) startRef.current?.focus();
      else if (windowError) endRef.current?.focus();
      else document.getElementById("endpoint-origin")?.focus();
      return;
    }
    if (health.status !== "available" || busy) return;

    // Persist the forced public-fixture facts so an hour override rebuilds the
    // same request the baseline used.
    setTripSetup(effective);
    const response = await run(buildTripRequest(effective, health.mode));
    if (!response) return;
    setBaseline(response);
    navigate("/trip/results");
  }

  return (
    <section className="screen trip-setup">
      <header className="trip-setup-heading">
        <span className="step-label">Step 1 of 2 · Explore trip</span>
        <h1>Explore trip</h1>
        <p>
          {publicFixture
            ? "Explore the fixed demonstration date and time window for the San Antonio walk from the Menger Hotel to The Alamo."
            : "Choose where you are walking from and to, then the date and hours you are considering."}
        </p>
      </header>

      <div className="setup-layout">
        <form
          className="setup-card"
          onSubmit={submit}
          aria-busy={busy}
          noValidate
        >
          {/* One flow, one picker: the Menger Hotel and The Alamo are only the
              prefilled defaults, so both pins are always movable. */}
          <EndpointPicker
            origin={effective.origin}
            destination={effective.destination}
            disabled={busy || publicFixture}
            error={endpointError}
            onChange={moveEndpoint}
          />

          <div className="setup-fields">
            <div className="field">
              <label htmlFor="trip-date">Date</label>
              <input
                ref={dateRef}
                id="trip-date"
                type="date"
                value={effective.date}
                min={liveMode ? LIVE_EARLIEST_DATE : undefined}
                max={liveMode ? liveLatestDate() : undefined}
                disabled={busy || publicFixture}
                aria-invalid={Boolean(dateError)}
                aria-describedby={dateError ? "date-error" : undefined}
                onChange={(event) => {
                  setDateError("");
                  edit({ date: event.target.value });
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
                value={effective.startHour}
                disabled={busy || publicFixture}
                aria-invalid={Boolean(startError)}
                aria-describedby={startError ? "start-hour-error" : undefined}
                onChange={(event) => {
                  setStartError("");
                  setEndError("");
                  edit({ startHour: Number(event.target.value) });
                }}
              >
                {START_HOUR_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {formatHourLabel(value)}
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
                value={effective.endHour}
                disabled={busy || publicFixture}
                aria-invalid={Boolean(endError)}
                aria-describedby={endError ? "end-hour-error" : undefined}
                onChange={(event) => {
                  setStartError("");
                  setEndError("");
                  edit({ endHour: Number(event.target.value) });
                }}
              >
                {/* Labelled by the last hour walked: the wire value is the
                    server's exclusive end, which travelers do not think in. */}
                {END_HOUR_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {formatHourLabel(lastHour(value))}
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
          <p className="window-summary">
            Hours analyzed:{" "}
            <strong>
              {formatWindowLabel(effective.startHour, effective.endHour)}
            </strong>
            , inclusive.
          </p>
          {publicFixture && (
            <p className="fixture-facts" role="note">
              Public demonstration facts are fixed to the committed scenario:{" "}
              {effective.date},{" "}
              {formatWindowLabel(effective.startHour, effective.endHour)}.
              Cautious guidance remains available below.
            </p>
          )}
          {!publicFixture && fixtureScenario && (
            <p className="fixture-facts" role="note">
              Fixture replay holds this walk on {effective.date}, so the date
              and hours follow the committed scenario. Another date returns the
              server&apos;s no-matching-fixture answer rather than invented
              data.
            </p>
          )}
          {liveMode && (
            <p className="fixture-facts" role="note">
              Live readings run from {LIVE_EARLIEST_DATE} to tomorrow&apos;s
              forecast ({liveLatestDate()}); anything past tomorrow has not been
              measured or forecast yet. Each hour in the window is a separate
              provider request, so a shorter window costs less.
            </p>
          )}

          <label className="cautious-option">
            <input
              type="checkbox"
              checked={effective.cautious}
              disabled={busy}
              onChange={(event) => edit({ cautious: event.target.checked })}
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
          <p className="billing-note">
            One analysis covers the whole window: the best hour, the returned
            walking routes, and their modeled shade.
          </p>
        </form>

        <ModeCard health={health} onRecheck={() => void refreshHealth()} />
      </div>

      {phase === "failed" && (
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

function EnvironmentSeries({ result }: { result: TripAnalysisResponse }) {
  const environment = result.environment;
  if (!environment) return null;
  const parameters = Object.keys(environment.entries[0]?.parameters ?? {});
  return (
    <section className="series-panel" aria-label="Environmental conditions">
      <h2>Environmental conditions</h2>
      <div className="series-summary">
        <div>
          <span>Temperature anchor</span>
          <strong>{environment.temperature_anchor_celsius.toFixed(1)} C</strong>
        </div>
        <div>
          <span>Data source</span>
          <strong>{environment.provenance.source}</strong>
        </div>
        <div>
          <span>Data date</span>
          <strong>{environment.provenance.data_date}</strong>
        </div>
      </div>
      <div className="series-table-wrap">
        <table className="series-table">
          <caption>Hourly environmental readings</caption>
          <thead>
            <tr>
              <th scope="col">Time</th>
              {parameters.map((parameter) => (
                <th scope="col" key={parameter}>
                  {formatParameterName(parameter)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {environment.entries.map((entry) => (
              <tr key={entry.valid_time}>
                <th scope="row">
                  {formatHour(entry.valid_time, environment.timezone)}
                </th>
                {parameters.map((parameter) => (
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
        {environment.warning}
      </p>
    </section>
  );
}

/**
 * A single hour the server declined to analyze.
 *
 * Fixture replay only matches the committed window, so a narrowed request can
 * legitimately come back unavailable while the analyzed window stays valid.
 */
type HourRefusal = {
  hour: number;
  reason: string | null;
  action: string | null;
};

/** The decision states that leave every returned route unranked. */
const UNRANKED_DECISION_STATES: RouteDecisionState[] = [
  "shade_required",
  "insufficient_shade_comparison_required",
  "heat_unavailable",
];

/**
 * Why no route was recommended, in the traveler's terms.
 *
 * The backend's `decision_state` is an internal token and its degraded reason is
 * an engineering fragment, so neither is shown. The two shade failures are
 * genuinely different and must not be merged: the building data can fail to
 * arrive at all, or it can arrive complete while too few buildings publish a
 * height to model shade from. Only the first is worth retrying, and the
 * discriminator is the building provenance the server already sends —
 * `response_status: "unavailable"` is set exactly where the Overpass fetch
 * failed, alongside the reason as `note`.
 */
function UnrankedRoutesNotice({ routes }: { routes: RouteComparisonResult }) {
  const state = routes.decision_state;
  if (!state || !UNRANKED_DECISION_STATES.includes(state)) return null;

  const buildings = routes.building_provenance;
  const buildingsMissing = buildings?.response_status === "unavailable";
  const heading = "Routes are listed, but not ranked";

  return (
    <section className="route-unranked-notice" role="note">
      <AlertTriangle size={20} />
      <div>
        <h2>{heading}</h2>
        {state === "heat_unavailable" ? (
          <p>
            Heat could not be measured along this corridor, so no route is
            recommended. Every returned route is still listed below, in the
            order the routing service returned them.
          </p>
        ) : buildingsMissing ? (
          <>
            <p>
              We could not reach the building data for this corridor, so no
              shade could be modeled and no route is recommended. Every returned
              route is still listed below, in the order the routing service
              returned them.
            </p>
            <p>Re-running the analysis may reach the building data.</p>
            {buildings?.note && (
              <p className="notice-detail">{buildings.note}</p>
            )}
          </>
        ) : (
          <>
            <p>
              The buildings along this corridor do not publish enough height
              data to compare shade, so no route is recommended. Every returned
              route is still listed below, in the order the routing service
              returned them.
            </p>
            <p>
              Re-running the analysis will not change this: the heights are
              missing from the map data itself, not from this request.
            </p>
          </>
        )}
      </div>
    </section>
  );
}

/** The reason the unranked notice already states, so it is not repeated raw. */
function bannerReasons(analysis: TripAnalysisResponse): [string, string][] {
  const state = analysis.routes?.decision_state;
  const explained = Boolean(state && UNRANKED_DECISION_STATES.includes(state));
  return Object.entries(analysis.degraded_reasons ?? {}).filter(
    ([section]) => !(explained && section === "routes")
  );
}

/**
 * Screen three: the whole answer on one screen.
 *
 * The chart always shows the baseline window, because that is the comparison
 * the traveler asked for. The map and route cards show the active analysis,
 * which is the hour override when one exists — its route heat and solar
 * geometry were computed for the hour actually chosen.
 */
export function TripResultsScreen() {
  const { health, tripSetup, tripResults, setOverride, clearOverride } =
    useAppState();
  const { phase, run, reset } = useTripAnalysis();
  const [pendingHour, setPendingHour] = useState<number | null>(null);
  const [refusedHour, setRefusedHour] = useState<HourRefusal | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);

  if (!tripResults) return <Navigate to="/trip/setup" replace />;

  const { baseline, override } = tripResults;
  const analysis = override?.response ?? baseline;
  const routes = analysis.routes;
  const busy = phase === "submitting";
  const executionMode: ExecutionMode = baseline.execution_mode;
  const activeHour =
    override?.hour ?? baseline.best_time?.recommendation_hour ?? null;
  const recommendedId =
    routes?.alternatives.find((route) => route.recommended)?.identity ??
    routes?.alternatives[0]?.identity ??
    "";
  // A superseded highlight can name a route the override did not return.
  const selectedId =
    highlightId &&
    routes?.alternatives.some((route) => route.identity === highlightId)
      ? highlightId
      : recommendedId;

  async function recalculate(hour: number) {
    const response = await run(
      buildHourOverrideRequest(tripSetup, executionMode, hour)
    );
    if (!response) return;
    setPendingHour(null);
    // A refusal answers the question about that one hour; the analyzed window
    // is still valid, so it is reported beside the chart and the baseline
    // results stay on screen instead of being replaced by the notice.
    if (response.state === "unavailable" || response.state === "error") {
      setRefusedHour({
        hour,
        reason: response.unavailable?.reason ?? null,
        action: response.unavailable?.action ?? null,
      });
      return;
    }
    setRefusedHour(null);
    setOverride(hour, response);
  }

  function selectHour(hour: number) {
    // A refusal names one hour, so it cannot stand while another is pending.
    setRefusedHour(null);
    setPendingHour(hour === activeHour ? null : hour);
  }

  function returnToRecommended() {
    reset();
    setPendingHour(null);
    setRefusedHour(null);
    clearOverride();
  }

  return (
    <section className="screen trip-results">
      <header className="trip-setup-heading">
        <span className="step-label">Step 2 of 2 · Trip results</span>
        <h1>
          {baseline.state === "series_ready"
            ? "Environmental series"
            : "Your walk"}
        </h1>
        <p>
          {tripSetup.origin.name} to {tripSetup.destination.name} on{" "}
          {tripSetup.date}.
        </p>
        <Link className="text-link" to="/trip/setup">
          Edit setup
        </Link>
      </header>

      <section
        className={`setup-outcome ${analysis.state}`}
        role="status"
        aria-label="Trip analysis outcome"
      >
        <CheckCircle2 size={24} />
        <div>
          {analysis.state === "success" && <h2>Trip analysis ready</h2>}
          {analysis.state === "degraded" && (
            <>
              <h2>Trip analysis ready with limitations</h2>
              <ul>
                {bannerReasons(analysis).map(([section, reason]) => (
                  <li key={section}>{reason}</li>
                ))}
              </ul>
            </>
          )}
          {analysis.state === "series_ready" && (
            <h2>Environmental series only</h2>
          )}
          <p className="outcome-mode">
            Produced by{" "}
            {executionMode === "fixture"
              ? "fixture replay"
              : "live provider data"}
            {override
              ? `, recalculated for ${formatClockHour(override.hour)} only.`
              : "."}
          </p>
        </div>
      </section>

      {(analysis.state === "unavailable" || analysis.state === "error") && (
        // Only a baseline can reach this: an unavailable result carries no
        // domain payload, so no chart was drawn and no hour override exists.
        <UnavailableNotice
          reason={analysis.unavailable?.reason}
          code={analysis.unavailable?.code}
          action={analysis.unavailable?.action}
        >
          <Link className="button-link" to="/trip/setup">
            Edit setup
          </Link>
        </UnavailableNotice>
      )}

      {baseline.state === "series_ready" && (
        <EnvironmentSeries result={baseline} />
      )}

      {baseline.best_time && (
        <div className="results-primary">
          <BestTimeSummary result={baseline.best_time} />
          <HeatPolicySummary value={baseline.best_time.heat_interpretation} />
          <HourlyHeatChart
            result={baseline.best_time}
            selectedHour={pendingHour ?? activeHour ?? -1}
            interactive={!isPublicFixture(health)}
            busy={busy}
            onSelectHour={selectHour}
          />
          {pendingHour !== null && (
            <div
              className="hour-override"
              role="group"
              aria-label="Custom hour override"
            >
              <p>
                Re-analyze the walk for {formatClockHour(pendingHour)} only.
                This asks the server for fresh route heat and sun angles at that
                hour.
              </p>
              <button
                type="button"
                onClick={() => void recalculate(pendingHour)}
                disabled={busy}
              >
                {busy
                  ? `Recalculating ${formatClockHour(pendingHour)}...`
                  : `Recalculate for ${formatClockHour(pendingHour)}`}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => setPendingHour(null)}
                disabled={busy}
              >
                Keep current hour
              </button>
            </div>
          )}
          {override && pendingHour === null && (
            <div className="hour-override">
              <p>
                Showing {formatClockHour(override.hour)}, not the recommended
                hour.
              </p>
              <button
                type="button"
                className="secondary-button"
                onClick={returnToRecommended}
                disabled={busy}
              >
                <RotateCcw size={16} /> Return to recommended hour
              </button>
            </div>
          )}
          {refusedHour && pendingHour === null && (
            <div className="hour-override refused" role="alert">
              <h3>{formatClockHour(refusedHour.hour)} could not be analyzed</h3>
              <p>
                {refusedHour.reason ??
                  "The server did not return an analysis for that hour."}
              </p>
              {refusedHour.action && (
                <p className="action-guidance">
                  {actionGuidance(refusedHour.action)}
                </p>
              )}
              <p>
                Everything below still describes{" "}
                {activeHour === null
                  ? "the analyzed window"
                  : formatClockHour(activeHour)}
                .
              </p>
            </div>
          )}
          {phase === "failed" && (
            <p className="field-error" role="alert">
              That hour could not be re-analyzed. The results below still
              describe{" "}
              {activeHour === null
                ? "the analyzed window"
                : formatClockHour(activeHour)}
              .
            </p>
          )}
        </div>
      )}

      {routes && (
        <div className="results-routes">
          <UnrankedRoutesNotice routes={routes} />
          <RouteMap
            routes={routes}
            selectedId={selectedId}
            onSelect={setHighlightId}
          />
          <RouteComparison
            result={routes}
            selectedId={selectedId}
            onHighlight={setHighlightId}
          />
        </div>
      )}
    </section>
  );
}

/**
 * Screen four: one route alternative in full.
 *
 * The route is read from the active analysis, so a route opened after an hour
 * override shows the evidence computed for that hour.
 */
export function RouteDetailScreen() {
  const { tripResults } = useAppState();
  const { routeId } = useParams();
  const analysis = activeAnalysis(tripResults);
  const routes = analysis?.routes;
  const route = routes?.alternatives.find((item) => item.identity === routeId);
  if (!routes || !route) return <Navigate to="/trip/results" replace />;
  return (
    <RouteDossier
      route={route}
      comparison={routes}
      resultSetToken={analysis?.result_set_token}
    />
  );
}
