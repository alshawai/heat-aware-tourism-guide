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

export type ExecutionMode = "fixture" | "live";

export type TripAnalysisRequest = {
  mode: "curated";
  origin_latitude: number;
  origin_longitude: number;
  destination_latitude: number;
  destination_longitude: number;
  landmark_name: "The Alamo";
  district_name: "Downtown San Antonio";
  date: string;
  hour: number;
  cautious: boolean;
  execution_mode: ExecutionMode;
};

export type TripAnalysisResponse = {
  request_identity: string;
  mode: "curated";
  execution_mode: ExecutionMode;
  state: "success" | "degraded" | "unavailable" | "error";
  best_time:
    | ({ heat_interpretation?: HeatInterpretation } & Record<string, unknown>)
    | null;
  hotels: Record<string, unknown> | null;
  routes: Record<string, unknown> | null;
  unavailable: { reason: string; recoverable: boolean } | null;
  degraded_reasons: Record<string, string> | null;
};

export type HeatInterpretation = {
  metric: "tcm" | "heat_index_celsius";
  value_celsius: number | null;
  band: string | null;
  band_label: string;
  action_band: string | null;
  guidance_policy: "standard" | "cautious";
  is_actual_heat_index: boolean;
  policy_applied: string;
};

export type CuratedTripSetup = {
  date: string;
  hour: number;
  cautious: boolean;
};
