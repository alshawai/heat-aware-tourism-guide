import { useCallback, useEffect, useRef, useState } from "react";
import { dataClient } from "../../services/dataClient";
import type {
  ExecutionMode,
  TripAnalysisRequest,
  TripAnalysisResponse,
  TripSetup,
} from "../../types";
import { singleHourWindow } from "./timeWindow";

export type AnalysisPhase = "idle" | "submitting" | "failed";

/**
 * Session cache of completed trip analyses.
 *
 * Every live `/api/trip/analyze` costs billable FortyGuard activities and the
 * server cache is write-through only, so an identical repeat request bills
 * again. Holding responses here at module scope means the cache survives
 * navigation without re-rendering anything, and a traveler who steps back to an
 * hour they already looked at pays nothing. Because the key covers the whole
 * request, a hit can never describe a different trip, so the application never
 * needs to clear it.
 */
const analysisCache = new Map<string, TripAnalysisResponse>();

/**
 * Full-request cache key.
 *
 * Deliberately not `request_identity`: the server builds that from mode, date,
 * and window only, so it collides across different endpoints, guidance
 * preferences, and execution modes. Keying on it would serve a traveler an
 * analysis computed for endpoints they have since moved.
 */
export function requestCacheKey(request: TripAnalysisRequest): string {
  return JSON.stringify([
    request.mode,
    request.execution_mode,
    request.date,
    request.start_hour,
    request.end_hour,
    request.cautious,
    request.origin_latitude.toFixed(6),
    request.origin_longitude.toFixed(6),
    request.destination_latitude.toFixed(6),
    request.destination_longitude.toFixed(6),
    request.landmark_name,
    request.district_name,
  ]);
}

/** Exposed for tests. The application never clears the cache. */
export function resetTripAnalysisCache() {
  analysisCache.clear();
}

/**
 * Derive the wire request from the traveler's setup.
 *
 * A curated setup already holds the canonical Menger/Alamo endpoints and names,
 * so no field needs a per-mode branch here; `_validate_trip_mode` on the server
 * compares those exact values.
 */
export function buildTripRequest(
  setup: TripSetup,
  executionMode: ExecutionMode,
  window: { startHour: number; endHour: number } = {
    startHour: setup.startHour,
    endHour: setup.endHour,
  }
): TripAnalysisRequest {
  return {
    mode: setup.tripMode,
    origin_latitude: setup.origin.latitude,
    origin_longitude: setup.origin.longitude,
    destination_latitude: setup.destination.latitude,
    destination_longitude: setup.destination.longitude,
    landmark_name: setup.destination.name,
    district_name: setup.destination.context,
    date: setup.date,
    start_hour: window.startHour,
    end_hour: window.endHour,
    cautious: setup.cautious,
    execution_mode: executionMode,
  };
}

/** The single-hour request an hour override sends. */
export function buildHourOverrideRequest(
  setup: TripSetup,
  executionMode: ExecutionMode,
  hour: number
): TripAnalysisRequest {
  return buildTripRequest(setup, executionMode, singleHourWindow(hour));
}

/**
 * Run one billable trip analysis and report its phase.
 *
 * The request is never aborted. Aborting cannot un-bill provider work already
 * in flight, and it would drop the response before it reached the cache, so the
 * next identical request would bill a second time. Instead a version counter
 * ignores results the caller no longer wants while the cache still records them.
 */
export function useTripAnalysis() {
  const [phase, setPhase] = useState<AnalysisPhase>("idle");
  const versionRef = useRef(0);
  const liveRef = useRef(true);

  useEffect(() => {
    liveRef.current = true;
    return () => {
      liveRef.current = false;
    };
  }, []);

  const current = useCallback(
    (version: number) => liveRef.current && version === versionRef.current,
    []
  );

  const run = useCallback(
    async (
      request: TripAnalysisRequest
    ): Promise<TripAnalysisResponse | null> => {
      const version = (versionRef.current += 1);
      const key = requestCacheKey(request);
      const cached = analysisCache.get(key);
      if (cached) {
        if (current(version)) setPhase("idle");
        return cached;
      }
      setPhase("submitting");
      try {
        const response = await dataClient.analyzeTripAnalysis(request);
        if (response.state !== "error") {
          analysisCache.set(key, response);
        }
        if (!current(version)) return null;
        if (response.state === "error") {
          setPhase("failed");
          return null;
        }
        setPhase("idle");
        return response;
      } catch {
        if (current(version)) setPhase("failed");
        return null;
      }
    },
    [current]
  );

  const reset = useCallback(() => {
    versionRef.current += 1;
    setPhase("idle");
  }, []);

  return { phase, run, reset };
}
