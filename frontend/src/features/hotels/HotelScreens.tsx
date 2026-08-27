import {
  ArrowRight,
  Hotel as HotelIcon,
  SlidersHorizontal,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
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
import type { Hotel, ResultState } from "../../types";

export function HotelLocationScreen() {
  const navigate = useNavigate();
  const { setHotelLocation } = useAppState();
  return (
    <LocationPicker
      title="Where should hotels be ranked?"
      description="Choose the area whose nearby hotels you want to compare by outdoor heat exposure."
      onContinue={(location) => {
        setHotelLocation(location);
        navigate("/hotels/results");
      }}
    />
  );
}

function useHotelRequest() {
  const { hotelLocation, mode, ranking, setRanking } = useAppState();
  const [status, setStatus] = useState<ResultState>(
    ranking ? (mode === "degraded" ? "degraded" : "success") : "loading"
  );
  const load = useCallback(() => {
    if (!hotelLocation) return;
    setStatus("loading");
    dataClient
      .rankHotels(hotelLocation, { mode })
      .then((value) => {
        setRanking(value);
        setStatus(
          mode === "degraded"
            ? "degraded"
            : value.usableCount < 5
              ? "degraded"
              : "success"
        );
      })
      .catch((error: Error & { code?: string }) =>
        setStatus(error.code === "EMPTY" ? "empty" : "error")
      );
  }, [hotelLocation, mode, setRanking]);
  useEffect(() => {
    if (!ranking) load();
  }, [ranking, load]);
  return { status, ranking, load };
}

function HotelComponents({ hotel }: { hotel: Hotel }) {
  return (
    <div className="component-list">
      {hotel.components.map((component) => (
        <div key={component.label}>
          <span>{component.label}</span>
          <strong>{component.value.toFixed(1)}</strong>
        </div>
      ))}
    </div>
  );
}

export function HotelRankingScreen() {
  const { hotelLocation } = useAppState();
  const { status, ranking, load } = useHotelRequest();
  if (!hotelLocation) return <Navigate to="/hotels/location" replace />;
  return (
    <section className="screen result-screen">
      <div className="screen-heading compact">
        <span className="step-label">Hotel ranking</span>
        <h1>{hotelLocation.name}</h1>
        <p>
          Lower component values rank ahead under the displayed product
          weighting.
        </p>
      </div>
      {status === "loading" && <ResultSkeleton rows={5} />}
      {(status === "empty" || status === "error") && (
        <ResultProblem kind={status} onRetry={load} />
      )}
      {ranking && (status === "success" || status === "degraded") && (
        <>
          {status === "degraded" && (
            <DegradedNotice>
              Fewer than five hotels or incomplete coverage makes this ranking
              less representative.
            </DegradedNotice>
          )}
          <article className="weights-summary">
            <SlidersHorizontal size={20} />
            <div>
              <strong>Current weighting configuration</strong>
              <p>
                {Object.entries(ranking.weights)
                  .map(([name, weight]) => `${name} ${weight}%`)
                  .join(" · ")}
              </p>
            </div>
          </article>
          <div className="hotel-list">
            {ranking.hotels.map((hotel, index) => (
              <article className="hotel-card" key={hotel.id}>
                <span className="rank-number">{index + 1}</span>
                <div className="hotel-main">
                  <div>
                    <h2>{hotel.name}</h2>
                    <p>
                      {hotel.percentile}th percentile for lower modeled exposure
                    </p>
                    {hotel.tieLabel && (
                      <span className="tie-chip">{hotel.tieLabel}</span>
                    )}
                  </div>
                  <HotelComponents hotel={hotel} />
                </div>
                <Link
                  aria-label={`View details for ${hotel.name}`}
                  to={`/hotels/${hotel.id}`}
                >
                  <ArrowRight size={20} />
                </Link>
              </article>
            ))}
          </div>
          <ProvenanceFooter value={ranking.provenance} />
        </>
      )}
    </section>
  );
}

export function HotelDetailScreen() {
  const { ranking } = useAppState();
  const { hotelId } = useParams();
  const hotel = ranking?.hotels.find((candidate) => candidate.id === hotelId);
  const defaults = ranking?.weights ?? {};
  const [weights, setWeights] = useState(defaults);
  if (!ranking) return <Navigate to="/hotels/results" replace />;
  if (!hotel) return <Navigate to="/hotels/results" replace />;
  const total = Object.values(weights).reduce((sum, value) => sum + value, 0);
  const weightedValue = useMemo(
    () =>
      hotel.components.reduce(
        (sum, component) =>
          sum + component.value * ((weights[component.label] ?? 0) / 100),
        0
      ),
    [hotel, weights]
  );
  return (
    <section className="screen narrow-screen">
      <div className="screen-heading">
        <span className="step-label">Hotel detail</span>
        <h1>{hotel.name}</h1>
        <p>
          {hotel.percentile}th percentile under the default product preferences.{" "}
          {hotel.tieLabel}
        </p>
      </div>
      <article className="local-score">
        <HotelIcon size={25} />
        <div>
          <span>Locally weighted comparison value</span>
          <strong>{weightedValue.toFixed(1)}</strong>
          <small>
            Lower is better within this returned hotel set; this is not an
            objective score.
          </small>
        </div>
      </article>
      <div className="weight-editor">
        <div className="section-title">
          <div>
            <span>Local preferences</span>
            <h2>Adjust component weights</h2>
          </div>
          <strong className={total === 100 ? "valid-total" : "invalid-total"}>
            {total}% total
          </strong>
        </div>
        {hotel.components.map((component) => (
          <label key={component.label}>
            <span>
              <strong>{component.label}</strong>
              <small>Raw component value: {component.value.toFixed(1)}</small>
            </span>
            <input
              type="number"
              min="0"
              max="100"
              value={weights[component.label] ?? 0}
              onChange={(event) =>
                setWeights((current) => ({
                  ...current,
                  [component.label]: Number(event.target.value),
                }))
              }
            />
            <span>%</span>
          </label>
        ))}
        <button
          className="secondary-button"
          type="button"
          onClick={() => setWeights(defaults)}
        >
          Reset defaults
        </button>
        {total !== 100 && (
          <p className="validation-message">
            Weights must total 100% for a comparable result.
          </p>
        )}
      </div>
      <Link className="text-link" to="/hotels/results">
        Return to hotel ranking
      </Link>
    </section>
  );
}
