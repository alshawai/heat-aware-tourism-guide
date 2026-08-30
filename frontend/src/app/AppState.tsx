import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { dataClient } from "../services/dataClient";
import type {
  HealthResponse,
  HotelRankResponse,
  LocationSelection,
  MockMode,
  TripAnalysisResponse,
  TripResults,
  TripSetup,
} from "../types";

export type HealthState =
  | { status: "checking" | "unavailable" }
  | ({ status: "available" } & Omit<HealthResponse, "status">);

/** The canonical trip: the validated Menger Hotel to The Alamo journey. */
export const CANONICAL_ORIGIN: LocationSelection = {
  id: "menger",
  name: "Menger Hotel",
  context: "San Antonio, TX",
  latitude: 29.4245914,
  longitude: -98.4864288,
};
export const CANONICAL_DESTINATION: LocationSelection = {
  id: "alamo",
  name: "The Alamo",
  context: "Downtown San Antonio",
  latitude: 29.425833,
  longitude: -98.485833,
};

/** The tolerance `_validate_trip_mode` in `app/api.py` applies to a curated trip. */
const CANONICAL_TOLERANCE = 1e-5;

function samePlace(a: LocationSelection, b: LocationSelection) {
  return (
    Math.abs(a.latitude - b.latitude) <= CANONICAL_TOLERANCE &&
    Math.abs(a.longitude - b.longitude) <= CANONICAL_TOLERANCE
  );
}

/**
 * Whether a setup is still the validated Menger Hotel to The Alamo journey.
 *
 * One "Explore trip" flow lets the traveler move either pin, but the wire
 * contract still carries `mode`, and fixture replay only holds the curated
 * scenario. So the request's mode is derived from the endpoints rather than from
 * a screen the traveler no longer sees.
 *
 * `id` cannot decide this: a searched place carries a provider id and a map click
 * carries a coordinate id, so a traveler could land on the canonical point with a
 * different id. The check therefore mirrors `_validate_trip_mode` exactly — the
 * same coordinate tolerance, plus the destination name and context the request
 * sends as `landmark_name` and `district_name` — because anything the server
 * would reject as non-canonical must not be labelled curated here.
 */
export function isCanonicalTrip(
  setup: Pick<TripSetup, "origin" | "destination">
): boolean {
  return (
    samePlace(setup.origin, CANONICAL_ORIGIN) &&
    samePlace(setup.destination, CANONICAL_DESTINATION) &&
    setup.destination.name === CANONICAL_DESTINATION.name &&
    setup.destination.context === CANONICAL_DESTINATION.context
  );
}

const DEFAULT_TRIP_SETUP: TripSetup = {
  origin: CANONICAL_ORIGIN,
  destination: CANONICAL_DESTINATION,
  date: "2026-08-23",
  startHour: 8,
  endHour: 20,
  cautious: false,
};

/**
 * The analysis the map, route cards, and route detail should render.
 *
 * An hour override supersedes the baseline because its route heat and solar
 * geometry were computed for the hour the traveler actually chose.
 */
export function activeAnalysis(
  results: TripResults | null
): TripAnalysisResponse | null {
  if (!results) return null;
  return results.override?.response ?? results.baseline;
}

type AppState = {
  health: HealthState;
  tripSetup: TripSetup;
  tripResults: TripResults | null;
  hotelLocation: LocationSelection | null;
  ranking: HotelRankResponse | null;
  mode: MockMode;
};

type AppContextValue = AppState & {
  refreshHealth: () => Promise<void>;
  setTripSetup: (value: TripSetup) => void;
  clearTripResults: () => void;
  setBaseline: (value: TripAnalysisResponse) => void;
  setOverride: (hour: number, value: TripAnalysisResponse) => void;
  clearOverride: () => void;
  setHotelLocation: (value: LocationSelection) => void;
  setRanking: (value: HotelRankResponse | null) => void;
  setMode: (value: MockMode) => void;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const queryMode = new URLSearchParams(window.location.search).get(
    "state"
  ) as MockMode | null;
  const [state, setState] = useState<AppState>({
    health: { status: "checking" },
    tripSetup: DEFAULT_TRIP_SETUP,
    tripResults: null,
    hotelLocation: null,
    ranking: null,
    mode: queryMode ?? "success",
  });

  // One free health probe per session, shared by the shell chrome and every
  // screen, so no screen spends a second call to learn the same thing.
  const refreshHealth = useCallback(async (signal?: AbortSignal) => {
    setState((current) => ({ ...current, health: { status: "checking" } }));
    try {
      const value = await dataClient.getHealth(signal);
      setState((current) => ({
        ...current,
        health: {
          status: "available",
          deployment_profile: value.deployment_profile,
          mode: value.mode,
          execution_capability: value.execution_capability,
        },
      }));
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setState((current) => ({
        ...current,
        health: { status: "unavailable" },
      }));
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refreshHealth(controller.signal);
    return () => controller.abort();
  }, [refreshHealth]);

  const value = useMemo<AppContextValue>(
    () => ({
      ...state,
      refreshHealth: () => refreshHealth(),
      // Any setup edit invalidates both analyses: they describe a trip the
      // traveler is no longer asking about.
      setTripSetup: (tripSetup) =>
        setState((current) => ({ ...current, tripSetup, tripResults: null })),
      clearTripResults: () =>
        setState((current) => ({ ...current, tripResults: null })),
      setBaseline: (baseline) =>
        setState((current) => ({
          ...current,
          tripResults: { baseline, override: null },
        })),
      setOverride: (hour, response) =>
        setState((current) =>
          current.tripResults
            ? {
                ...current,
                tripResults: {
                  ...current.tripResults,
                  override: { hour, response },
                },
              }
            : current
        ),
      clearOverride: () =>
        setState((current) =>
          current.tripResults
            ? {
                ...current,
                tripResults: { ...current.tripResults, override: null },
              }
            : current
        ),
      setHotelLocation: (hotelLocation) =>
        setState((current) => ({ ...current, hotelLocation, ranking: null })),
      setRanking: (ranking) => setState((current) => ({ ...current, ranking })),
      setMode: (mode) =>
        setState((current) => ({ ...current, mode, ranking: null })),
    }),
    [refreshHealth, state]
  );
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useAppState() {
  const value = useContext(AppContext);
  if (!value) throw new Error("App state must be used inside AppProvider");
  return value;
}
