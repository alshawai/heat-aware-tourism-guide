import { AlertTriangle, CheckCircle2, Database, Radio } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAppState } from "../app/AppState";
import { dataClient } from "../services/dataClient";
import type { ExecutionMode, TripAnalysisRequest } from "../types";

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

type HealthState =
  | { status: "checking" | "unavailable" }
  | { status: "available"; mode: ExecutionMode };
type RequestState = "idle" | "submitting" | "failed";

function validDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value
  );
}

export function TripSetupScreen() {
  const {
    curatedTripSetup,
    setCuratedTripSetup,
    tripAnalysis,
    setTripAnalysis,
  } = useAppState();
  const { date, hour, cautious } = curatedTripSetup;
  const [dateError, setDateError] = useState("");
  const [health, setHealth] = useState<HealthState>({ status: "checking" });
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const dateRef = useRef<HTMLInputElement>(null);

  async function checkHealth(signal?: AbortSignal) {
    setHealth({ status: "checking" });
    try {
      const mode = await dataClient.getHealth(signal);
      setHealth({ status: "available", mode });
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
    if (!validDate(date)) {
      setDateError("Enter a valid date.");
      dateRef.current?.focus();
      return;
    }
    setDateError("");
    if (health.status !== "available" || requestState === "submitting") return;

    const request: TripAnalysisRequest = {
      mode: "curated",
      origin_latitude: 29.4245914,
      origin_longitude: -98.4864288,
      destination_latitude: 29.425833,
      destination_longitude: -98.485833,
      landmark_name: "The Alamo",
      district_name: "Downtown San Antonio",
      date,
      hour,
      cautious,
      execution_mode: health.mode,
    };
    setTripAnalysis(null);
    setRequestState("submitting");
    try {
      const response = await dataClient.analyzeCuratedTrip(request);
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

  const busy = requestState === "submitting";
  const mode = health.status === "available" ? health.mode : null;

  return (
    <section className="screen trip-setup">
      <header className="trip-setup-heading">
        <span className="step-label">Curated San Antonio trip</span>
        <h1>Trip Setup</h1>
        <p>
          Configure one analysis for the best time, nearby hotels, and walking
          route for this fixed journey.
        </p>
      </header>

      <div className="setup-layout">
        <form
          className="setup-card"
          onSubmit={submit}
          aria-busy={busy}
          noValidate
        >
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

          <div className="setup-fields">
            <div className="field">
              <label htmlFor="trip-date">Date</label>
              <input
                ref={dateRef}
                id="trip-date"
                type="date"
                value={date}
                disabled={busy}
                aria-invalid={Boolean(dateError)}
                aria-describedby={dateError ? "date-error" : undefined}
                onChange={(event) => {
                  setCuratedTripSetup({
                    ...curatedTripSetup,
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
              <label htmlFor="trip-hour">Hour</label>
              <select
                id="trip-hour"
                value={hour}
                disabled={busy}
                onChange={(event) => {
                  setCuratedTripSetup({
                    ...curatedTripSetup,
                    hour: Number(event.target.value),
                  });
                  setRequestState("idle");
                }}
              >
                {HOURS.map((value) => (
                  <option key={value} value={value}>
                    {String(value).padStart(2, "0")}:00
                  </option>
                ))}
              </select>
            </div>
          </div>

          <label className="cautious-option">
            <input
              type="checkbox"
              checked={cautious}
              disabled={busy}
              onChange={(event) => {
                setCuratedTripSetup({
                  ...curatedTripSetup,
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
          {mode && (
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
