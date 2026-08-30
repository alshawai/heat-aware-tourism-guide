import {
  ArrowRight,
  Hotel as HotelIcon,
  SlidersHorizontal,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { useAppState } from "../../app/AppState";
import {
  DegradedNotice,
  LocationPicker,
  ResultProblem,
  ResultSkeleton,
} from "../../components/Shared";
import { dataClient } from "../../services/dataClient";
import { hotelLocations } from "../../mocks/data";
import type {
  HotelComponentAssignment,
  HotelComponentName,
  HotelRankingHotel,
  ResultState,
} from "../../types";
import {
  HOTEL_COMPONENT_LABELS,
  HOTEL_COMPONENTS,
  rerankHotels,
} from "./rerankHotels";

export function HotelLocationScreen() {
  const navigate = useNavigate();
  const { setHotelLocation } = useAppState();
  return (
    <LocationPicker
      title="Where should hotels be ranked?"
      description="Choose the area whose nearby hotels you want to compare by outdoor heat exposure."
      locations={hotelLocations}
      allowMapSelection={false}
      onContinue={(location) => {
        setHotelLocation(location);
        navigate("/hotels/results");
      }}
    />
  );
}

function useHotelRequest() {
  const { hotelLocation, mode, ranking, setRanking } = useAppState();
  const requestedLocation = useRef<string | null>(null);
  const requestVersion = useRef(0);
  const [status, setStatus] = useState<ResultState>(
    ranking
      ? ranking.state === "available"
        ? "success"
        : "degraded"
      : "loading"
  );
  const load = useCallback(() => {
    const previewMode = new URLSearchParams(window.location.search).has(
      "state"
    );
    const requestKey = hotelLocation
      ? `${hotelLocation.id}:${previewMode ? mode : "api"}`
      : null;
    if (!hotelLocation || requestedLocation.current === requestKey) {
      return;
    }
    const version = ++requestVersion.current;
    requestedLocation.current = requestKey;
    setStatus("loading");
    dataClient
      .rankHotels(hotelLocation, previewMode ? { mode } : {})
      .then((value) => {
        if (requestVersion.current !== version) return;
        const withPercentiles = value.ranking
          ? rerankHotels(
              value,
              value.ranking.weights,
              value.ranking.weight_label
            )
          : value;
        setRanking(withPercentiles);
        setStatus(value.state === "available" ? "success" : "degraded");
      })
      .catch((error: Error & { code?: string }) => {
        if (requestVersion.current !== version) return;
        requestedLocation.current = null;
        setStatus(error.code === "EMPTY" ? "empty" : "error");
      })
      .finally(() => {
        if (requestVersion.current === version) {
          requestedLocation.current = null;
        }
      });
  }, [hotelLocation, mode, setRanking]);
  useEffect(() => {
    if (!ranking) load();
  }, [ranking, load]);
  return { status, ranking, load };
}

function formatValue(component: HotelComponentAssignment) {
  return component.value === null
    ? "Unavailable"
    : `${component.value.toFixed(1)} ${component.unit === "C" ? "°C" : component.unit}`;
}

function HotelComponents({ hotel }: { hotel: HotelRankingHotel }) {
  return (
    <div className="component-list">
      {HOTEL_COMPONENTS.map((name) => {
        const component = hotel.components[name];
        return (
          <div key={name}>
            <span>{HOTEL_COMPONENT_LABELS[name]}</span>
            <strong>{formatValue(component)}</strong>
            <small>
              {component.percentile === null
                ? "Not ranked"
                : `${Math.round(component.percentile)}th component percentile`}
            </small>
          </div>
        );
      })}
    </div>
  );
}

function WeightEditor({
  initialWeights,
  onApply,
}: {
  initialWeights: Record<HotelComponentName, number>;
  onApply: (weights: Record<HotelComponentName, number>) => void;
}) {
  const defaults = Object.fromEntries(
    HOTEL_COMPONENTS.map((name) => [name, initialWeights[name] * 100])
  ) as Record<HotelComponentName, number>;
  const [weights, setWeights] = useState(defaults);
  const total = HOTEL_COMPONENTS.reduce((sum, name) => sum + weights[name], 0);

  function apply() {
    if (total !== 100) return;
    onApply(
      Object.fromEntries(
        HOTEL_COMPONENTS.map((name) => [name, weights[name] / 100])
      ) as Record<HotelComponentName, number>
    );
  }

  return (
    <div className="weight-editor">
      <div className="section-title">
        <div>
          <span>Local preferences</span>
          <h2>Rerank the candidate set</h2>
        </div>
        <strong className={total === 100 ? "valid-total" : "invalid-total"}>
          {total}% total
        </strong>
      </div>
      {HOTEL_COMPONENTS.map((name) => (
        <label key={name}>
          <span>
            <strong>{HOTEL_COMPONENT_LABELS[name]}</strong>
            <small>Candidate-relative component percentile</small>
          </span>
          <input
            aria-label={`${HOTEL_COMPONENT_LABELS[name]} weight`}
            type="number"
            min="0"
            max="100"
            value={weights[name]}
            onChange={(event) =>
              setWeights((current) => ({
                ...current,
                [name]: Math.max(0, Number(event.target.value)),
              }))
            }
          />
          <span>%</span>
        </label>
      ))}
      <div className="weight-actions">
        <button type="button" disabled={total !== 100} onClick={apply}>
          Apply local weights
        </button>
        <button
          className="secondary-button"
          type="button"
          onClick={() => {
            setWeights(defaults);
            onApply(initialWeights);
          }}
        >
          Reset product defaults
        </button>
      </div>
      {total !== 100 && (
        <p className="validation-message" role="alert">
          Weights must total 100% before reranking.
        </p>
      )}
      <small>
        Reranking uses cached component percentiles for every candidate and does
        not request another provider analysis.
      </small>
    </div>
  );
}

function EvidenceSummary({
  ranking,
}: {
  ranking: NonNullable<ReturnType<typeof useHotelRequest>["ranking"]>;
}) {
  return (
    <section className="evidence-summary" aria-labelledby="evidence-heading">
      <div className="section-title">
        <div>
          <span>Shared district analyses</span>
          <h2 id="evidence-heading">Component evidence</h2>
        </div>
      </div>
      <div className="evidence-grid">
        {HOTEL_COMPONENTS.map((name) => {
          const component = ranking.components[name];
          if (!component) return null;
          return (
            <article key={name}>
              <h3>{HOTEL_COMPONENT_LABELS[name]}</h3>
              <dl>
                <div>
                  <dt>Unit</dt>
                  <dd>{component.unit === "C" ? "°C" : component.unit}</dd>
                </div>
                {component.threshold_celsius !== null && (
                  <div>
                    <dt>Threshold</dt>
                    <dd>{component.threshold_celsius} °C</dd>
                  </div>
                )}
                <div>
                  <dt>Coverage</dt>
                  <dd>
                    {component.coverage === null
                      ? "Not reported"
                      : `${Math.round(component.coverage * 100)}%`}
                  </dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>{component.confidence ?? "Not reported"}</dd>
                </div>
                <div>
                  <dt>Provenance</dt>
                  <dd>{component.provenance ?? "Unavailable"}</dd>
                </div>
              </dl>
              {component.provenance_details && (
                <p>
                  Data date:{" "}
                  {String(component.provenance_details.data_date ?? "unknown")};
                  source:{" "}
                  {String(component.provenance_details.source ?? "unknown")}
                </p>
              )}
              {component.caveats.map((caveat) => (
                <p key={caveat}>{caveat}</p>
              ))}
              {component.missing_reason && <p>{component.missing_reason}</p>}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function HotelRankingScreen() {
  const { hotelLocation, setRanking } = useAppState();
  const { status, ranking, load } = useHotelRequest();
  if (!hotelLocation) return <Navigate to="/hotels/location" replace />;
  const result = ranking?.ranking;
  return (
    <section className="screen result-screen">
      <div className="screen-heading compact">
        <span className="step-label">Hotel ranking</span>
        <h1>{ranking?.district_name ?? hotelLocation.name}</h1>
        <p>
          Lower candidate-relative exposure ranks ahead. This is not an absolute
          objective score.
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
              {ranking.reason ??
                "Coverage is insufficient for a representative ranking."}
            </DegradedNotice>
          )}
          {result && (
            <>
              <article className="weights-summary">
                <SlidersHorizontal size={20} />
                <div>
                  <strong>Current weighting: {result.weight_label}</strong>
                  <p>
                    {HOTEL_COMPONENTS.map(
                      (name) =>
                        `${HOTEL_COMPONENT_LABELS[name]} ${Math.round(result.weights[name] * 100)}%`
                    ).join(" · ")}
                  </p>
                </div>
              </article>
              <WeightEditor
                initialWeights={{
                  night: 0.35,
                  hot_hours: 0.25,
                  persistence: 0.2,
                  day: 0.2,
                }}
                onApply={(weights) =>
                  setRanking(
                    rerankHotels(
                      ranking,
                      weights,
                      weights.night === 0.35 &&
                        weights.hot_hours === 0.25 &&
                        weights.persistence === 0.2 &&
                        weights.day === 0.2
                        ? "product defaults"
                        : "custom"
                    )
                  )
                }
              />
              <div className="hotel-list">
                {result.hotels.map((hotel) => {
                  const id = `${hotel.identity.object_type}:${hotel.identity.object_id}`;
                  const tied =
                    result.hotels.filter(
                      (candidate) =>
                        candidate.rank !== null && candidate.rank === hotel.rank
                    ).length > 1;
                  return (
                    <article className="hotel-card" key={id}>
                      <span className="rank-number">{hotel.rank ?? "–"}</span>
                      <div className="hotel-main">
                        <div>
                          <h2>{hotel.name}</h2>
                          <p>
                            {hotel.relative_percentile === null ||
                            hotel.relative_percentile === undefined
                              ? "Unranked: incomplete component evidence"
                              : `${Math.round(hotel.relative_percentile)}th percentile for lower modeled exposure`}
                          </p>
                          {tied && (
                            <span className="tie-chip">
                              Tied at this position
                            </span>
                          )}
                        </div>
                        <HotelComponents hotel={hotel} />
                      </div>
                      <Link
                        aria-label={`View details for ${hotel.name}`}
                        to={`/hotels/${id}`}
                      >
                        <ArrowRight size={20} />
                      </Link>
                    </article>
                  );
                })}
              </div>
            </>
          )}
          <EvidenceSummary ranking={ranking} />
        </>
      )}
    </section>
  );
}

export function HotelDetailScreen() {
  const { ranking } = useAppState();
  const { hotelId } = useParams();
  const hotel = ranking?.ranking?.hotels.find(
    (candidate) =>
      `${candidate.identity.object_type}:${candidate.identity.object_id}` ===
      hotelId
  );
  if (!ranking || !hotel) return <Navigate to="/hotels/results" replace />;
  const selectedRanking = ranking;
  const resultSetToken = selectedRanking.result_set_token;
  const [anchor, setAnchor] = useState(32);
  const [enrichment, setEnrichment] = useState<Awaited<
    ReturnType<typeof dataClient.requestEnrichment>
  > | null>(null);
  const [loading, setLoading] = useState(false);
  const targetId = `${hotel.identity.object_type}:${hotel.identity.object_id}`;
  async function loadEnvironment() {
    if (!resultSetToken) return;
    setLoading(true);
    try {
      setEnrichment(
        await dataClient.requestEnrichment(
          "environment",
          targetId,
          resultSetToken,
          anchor
        )
      );
    } catch (error) {
      setEnrichment({
        status: "success",
        kind: "environment",
        target_id: targetId,
        state: "unavailable",
        reason: error instanceof Error ? error.message : "request_failed",
        base_result: {},
        usage: { requested_calls: 0, completed_calls: 0 },
        provenance: null,
        limitations: [],
        payload: null,
      });
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="screen narrow-screen">
      <div className="screen-heading">
        <span className="step-label">Hotel evidence</span>
        <h1>{hotel.name}</h1>
        <p>
          {hotel.rank === null
            ? "Unranked because component evidence is incomplete."
            : `Rank ${hotel.rank} within this candidate set under ${ranking.ranking?.weight_label}.`}
        </p>
      </div>
      <article className="local-score">
        <HotelIcon size={25} />
        <div>
          <span>Relative aggregate</span>
          <strong>
            {hotel.relative_aggregate?.toFixed(3) ?? "Unavailable"}
          </strong>
          <small>
            Dimensionless percentile aggregate; no mixed-unit raw values are
            summed.
          </small>
        </div>
      </article>
      <div className="assignment-evidence">
        {HOTEL_COMPONENTS.map((name) => {
          const component = hotel.components[name];
          return (
            <article key={name}>
              <h2>{HOTEL_COMPONENT_LABELS[name]}</h2>
              <strong>{formatValue(component)}</strong>
              <dl>
                <div>
                  <dt>Assignment quality</dt>
                  <dd>{component.quality.replaceAll("_", " ")}</dd>
                </div>
                <div>
                  <dt>Tile resolution</dt>
                  <dd>{component.tile_resolution_m} m</dd>
                </div>
                <div>
                  <dt>Distance</dt>
                  <dd>
                    {component.distance_m === null
                      ? "Not reported"
                      : `${component.distance_m} m`}
                  </dd>
                </div>
                {component.threshold_celsius !== null && (
                  <div>
                    <dt>Threshold</dt>
                    <dd>{component.threshold_celsius} °C</dd>
                  </div>
                )}
                <div>
                  <dt>Coverage</dt>
                  <dd>
                    {component.coverage === null
                      ? "Not reported"
                      : `${Math.round(component.coverage * 100)}%`}
                  </dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>
                    {component.coverage === null
                      ? "Not reported"
                      : component.coverage >= 0.95
                        ? "High"
                        : component.coverage >= 0.7
                          ? "Limited"
                          : "Insufficient"}
                  </dd>
                </div>
                <div>
                  <dt>Provenance</dt>
                  <dd>{component.provenance}</dd>
                </div>
              </dl>
              {component.caveats?.map((caveat) => (
                <p key={caveat}>{caveat}</p>
              ))}
            </article>
          );
        })}
      </div>
      <article className="local-score" aria-live="polite">
        <div>
          <span>Optional environmental context</span>
          <label>
            Temperature anchor °C
            <input
              type="number"
              value={anchor}
              onChange={(event) => setAnchor(Number(event.target.value))}
            />
          </label>
          <button
            type="button"
            onClick={loadEnvironment}
            disabled={loading || !resultSetToken}
          >
            {loading ? "Loading context..." : "Load environmental context"}
          </button>
          {enrichment && (
            <p>
              {enrichment.state === "available"
                ? "Environmental context available."
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
      <Link className="text-link" to="/hotels/results">
        Return to hotel ranking
      </Link>
    </section>
  );
}
