import type {
  ApiProvenance,
  RouteComparisonResult,
  RouteHeatSource,
  RouteOptionResult,
} from "../../types";

/** `"Unavailable"` for a null metric; never a fabricated zero. */
export function formatMetric(value: number | null, unit?: string) {
  return value === null
    ? "Unavailable"
    : `${value.toFixed(1)}${unit ? ` ${unit}` : ""}`;
}

export function formatHour(validTime: string, timezone: string) {
  return `${validTime.slice(11, 16)} ${timezone}`;
}

export function formatParameterName(name: string) {
  return name
    .replaceAll("_", " ")
    .replaceAll(":", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function parameterUnit(name: string) {
  if (name.includes("humidity") || name.includes("cloud_cover")) return "%";
  if (name.includes("precipitation")) return "mm";
  if (name.includes("irradiance")) return "W/m2";
  if (name.includes("elevation")) return "m";
  if (name.includes("index") || name.includes("temperature")) return "C";
  return "";
}

export function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function formatClockHour(hour: number) {
  return `${String(hour).padStart(2, "0")}:00`;
}

export function formatDistanceAndDuration(route: RouteOptionResult) {
  return `${(route.distance_m / 1000).toFixed(2)} km · ${Math.round(
    route.duration_s / 60
  )} min`;
}

/** Route geometry arrives as `[lon, lat]`; Leaflet wants `[lat, lon]`. */
export function leafletPoint(point: [number, number]): [number, number] {
  return [point[1], point[0]];
}

export function heatLabel(route: RouteOptionResult) {
  if (route.heat_value === null) return "Heat unavailable";
  return `${route.heat_value.toFixed(1)} °C · ${
    route.heat_status === "elevated" ? "Elevated heat" : "Mild heat"
  }`;
}

export function coverageLabel(
  route: RouteOptionResult,
  comparison: RouteComparisonResult
) {
  const coverage =
    route.heat_coverage ?? route.building_coverage ?? comparison.coverage;
  return `Coverage ${Math.round(coverage * 100)}% · ${comparison.confidence} confidence`;
}

export function heatMetricLabel(metric: "tcm" | "heat_index_celsius") {
  return metric === "tcm" ? "provider TCM" : "NOAA Heat Index";
}

export function heatSourceLabel(source: RouteHeatSource | null) {
  if (source === "landmark_reuse") return "Retained landmark value";
  if (source === "shared_corridor") return "Shared route corridor";
  return "Unavailable";
}

export function toProvenance(
  value: ApiProvenance,
  comparison: RouteComparisonResult
) {
  return {
    source: value.source === "fixture" ? "fixture" : "provider",
    dataDate: value.data_date,
    confidence: comparison.confidence,
    coverage: `${Math.round(comparison.coverage * 100)}% route coverage`,
    note: "Comparison is limited to returned alternatives. Shade is modeled from building data.",
  } as const;
}
