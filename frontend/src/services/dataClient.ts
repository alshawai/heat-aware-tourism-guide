import { scenarioLocations } from "../mocks/data";
import { mockHotelRanking } from "../mocks/mockHotelRanking";
import { mockTripAnalyze } from "../mocks/mockTripAnalyze";
import type {
  ExecutionMode,
  HotelRankRequest,
  HotelRankResponse,
  LocationSelection,
  RequestOptions,
  TripAnalysisRequest,
  TripAnalysisResponse,
} from "../types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isResultSection(value: unknown) {
  return value === null || isObject(value);
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
    typeof value.recoverable === "boolean"
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

function validRoutes(value: unknown) {
  if (value === null) return true;
  if (
    !isObject(value) ||
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
  return (
    value === null ||
    (isObject(value) && validHeatInterpretation(value.heat_interpretation))
  );
}

function isTripAnalysisResponse(
  value: unknown,
  request: TripAnalysisRequest
): value is TripAnalysisResponse {
  if (
    !isObject(value) ||
    value.request_identity !==
      `${request.mode}:${request.date}:${request.hour}` ||
    value.mode !== request.mode ||
    value.execution_mode !== request.execution_mode ||
    !["success", "degraded", "unavailable", "error"].includes(
      String(value.state)
    ) ||
    !validBestTime(value.best_time) ||
    !isResultSection(value.hotels) ||
    !validRoutes(value.routes)
  ) {
    return false;
  }
  const hasResults = Boolean(value.best_time || value.hotels || value.routes);
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
    const expectedReasons = [
      ...(!value.best_time ? ["best_time"] : []),
      ...(!value.hotels ? ["hotels"] : []),
      ...(!value.routes ? ["routes"] : []),
      ...(isObject(value.routes) && value.routes.confidence === "insufficient"
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
  if (!response.ok) throw new Error("Request failed");
  return response.json() as Promise<unknown>;
}

export const dataClient = {
  analyzeTrip: mockTripAnalyze,
  async getHealth(signal?: AbortSignal): Promise<ExecutionMode> {
    const value = await readJson(await fetch("/health", { signal }));
    if (
      !isObject(value) ||
      value.status !== "ok" ||
      (value.mode !== "fixture" && value.mode !== "live")
    ) {
      throw new Error("Invalid health response");
    }
    return value.mode;
  },
  async analyzeCuratedTrip(
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
  async rankHotels(
    location: LocationSelection,
    options: RequestOptions = {}
  ): Promise<HotelRankResponse> {
    // Explicit mock scenarios remain available for deterministic previews and tests.
    if (options.mode !== undefined || options.scenario !== undefined) {
      return mockHotelRanking(location, options);
    }
    const executionMode = await this.getHealth(options.signal);
    const request: HotelRankRequest = {
      // The current hotel flow is scoped to the canonical district AOI.
      district_name: "Downtown San Antonio",
      execution_mode: executionMode,
    };
    const value = await readJson(
      await fetch("/api/hotels/rank", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal: options.signal,
      })
    );
    if (!isHotelRankResponse(value)) {
      throw new Error("Invalid hotel ranking response");
    }
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
