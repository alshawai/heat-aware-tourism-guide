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
      `${request.mode}:${request.date}:${request.hour}` ||
    value.mode !== request.mode ||
    value.execution_mode !== request.execution_mode ||
    !["success", "degraded", "unavailable", "error"].includes(
      String(value.state)
    ) ||
    !isResultSection(value.best_time) ||
    !isResultSection(value.hotels) ||
    !isResultSection(value.routes)
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
