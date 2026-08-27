export type ResultState =
  "loading" | "success" | "degraded" | "empty" | "error";
export type MockMode = "success" | "degraded" | "empty" | "error";

export type LocationSelection = {
  id: string;
  name: string;
  context: string;
  latitude: number;
  longitude: number;
};

export type Provenance = {
  source: "mock" | "fixture";
  dataDate: string;
  confidence?: string;
  coverage?: string;
  note?: string;
};

export type HourPoint = {
  hour: string;
  value: number;
  comfort: "lower" | "moderate" | "higher";
};
export type RouteAlternative = {
  id: string;
  name: string;
  distanceMeters: number;
  durationMinutes: number;
  heatStatus: string;
  shadePercent: number;
  geometry: [number, number][];
  steps: string[];
};
export type TripResponse = {
  location: LocationSelection;
  date: string;
  metric: { label: string; unit: string; actualHeatIndex: boolean };
  hourly: HourPoint[];
  recommendation: { window: string; reason: string };
  routes: RouteAlternative[];
  provenance: { bestTime: Provenance; routes: Provenance };
};

export type HotelComponent = {
  label: string;
  value: number;
  contribution: number;
};
export type Hotel = {
  id: string;
  name: string;
  percentile: number;
  tieLabel?: string;
  components: HotelComponent[];
  latitude: number;
  longitude: number;
};
export type HotelResponse = {
  location: LocationSelection;
  hotels: Hotel[];
  usableCount: number;
  weights: Record<string, number>;
  provenance: Provenance;
};
export type RequestOptions = {
  scenario?: string;
  mode?: MockMode;
  signal?: AbortSignal;
};
