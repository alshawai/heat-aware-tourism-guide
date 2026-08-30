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
  source: "mock" | "fixture" | "provider" | "cache";
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

export type HotelComponentName = "night" | "hot_hours" | "persistence" | "day";

export type HotelComponentMetadata = {
  component: HotelComponentName;
  available: boolean;
  unit: "C" | "hours";
  threshold_celsius: number | null;
  provenance: string | null;
  coverage: number | null;
  confidence: "high" | "limited" | "insufficient" | null;
  caveats: string[];
  provenance_details?: Record<string, unknown> | null;
  missing_reason: string | null;
};

export type HotelComponentAssignment = {
  component: HotelComponentName;
  value: number | null;
  unit: "C" | "hours";
  threshold_celsius: number | null;
  provenance: string;
  tile_id: string | null;
  tile_resolution_m: number;
  quality: string;
  distance_m: number | null;
  coverage: number | null;
  caveats: string[];
  correlation_key?: string | null;
  percentile: number | null;
};

export type HotelRankingHotel = {
  identity: { object_type: "node" | "way" | "relation"; object_id: number };
  name: string;
  complete: boolean;
  relative_aggregate: number | null;
  rank: number | null;
  components: Record<HotelComponentName, HotelComponentAssignment>;
  /** Candidate-relative percentile derived locally from relative_aggregate. */
  relative_percentile?: number | null;
};

export type HotelRanking = {
  weights: Record<HotelComponentName, number>;
  weight_label: "product defaults" | "custom";
  complete_candidate_count: number;
  ranked_output: boolean;
  hotels: HotelRankingHotel[];
};

export type HotelRankResponse = {
  state: "available" | "unavailable";
  district_name: string;
  execution_mode: ExecutionMode;
  reason: string | null;
  discovered_count: number;
  usable_count: number;
  components: Partial<Record<HotelComponentName, HotelComponentMetadata>>;
  ranking: HotelRanking | null;
};

export type HotelRankRequest = {
  district_name: string;
  execution_mode: ExecutionMode;
};
export type RequestOptions = {
  scenario?: string;
  mode?: MockMode;
  signal?: AbortSignal;
};

export type ExecutionMode = "fixture" | "live";

export type ApiProvenance = {
  source: string;
  data_date: string;
  confidence: "sufficient" | "insufficient";
  retrieved_at: string;
  transformation_version: string;
  provider: string;
  response_status: string;
  request_configuration: Record<string, unknown>;
  fresh: boolean;
  coverage: number | null;
  note: string | null;
  activity_id: string | null;
};

export type EnvironmentSeriesEntry = {
  valid_time: string;
  heat_index_celsius: number | null;
  humidity_percent: number | null;
  parameters: Record<string, number | null>;
};

export type EnvironmentSeriesResult = {
  entries: EnvironmentSeriesEntry[];
  timezone: string;
  temperature_anchor_celsius: number;
  warning: string;
  provenance: ApiProvenance;
};

export type ParameterConcern = {
  parameter: string;
  value: number | null;
  unit: string;
  available: boolean;
  concern_level: "none" | "elevated" | "high" | "not_reported";
  threshold: number | null;
  threshold_source: string | null;
};

export type HourlyConcernProfile = {
  hour: number;
  concerns: ParameterConcern[];
  elevated_count: number;
  high_count: number;
  not_reported_count: number;
  primary_thermal_value: number;
  primary_thermal_metric: "tcm" | "heat_index_celsius";
};

export type TemporalEvidenceState = "exact" | "inconsistent" | "unavailable";

export type BestTimeResult = {
  hourly: Array<{
    hour: number;
    metric: {
      value: number;
      unit: string;
      label: "provider_tcm" | "noaa_heat_index";
      is_actual_heat_index: boolean;
    };
  }>;
  hourly_coverage: number;
  recommendation_hour: number;
  recommendation_reason: string;
  metric_label: "provider_tcm" | "noaa_heat_index";
  provenance: ApiProvenance;
  heat_interpretation?: HeatInterpretation;
  environmental_concerns: HourlyConcernProfile[] | null;
  recommended_hour_tcm_celsius: number | null;
  exceedance_hours: number | null;
  persistence_hours: number | null;
  framing_threshold_celsius: number | null;
  framing_direction: "above" | "below" | null;
  recommendation_time: string | null;
  recommendation_timezone: string | null;
  temporal_evidence: TemporalEvidenceState;
};

export type RankedHotelResult = {
  identity: string;
  components: Record<HotelComponentName, number>;
  score: number;
  percentile: number;
  tie_group: number;
};

export type OptionalEnrichment =
  | { state: "available" | "not_requested"; code: null; reason: null }
  | {
      state: "unavailable";
      code: "optional_provider_failure";
      reason: string;
    };

export type HotelComponentTemporalMetadata = {
  start: string;
  end: string;
  timezone: string;
  interval: "[start,end)";
  temporal_basis: string;
  provider_window_validated: boolean;
  caveat_code: string;
};

export type HotelRankingResult = {
  ranked: RankedHotelResult[];
  weights: Record<HotelComponentName, number>;
  usable_count: number;
  discovered_count: number;
  provenance: ApiProvenance;
  enrichment: OptionalEnrichment;
  component_units: Record<HotelComponentName, "C" | "hours">;
  component_temporal_metadata: Record<
    "night" | "day",
    HotelComponentTemporalMetadata
  > | null;
};

export type TripAnalysisRequest = {
  mode: "curated" | "exploratory";
  origin_latitude: number;
  origin_longitude: number;
  destination_latitude: number;
  destination_longitude: number;
  landmark_name: string;
  district_name: string;
  date: string;
  start_hour: number;
  end_hour: number;
  cautious: boolean;
  execution_mode: ExecutionMode;
};

export type RouteSetState =
  "alternatives_returned" | "single_route" | "no_suitable_returned_route";

export type RouteDecisionState =
  | "mild_shortest_recommended"
  | "shade_required"
  | "shade_shadiest_recommended"
  | "shade_only_route_recommended"
  | "nighttime_coolest_recommended"
  | "insufficient_shade_comparison_required"
  | "heat_unavailable"
  | "no_suitable_returned_route";

export type RouteHeatSource = "landmark_reuse" | "shared_corridor";

export type RouteOptionResult = {
  identity: string;
  distance_m: number;
  duration_s: number;
  geometry: [number, number][] | null;
  heat_value: number | null;
  heat_unit: "C";
  heat_metric: "tcm" | "heat_index_celsius";
  heat_status: "elevated" | "not_elevated" | null;
  heat_coverage: number | null;
  heat_source: RouteHeatSource | null;
  heat_interpretation: HeatInterpretation | null;
  modeled_shade_percent: number | null;
  shade_confidence: "sufficient" | "insufficient" | "not_applicable" | null;
  building_coverage: number;
  building_explicit_fraction: number;
  building_inferred_levels_fraction: number;
  building_unknown_fraction: number;
  building_explicit_count: number;
  building_inferred_levels_count: number;
  building_unknown_count: number;
  dropped_building_geometry_count: number;
  shade_limitations: string[];
  recommended: boolean;
  recommendation_reason: string | null;
  shade_model_label: string | null;
};

export type RouteComparisonResult = {
  alternatives: RouteOptionResult[];
  recommended_id: string | null;
  lowest_heat_route_id: string | null;
  reason: string;
  heat_status: "elevated" | "not_elevated" | null;
  corridor_heat_value: number | null;
  heat_metric: "tcm" | "heat_index_celsius";
  heat_unit: "C";
  coverage: number;
  confidence: "sufficient" | "insufficient";
  comparison_scope: "returned alternatives";
  route_set_state: RouteSetState | null;
  decision_state: RouteDecisionState | null;
  provenance: ApiProvenance;
  routing_provenance: ApiProvenance | null;
  heat_provenance: ApiProvenance | null;
  building_provenance: ApiProvenance | null;
  solar_provenance: ApiProvenance | null;
  fallback_reason: string | null;
  heat_interpretation: HeatInterpretation | null;
};

export type TripAnalysisResponse = {
  schema_version?: "trip-contract-v2";
  request_identity: string;
  mode: "curated" | "exploratory";
  execution_mode: ExecutionMode;
  state: "series_ready" | "success" | "degraded" | "unavailable" | "error";
  environment?: EnvironmentSeriesResult | null;
  best_time: BestTimeResult | null;
  hotels: HotelRankingResult | null;
  routes: RouteComparisonResult | null;
  unavailable: {
    reason: string;
    recoverable: boolean;
    code?: string;
    action?: string | null;
  } | null;
  degraded_reasons: Record<string, string> | null;
};

export type HeatInterpretation = {
  metric: "tcm" | "heat_index_celsius";
  value_celsius: number | null;
  band: HeatBand | null;
  band_label: string;
  action_threshold_band: HeatBand | null;
  guidance_policy: "standard" | "cautious";
  is_actual_heat_index: boolean;
  noaa_heat_index_available: boolean;
  action_required: boolean;
  policy_applied: string;
};

export type HeatBand =
  | "below_caution"
  | "caution"
  | "extreme_caution"
  | "danger"
  | "extreme_danger"
  | "provider_lower"
  | "provider_moderate"
  | "provider_higher"
  | "provider_very_high";

export type CuratedTripSetup = {
  date: string;
  startHour: number;
  endHour: number;
  cautious: boolean;
};

export type PlaceSearchResponse = { places: LocationSelection[] };
