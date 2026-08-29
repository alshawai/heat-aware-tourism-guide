import { scenarioLocations } from "../mocks/data";
import { mockHotelRanking } from "../mocks/mockHotelRanking";
import { mockTripAnalyze } from "../mocks/mockTripAnalyze";
import type {
  ExecutionMode,
  TripAnalysisRequest,
  TripAnalysisResponse,
} from "../types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isResultSection(value: unknown) {
  return value === null || isObject(value);
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
    typeof provenance.retrieved_at === "string" &&
    typeof provenance.provider === "string" &&
    typeof provenance.response_status === "string" &&
    typeof provenance.fresh === "boolean" &&
    (provenance.activity_id === null ||
      typeof provenance.activity_id === "string") &&
    isObject(provenance.request_configuration)
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

function isTripAnalysisResponse(
  value: unknown,
  request: TripAnalysisRequest
): value is TripAnalysisResponse {
  if (
    !isObject(value) ||
    value.request_identity !==
      `${request.mode}:${request.date}:${request.start_hour}-${request.end_hour}` ||
    value.mode !== request.mode ||
    value.execution_mode !== request.execution_mode ||
    !["series_ready", "success", "degraded", "unavailable", "error"].includes(
      String(value.state)
    ) ||
    !(value.environment === null || validEnvironment(value.environment)) ||
    !isResultSection(value.best_time) ||
    !isResultSection(value.hotels) ||
    !isResultSection(value.routes)
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
  if (value.environment !== null) return false;
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
  rankHotels: mockHotelRanking,
  searchLocations(query: string) {
    const normalized = query.trim().toLowerCase();
    return scenarioLocations.filter(
      (location) =>
        !normalized ||
        `${location.name} ${location.context}`
          .toLowerCase()
          .includes(normalized)
    );
  },
};
