import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type {
  HotelResponse,
  LocationSelection,
  MockMode,
  TripResponse,
} from "../types";

type AppState = {
  walkLocation: LocationSelection | null;
  walkDate: string;
  trip: TripResponse | null;
  hotelLocation: LocationSelection | null;
  ranking: HotelResponse | null;
  mode: MockMode;
};
type AppContextValue = AppState & {
  setWalkLocation: (value: LocationSelection) => void;
  setWalkDate: (value: string) => void;
  setTrip: (value: TripResponse | null) => void;
  setHotelLocation: (value: LocationSelection) => void;
  setRanking: (value: HotelResponse | null) => void;
  setMode: (value: MockMode) => void;
};
const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const queryMode = new URLSearchParams(window.location.search).get(
    "state"
  ) as MockMode | null;
  const [state, setState] = useState<AppState>({
    walkLocation: null,
    walkDate: "",
    trip: null,
    hotelLocation: null,
    ranking: null,
    mode: queryMode ?? "success",
  });
  const value = useMemo<AppContextValue>(
    () => ({
      ...state,
      setWalkLocation: (walkLocation) =>
        setState((current) => ({ ...current, walkLocation, trip: null })),
      setWalkDate: (walkDate) =>
        setState((current) => ({ ...current, walkDate, trip: null })),
      setTrip: (trip) => setState((current) => ({ ...current, trip })),
      setHotelLocation: (hotelLocation) =>
        setState((current) => ({ ...current, hotelLocation, ranking: null })),
      setRanking: (ranking) => setState((current) => ({ ...current, ranking })),
      setMode: (mode) =>
        setState((current) => ({
          ...current,
          mode,
          trip: null,
          ranking: null,
        })),
    }),
    [state]
  );
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
export function useAppState() {
  const value = useContext(AppContext);
  if (!value) throw new Error("App state must be used inside AppProvider");
  return value;
}
