import { scenarioLocations } from "../mocks/data";
import { mockHotelRanking } from "../mocks/mockHotelRanking";
import { mockTripAnalyze } from "../mocks/mockTripAnalyze";
import type {
  HealthResponse,
  HotelRankRequest,
  HotelRankResponse,
  LocationSelection,
  RequestOptions,
  TripAnalysisRequest,
  TripAnalysisResponse,
  EnrichmentKind,
  EnrichmentResponse,
  PlaceSearchResponse,
} from "../types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isResultSection(value: unknown) {
  return value === null || isObject(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: string[]) {
  const actual = Object.keys(value);
  return (
    actual.length === expected.length &&
    actual.every((key) => expected.includes(key))
  );
}

function isNullableFiniteNumber(value: unknown) {
  return (
    value === null || (typeof value === "number" && Number.isFinite(value))
  );
}

function validEnvironment(value: unknown) {
  if (
    !isObject(value) ||
    !Array.isArray(value.entries) ||
    value.entries.length === 0 ||
    typeof value.timezone !== "string" ||
    value.timezone.length === 0 ||
    typeof value.temperature_anchor_celsius !== "number" ||
    !Number.isFinite(value.temperature_anchor_celsius) ||
    typeof value.warning !== "string" ||
    !isObject(value.provenance)
  ) {
    return false;
  }
  const provenance = value.provenance;
  return (
    value.entries.every(
      (entry) =>
        isObject(entry) &&
        typeof entry.valid_time === "string" &&
        !Number.isNaN(Date.parse(entry.valid_time)) &&
        isNullableFiniteNumber(entry.heat_index_celsius) &&
        isNullableFiniteNumber(entry.humidity_percent) &&
        isObject(entry.parameters) &&
        Object.values(entry.parameters).every(isNullableFiniteNumber)
    ) &&
    typeof provenance.source === "string" &&
    typeof provenance.data_date === "string" &&
    (provenance.source === "synthesized"
      ? provenance.retrieved_at === null
      : provenance.retrieved_at !== null &&
        typeof provenance.retrieved_at === "string" &&
        !Number.isNaN(Date.parse(provenance.retrieved_at))) &&
    typeof provenance.provider === "string" &&
    typeof provenance.response_status === "string" &&
    typeof provenance.fresh === "boolean" &&
    (provenance.activity_id === null ||
      typeof provenance.activity_id === "string") &&
    isObject(provenance.request_configuration)
  );
}

function isHotelRankResponse(value: unknown): value is HotelRankResponse {
  return (
    isObject(value) &&
    (value.state === "available" || value.state === "unavailable") &&
    typeof value.district_name === "string" &&
    (value.execution_mode === "fixture" || value.execution_mode === "live") &&
    typeof value.discovered_count === "number" &&
    typeof value.usable_count === "number" &&
    isObject(value.components) &&
    (value.ranking === null ||
      (isObject(value.ranking) &&
        isObject(value.ranking.weights) &&
        typeof value.ranking.weight_label === "string" &&
        Array.isArray(value.ranking.hotels)))
  );
}

function validUnavailable(value: unknown) {
  return (
    isObject(value) &&
    typeof value.reason === "string" &&
    value.reason.length > 0 &&
    typeof value.recoverable === "boolean" &&
    (value.code === undefined || typeof value.code === "string") &&
    (value.action === undefined ||
      value.action === null ||
      typeof value.action === "string")
  );
}

function validReasons(value: unknown): value is Record<string, string> {
  return (
    isObject(value) &&
    Object.keys(value).length > 0 &&
    Object.entries(value).every(
      ([key, reason]) =>
        ["best_time", "hotels", "routes"].includes(key) &&
        typeof reason === "string" &&
        reason.length > 0
    )
  );
}

function validHeatInterpretation(value: unknown) {
  const noaaBands = [
    "below_caution",
    "caution",
    "extreme_caution",
    "danger",
    "extreme_danger",
  ];
  const providerBands = [
    "provider_lower",
    "provider_moderate",
    "provider_higher",
    "provider_very_high",
  ];
  const bandLabels: Record<string, string> = {
    below_caution: "Below NOAA caution",
    caution: "Caution",
    extreme_caution: "Extreme caution",
    danger: "Danger",
    extreme_danger: "Extreme danger",
    provider_lower: "Lower provider temperature",
    provider_moderate: "Moderate provider temperature",
    provider_higher: "Higher provider temperature",
    provider_very_high: "Very high provider temperature",
  };
  if (!isObject(value)) return false;
  const expectedBands =
    value.metric === "heat_index_celsius" ? noaaBands : providerBands;
  const actualHeatIndex =
    value.metric === "heat_index_celsius" &&
    typeof value.value_celsius === "number";
  const hasValue = typeof value.value_celsius === "number";
  const expectedThreshold =
    expectedBands[value.guidance_policy === "cautious" ? 1 : 2];
  const expectedAction =
    typeof value.band === "string" &&
    expectedBands.indexOf(value.band) >=
      expectedBands.indexOf(expectedThreshold);
  const expectedPolicy =
    value.guidance_policy === "cautious"
      ? "cautious_guidance_one_band_earlier"
      : "standard_heat_guidance";
  const expectedUnavailableLabel =
    value.metric === "heat_index_celsius"
      ? "NOAA Heat Index unavailable"
      : "Provider temperature unavailable";
  const expectedUnavailablePolicy =
    value.metric === "heat_index_celsius"
      ? "no_heat_index_available"
      : "metric_unavailable";
  return (
    (value.metric === "tcm" || value.metric === "heat_index_celsius") &&
    (value.value_celsius === null || typeof value.value_celsius === "number") &&
    (value.band === null || expectedBands.includes(String(value.band))) &&
    ((value.band === null && typeof value.band_label === "string") ||
      value.band_label === bandLabels[String(value.band)]) &&
    (value.action_threshold_band === null ||
      expectedBands.includes(String(value.action_threshold_band))) &&
    (value.guidance_policy === "standard" ||
      value.guidance_policy === "cautious") &&
    value.is_actual_heat_index === actualHeatIndex &&
    value.noaa_heat_index_available === actualHeatIndex &&
    (hasValue
      ? value.band !== null &&
        value.action_threshold_band === expectedThreshold &&
        value.action_required === expectedAction &&
        value.policy_applied === expectedPolicy
      : value.band === null &&
        value.action_threshold_band === null &&
        value.action_required === false &&
        value.band_label === expectedUnavailableLabel &&
        value.policy_applied === expectedUnavailablePolicy) &&
    typeof value.policy_applied === "string" &&
    value.policy_applied.length > 0
  );
}

function isNonNegativeInteger(value: unknown) {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isUnitFraction(value: unknown) {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1
  );
}

function validApiProvenance(value: unknown) {
  return (
    isObject(value) &&
    typeof value.source === "string" &&
    typeof value.data_date === "string" &&
    ["sufficient", "insufficient"].includes(String(value.confidence)) &&
    (value.source === "synthesized"
      ? value.retrieved_at === null
      : value.retrieved_at !== null &&
        typeof value.retrieved_at === "string" &&
        !Number.isNaN(Date.parse(value.retrieved_at))) &&
    typeof value.transformation_version === "string" &&
    typeof value.provider === "string" &&
    typeof value.response_status === "string" &&
    isObject(value.request_configuration) &&
    typeof value.fresh === "boolean" &&
    (value.coverage === null || isUnitFraction(value.coverage)) &&
    (value.note === null || typeof value.note === "string") &&
    (value.activity_id === null || typeof value.activity_id === "string")
  );
}

const hotelComponents = ["night", "hot_hours", "persistence", "day"];

function validHotels(value: unknown) {
  if (value === null) return true;
  if (
    !isObject(value) ||
    !Array.isArray(value.ranked) ||
    !isNonNegativeInteger(value.usable_count) ||
    value.usable_count !== value.ranked.length ||
    !isNonNegativeInteger(value.discovered_count) ||
    !validApiProvenance(value.provenance) ||
    !isObject(value.weights) ||
    !isObject(value.component_units) ||
    !isObject(value.enrichment) ||
    !hasExactKeys(value, [
      "ranked",
      "weights",
      "usable_count",
      "discovered_count",
      "provenance",
      "enrichment",
      "component_units",
      "component_temporal_metadata",
    ]) ||
    !hasExactKeys(value.weights, hotelComponents) ||
    !hasExactKeys(value.component_units, hotelComponents) ||
    !hasExactKeys(value.enrichment, ["state", "code", "reason"])
  ) {
    return false;
  }
  const weights = value.weights as Record<string, unknown>;
  const componentUnits = value.component_units as Record<string, unknown>;
  const discoveredCount = value.discovered_count as number;
  if (
    !hotelComponents.every(
      (component) =>
        typeof weights[component] === "number" &&
        Number.isFinite(weights[component]) &&
        Number(weights[component]) >= 0
    ) ||
    Math.abs(
      hotelComponents.reduce(
        (sum, component) => sum + Number(weights[component]),
        0
      ) - 1
    ) > 0.001 ||
    componentUnits.night !== "C" ||
    componentUnits.day !== "C" ||
    componentUnits.hot_hours !== "hours" ||
    componentUnits.persistence !== "hours" ||
    discoveredCount < Number(value.usable_count)
  ) {
    return false;
  }
  const enrichment = value.enrichment;
  const enrichmentValid =
    enrichment.state === "unavailable"
      ? enrichment.code === "optional_provider_failure" &&
        typeof enrichment.reason === "string" &&
        enrichment.reason.length > 0
      : ["available", "not_requested"].includes(String(enrichment.state)) &&
        enrichment.code === null &&
        enrichment.reason === null;
  const temporal = value.component_temporal_metadata;
  const temporalValid =
    temporal === null ||
    (isObject(temporal) &&
      ["night", "day"].every((component) => {
        const metadata = temporal[component];
        return (
          isObject(metadata) &&
          hasExactKeys(metadata, [
            "start",
            "end",
            "timezone",
            "interval",
            "temporal_basis",
            "provider_window_validated",
            "caveat_code",
          ]) &&
          typeof metadata.start === "string" &&
          typeof metadata.end === "string" &&
          typeof metadata.timezone === "string" &&
          metadata.interval === "[start,end)" &&
          typeof metadata.temporal_basis === "string" &&
          typeof metadata.provider_window_validated === "boolean" &&
          typeof metadata.caveat_code === "string"
        );
      }));
  return (
    enrichmentValid &&
    temporalValid &&
    value.ranked.every((hotel) => {
      if (!isObject(hotel) || !isObject(hotel.components)) return false;
      const components = hotel.components;
      return (
        hasExactKeys(hotel, [
          "identity",
          "components",
          "score",
          "percentile",
          "tie_group",
        ]) &&
        hasExactKeys(components, hotelComponents) &&
        typeof hotel.identity === "string" &&
        hotelComponents.every(
          (component) =>
            typeof components[component] === "number" &&
            Number.isFinite(components[component])
        ) &&
        typeof hotel.score === "number" &&
        Number.isFinite(hotel.score) &&
        typeof hotel.percentile === "number" &&
        hotel.percentile >= 0 &&
        hotel.percentile <= 100 &&
        isNonNegativeInteger(hotel.tie_group)
      );
    })
  );
}

function validRouteGeometry(value: unknown) {
  return (
    Array.isArray(value) &&
    value.length >= 2 &&
    value.every(
      (point) =>
        Array.isArray(point) &&
        point.length === 2 &&
        point.every(
          (coordinate) =>
            typeof coordinate === "number" && Number.isFinite(coordinate)
        ) &&
        point[0] >= -180 &&
        point[0] <= 180 &&
        point[1] >= -90 &&
        point[1] <= 90
    )
  );
}

function validShadeProvenance(value: Record<string, unknown>) {
  const building = value.building_provenance ?? null;
  const solar = value.solar_provenance ?? null;
  if (building !== null && !isObject(building)) return false;
  if (solar !== null && !isObject(solar)) return false;
  // Buildings are only ever acquired against a resolved solar position.
  if (building !== null && solar === null) return false;
  const modeledShadeStates = [
    "shade_shadiest_recommended",
    "shade_only_route_recommended",
  ];
  if (modeledShadeStates.includes(String(value.decision_state))) {
    return building !== null;
  }
  // Night needs the sun's position to justify itself, and acquires no buildings.
  if (value.decision_state === "nighttime_coolest_recommended") {
    return solar !== null && building === null;
  }
  return true;
}

function validExplicitRoutes(value: Record<string, unknown>) {
  const routeSetStates = [
    "alternatives_returned",
    "single_route",
    "no_suitable_returned_route",
  ];
  const decisionStates = [
    "mild_shortest_recommended",
    "shade_required",
    "shade_shadiest_recommended",
    "shade_only_route_recommended",
    "nighttime_coolest_recommended",
    "insufficient_shade_comparison_required",
    "heat_unavailable",
    "no_suitable_returned_route",
  ];
  if (
    !routeSetStates.includes(String(value.route_set_state)) ||
    !decisionStates.includes(String(value.decision_state)) ||
    !Array.isArray(value.alternatives) ||
    !isObject(value.routing_provenance) ||
    !validShadeProvenance(value)
  ) {
    return false;
  }
  if (value.route_set_state === "no_suitable_returned_route") {
    return (
      value.decision_state === "no_suitable_returned_route" &&
      value.alternatives.length === 0 &&
      value.recommended_id === null
    );
  }
  if (
    (value.route_set_state === "single_route" &&
      value.alternatives.length !== 1) ||
    (value.route_set_state === "alternatives_returned" &&
      value.alternatives.length < 2)
  ) {
    return false;
  }
  const heatUnavailable = value.decision_state === "heat_unavailable";
  const alternativesValid = value.alternatives.every(
    (route) =>
      isObject(route) &&
      validRouteGeometry(route.geometry) &&
      typeof route.identity === "string" &&
      typeof route.distance_m === "number" &&
      typeof route.duration_s === "number" &&
      isUnitFraction(route.building_coverage) &&
      isUnitFraction(route.building_explicit_fraction) &&
      isUnitFraction(route.building_inferred_levels_fraction) &&
      isUnitFraction(route.building_unknown_fraction) &&
      isNonNegativeInteger(route.building_explicit_count) &&
      isNonNegativeInteger(route.building_inferred_levels_count) &&
      isNonNegativeInteger(route.building_unknown_count) &&
      isNonNegativeInteger(route.dropped_building_geometry_count) &&
      Array.isArray(route.shade_limitations) &&
      route.shade_limitations.every(
        (limitation) => typeof limitation === "string" && limitation.length > 0
      ) &&
      typeof route.recommended === "boolean" &&
      (heatUnavailable
        ? route.heat_value === null && route.heat_interpretation === null
        : typeof route.heat_value === "number" &&
          validHeatInterpretation(route.heat_interpretation) &&
          isObject(route.heat_interpretation) &&
          route.heat_interpretation.metric === route.heat_metric &&
          route.heat_interpretation.value_celsius === route.heat_value)
  );
  const recommended = value.alternatives.filter(
    (route) => isObject(route) && route.recommended === true
  );
  const finalDecisionStates = [
    "shade_shadiest_recommended",
    "shade_only_route_recommended",
    "nighttime_coolest_recommended",
  ];
  const noRecommendationStates = [
    "shade_required",
    "insufficient_shade_comparison_required",
    "heat_unavailable",
    "no_suitable_returned_route",
  ];
  return (
    alternativesValid &&
    (value.decision_state === "mild_shortest_recommended" ||
    finalDecisionStates.includes(String(value.decision_state))
      ? typeof value.recommended_id === "string" && recommended.length === 1
      : noRecommendationStates.includes(String(value.decision_state))
        ? value.recommended_id === null && recommended.length === 0
        : false)
  );
}

function validRoutes(value: unknown) {
  if (value === null) return true;
  if (!isObject(value)) return false;
  if (value.route_set_state !== undefined && value.route_set_state !== null) {
    return validExplicitRoutes(value);
  }
  if (
    !validHeatInterpretation(value.heat_interpretation) ||
    !isObject(value.heat_interpretation) ||
    value.heat_interpretation.metric !== value.heat_metric ||
    value.heat_interpretation.value_celsius !== value.corridor_heat_value ||
    !Array.isArray(value.alternatives)
  ) {
    return false;
  }
  return value.alternatives.every(
    (route) =>
      isObject(route) &&
      validHeatInterpretation(route.heat_interpretation) &&
      isObject(route.heat_interpretation) &&
      route.heat_interpretation.metric === route.heat_metric &&
      route.heat_interpretation.value_celsius === route.heat_value
  );
}

function validBestTime(value: unknown) {
  if (value === null) return true;
  if (
    !isObject(value) ||
    !validHeatInterpretation(value.heat_interpretation) ||
    !Array.isArray(value.hourly) ||
    typeof value.hourly_coverage !== "number" ||
    typeof value.recommendation_hour !== "number" ||
    typeof value.recommendation_reason !== "string" ||
    !["exact", "inconsistent", "unavailable"].includes(
      String(value.temporal_evidence)
    ) ||
    !(
      value.recommendation_time === null ||
      (typeof value.recommendation_time === "string" &&
        !Number.isNaN(Date.parse(value.recommendation_time)))
    ) ||
    !(
      value.recommendation_timezone === null ||
      (typeof value.recommendation_timezone === "string" &&
        value.recommendation_timezone.length > 0)
    ) ||
    !(
      value.recommended_hour_tcm_celsius === null ||
      typeof value.recommended_hour_tcm_celsius === "number"
    ) ||
    !isObject(value.provenance) ||
    !(
      value.environmental_concerns === null ||
      Array.isArray(value.environmental_concerns)
    )
  ) {
    return false;
  }
  return (value.environmental_concerns ?? []).every(
    (profile) =>
      isObject(profile) &&
      typeof profile.hour === "number" &&
      typeof profile.primary_thermal_value === "number" &&
      ["tcm", "heat_index_celsius"].includes(
        String(profile.primary_thermal_metric)
      ) &&
      Array.isArray(profile.concerns) &&
      profile.concerns.every(
        (concern) =>
          isObject(concern) &&
          typeof concern.parameter === "string" &&
          typeof concern.available === "boolean" &&
          ["none", "elevated", "high", "not_reported"].includes(
            String(concern.concern_level)
          )
      )
  );
}

function isTripAnalysisResponse(
  value: unknown,
  request: TripAnalysisRequest
): value is TripAnalysisResponse {
  const modern = isObject(value) && value.schema_version === "trip-contract-v2";
  const modernEnvelopeKeys = [
    "schema_version",
    "state",
    "best_time",
    "hotels",
    "routes",
    "unavailable",
    "degraded_reasons",
    "request_identity",
    "mode",
    "execution_mode",
  ];
  if (
    modern &&
    !hasExactKeys(
      value,
      value.result_set_token === undefined
        ? modernEnvelopeKeys
        : [...modernEnvelopeKeys, "result_set_token"]
    )
  ) {
    return false;
  }
  if (
    !isObject(value) ||
    value.request_identity !==
      `${request.mode}:${request.date}:${request.start_hour}-${request.end_hour}` ||
    value.mode !== request.mode ||
    value.execution_mode !== request.execution_mode ||
    !(
      value.result_set_token === undefined ||
      typeof value.result_set_token === "string"
    ) ||
    !(modern
      ? ["success", "degraded", "unavailable"].includes(String(value.state))
      : [
          "series_ready",
          "success",
          "degraded",
          "unavailable",
          "error",
        ].includes(String(value.state))) ||
    !(modern
      ? value.environment === undefined
      : value.environment === null || validEnvironment(value.environment)) ||
    !validBestTime(value.best_time) ||
    !(modern ? validHotels(value.hotels) : isResultSection(value.hotels)) ||
    !validRoutes(value.routes)
  ) {
    return false;
  }
  const hasResults = Boolean(value.best_time || value.hotels || value.routes);
  if (value.state === "series_ready") {
    return Boolean(
      validEnvironment(value.environment) &&
      !hasResults &&
      value.unavailable === null &&
      value.degraded_reasons === null
    );
  }
  if (!modern && value.environment !== null) return false;
  if (value.state === "success") {
    return Boolean(
      value.best_time &&
      value.hotels &&
      value.routes &&
      value.unavailable === null &&
      value.degraded_reasons === null
    );
  }
  if (value.state === "degraded") {
    const reasons = value.degraded_reasons;
    if (!validReasons(reasons)) return false;
    if (modern) {
      return hasResults && value.unavailable === null;
    }
    const expectedReasons = [
      ...(!value.best_time ? ["best_time"] : []),
      ...(!value.hotels ? ["hotels"] : []),
      ...(!value.routes ? ["routes"] : []),
      ...(isObject(value.routes) &&
      (value.routes.confidence === "insufficient" ||
        [
          "shade_required",
          "insufficient_shade_comparison_required",
          "heat_unavailable",
          "no_suitable_returned_route",
        ].includes(String(value.routes.decision_state)) ||
        value.routes.route_set_state === "single_route")
        ? ["routes"]
        : []),
    ];
    return (
      hasResults &&
      value.unavailable === null &&
      Object.keys(reasons).length === expectedReasons.length &&
      expectedReasons.every((section) => section in reasons)
    );
  }
  return (
    !hasResults &&
    validUnavailable(value.unavailable) &&
    value.degraded_reasons === null
  );
}

async function readJson(response: Response) {
  const body = (await response.json()) as unknown;
  if (!response.ok) {
    const detail = isObject(body) && isObject(body.detail) ? body.detail : body;
    const error = new Error(
      isObject(detail) && typeof detail.error === "string"
        ? detail.error
        : "Request failed"
    ) as Error & { code?: string };
    if (isObject(detail) && typeof detail.error_kind === "string")
      error.code = detail.error_kind;
    throw error;
  }
  return body;
}

function isEnrichmentResponse(value: unknown): value is EnrichmentResponse {
  return (
    isObject(value) &&
    value.status === "success" &&
    ["environment", "satellite_canopy", "street_view"].includes(
      String(value.kind)
    ) &&
    typeof value.target_id === "string" &&
    ["available", "unavailable", "not_requested"].includes(
      String(value.state)
    ) &&
    isObject(value.usage) &&
    Array.isArray(value.limitations)
  );
}

type ColdStartRetryReason = "timeout" | "network" | "server";

type ResilienceOptions = {
  signal?: AbortSignal;
  /** Maximum cold-start retries after the first attempt. 0 (default) = plain fetch. */
  retries?: number;
  /** Per-attempt timeout in ms. Omitted (default) = no timeout, exactly like fetch. */
  timeoutMs?: number;
  onRetry?: (info: { attempt: number; reason: ColdStartRetryReason }) => void;
};

// A free-tier host (e.g. Render) spins the service down after idle and then
// stalls or returns a proxy error for ~1 minute while it wakes. These statuses
// and any transport failure are therefore treated as "the server is waking up"
// and retried, rather than surfaced immediately as a terminal error.
const COLD_START_STATUSES = new Set([502, 503, 504]);
const DEFAULT_COLD_START_RETRIES = 5;
const DEFAULT_ATTEMPT_TIMEOUT_MS = 12_000;
const COLD_START_BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 10_000];

function coldStartBackoff(attempt: number): number {
  return COLD_START_BACKOFF_MS[
    Math.min(attempt - 1, COLD_START_BACKOFF_MS.length - 1)
  ];
}

function abortableDelay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

// fetch that can survive a cold start. Resilience is fully opt-in: with the
// defaults it makes a single attempt with no timeout, identical to plain fetch.
// When retries/timeoutMs are supplied, timeouts, transport failures, and
// 502/503/504 responses are retried with bounded backoff; a caller-initiated
// abort is always propagated at once and never retried.
async function resilientFetch(
  input: string,
  init: RequestInit,
  resilience: ResilienceOptions = {}
): Promise<Response> {
  const {
    signal: externalSignal,
    retries = 0,
    timeoutMs,
    onRetry,
  } = resilience;
  for (let attempt = 1; ; attempt += 1) {
    const controller = new AbortController();
    const timer =
      timeoutMs === undefined
        ? undefined
        : setTimeout(
            () =>
              controller.abort(
                new DOMException("Request timed out", "TimeoutError")
              ),
            timeoutMs
          );
    const forwardAbort = () => controller.abort(externalSignal?.reason);
    if (externalSignal) {
      if (externalSignal.aborted) controller.abort(externalSignal.reason);
      else
        externalSignal.addEventListener("abort", forwardAbort, { once: true });
    }
    let retryReason: ColdStartRetryReason | null = null;
    let response: Response | null = null;
    try {
      const result = await fetch(input, { ...init, signal: controller.signal });
      if (COLD_START_STATUSES.has(result.status) && attempt <= retries) {
        retryReason = "server";
      } else {
        response = result;
      }
    } catch (error) {
      // The caller cancelled (e.g. component unmounted): never retry.
      if (externalSignal?.aborted) throw error;
      if (attempt > retries) throw error;
      retryReason =
        error instanceof DOMException && error.name === "TimeoutError"
          ? "timeout"
          : "network";
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      externalSignal?.removeEventListener("abort", forwardAbort);
    }
    if (response) return response;
    if (retryReason) {
      onRetry?.({ attempt, reason: retryReason });
      await abortableDelay(coldStartBackoff(attempt), externalSignal);
    }
  }
}

export const dataClient = {
  analyzeTrip: mockTripAnalyze,
  async getHealth(resilience: ResilienceOptions = {}): Promise<HealthResponse> {
    const value = await readJson(
      await resilientFetch("/health", {}, resilience)
    );
    if (
      !isObject(value) ||
      value.status !== "ok" ||
      (value.mode !== "fixture" && value.mode !== "live") ||
      (value.deployment_profile !== "local" &&
        value.deployment_profile !== "public-fixture" &&
        value.deployment_profile !== "protected-live") ||
      (value.execution_capability !== "fixture-only" &&
        value.execution_capability !== "fixture-and-live")
    ) {
      throw new Error("Invalid health response");
    }
    return value as HealthResponse;
  },
  async analyzeTripAnalysis(
    request: TripAnalysisRequest
  ): Promise<TripAnalysisResponse> {
    const value = await readJson(
      await fetch("/api/trip/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      })
    );
    if (!isTripAnalysisResponse(value, request)) {
      throw new Error("Invalid trip analysis response");
    }
    return value;
  },
  async searchPlaces(
    query: string,
    signal?: AbortSignal
  ): Promise<PlaceSearchResponse> {
    const value = await readJson(
      await fetch(`/api/places/search?q=${encodeURIComponent(query)}`, {
        signal,
      })
    );
    if (!isObject(value) || !Array.isArray(value.places))
      throw new Error("Invalid place search response");
    return value as PlaceSearchResponse;
  },
  async rankHotels(
    location: LocationSelection,
    options: RequestOptions = {}
  ): Promise<HotelRankResponse> {
    // Explicit mock scenarios remain available for deterministic previews and tests.
    if (options.mode !== undefined || options.scenario !== undefined) {
      return mockHotelRanking(location, options);
    }
    const onColdStartRetry = options.onColdStartRetry;
    // The hotel flow opts into full cold-start handling: a free-tier instance
    // may be waking, so give each attempt a timeout and retry with backoff.
    const resilience: ResilienceOptions = {
      signal: options.signal,
      retries: DEFAULT_COLD_START_RETRIES,
      timeoutMs: DEFAULT_ATTEMPT_TIMEOUT_MS,
      onRetry: onColdStartRetry
        ? (info) => onColdStartRetry(info.attempt)
        : undefined,
    };
    const health = await this.getHealth(resilience);
    const request: HotelRankRequest = {
      // The current hotel flow is scoped to the canonical district AOI.
      district_name: "Downtown San Antonio",
      execution_mode: health.mode,
    };
    const value = await readJson(
      await resilientFetch(
        "/api/hotels/rank",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request),
        },
        resilience
      )
    );
    if (!isHotelRankResponse(value)) {
      throw new Error("Invalid hotel ranking response");
    }
    return value;
  },
  async requestEnrichment(
    kind: EnrichmentKind,
    targetId: string,
    resultSetToken: string,
    temperatureAnchor?: number,
    signal?: AbortSignal
  ): Promise<EnrichmentResponse> {
    const path =
      kind === "environment"
        ? `/api/hotels/${encodeURIComponent(targetId)}/environment`
        : kind === "satellite_canopy"
          ? `/api/routes/${encodeURIComponent(targetId)}/canopy`
          : `/api/routes/${encodeURIComponent(targetId)}/street-view`;
    const body: Record<string, unknown> = { result_set_token: resultSetToken };
    if (temperatureAnchor !== undefined)
      body.temperature_anchor_celsius = temperatureAnchor;
    const value = await readJson(
      await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      })
    );
    if (!isEnrichmentResponse(value))
      throw new Error("Invalid enrichment response");
    return value;
  },
  searchLocations(query: string, locations = scenarioLocations) {
    const normalized = query.trim().toLowerCase();
    return locations.filter(
      (location) =>
        !normalized ||
        `${location.name} ${location.context}`
          .toLowerCase()
          .includes(normalized)
    );
  },
};
