import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../app/App";
import { resetTripAnalysisCache } from "./useTripAnalysis";

const successResponse = {
  request_identity: "curated:2024-07-15:8-20",
  mode: "curated",
  execution_mode: "fixture",
  state: "success",
  environment: null,
  best_time: {
    hourly: [],
    hourly_coverage: 1,
    recommendation_hour: 9,
    recommendation_reason: "coolest period with no environmental concerns",
    metric_label: "provider_tcm",
    recommended_hour_tcm_celsius: 29,
    exceedance_hours: 4,
    persistence_hours: 2,
    framing_threshold_celsius: 35,
    framing_direction: "above",
    recommendation_time: "2024-07-15T09:00:00-05:00",
    recommendation_timezone: "America/Chicago",
    temporal_evidence: "exact",
    environmental_concerns: [],
    provenance: {
      source: "fixture",
      data_date: "2024-07-15",
      confidence: "sufficient",
      retrieved_at: "2026-08-24T00:00:00Z",
      transformation_version: "best-time-decision-v1",
      provider: "fortyguard",
      response_status: "completed",
      request_configuration: { forecast: false },
      fresh: true,
      coverage: 1,
      note: null,
      activity_id: null,
    },
    heat_interpretation: {
      metric: "tcm",
      value_celsius: 29,
      band: "provider_lower",
      band_label: "Lower provider temperature",
      action_threshold_band: "provider_higher",
      guidance_policy: "standard",
      is_actual_heat_index: false,
      noaa_heat_index_available: false,
      action_required: false,
      policy_applied: "standard_heat_guidance",
    },
  },
  hotels: { ranked: [] },
  routes: {
    alternatives: [],
    heat_metric: "tcm",
    corridor_heat_value: 38,
    heat_interpretation: {
      metric: "tcm",
      value_celsius: 38,
      band: "provider_higher",
      band_label: "Higher provider temperature",
      action_threshold_band: "provider_higher",
      guidance_policy: "standard",
      is_actual_heat_index: false,
      noaa_heat_index_available: false,
      action_required: true,
      policy_applied: "standard_heat_guidance",
    },
  },
  unavailable: null,
  degraded_reasons: null,
};

const routesProvenance = {
  source: "fixture",
  data_date: "2024-07-15",
  confidence: "sufficient",
  retrieved_at: "2026-08-24T00:00:00Z",
  transformation_version: "osrm-route-normalization-v1",
  provider: "osrm",
  response_status: "completed",
  request_configuration: {},
  fresh: true,
  coverage: 1,
  note: null,
  activity_id: null,
};

const solarProvenance = {
  source: "astral",
  data_date: "2024-07-15",
  confidence: "sufficient",
  retrieved_at: "2026-08-24T00:00:00Z",
  transformation_version: "solar-position-v1",
  provider: "astral",
  response_status: "completed",
  request_configuration: {},
  fresh: true,
  coverage: null,
  note: null,
  activity_id: null,
};

const buildingProvenance = {
  source: "fixture",
  data_date: "2026-08-29",
  confidence: "sufficient",
  retrieved_at: "2026-08-24T00:00:00Z",
  transformation_version: "building-v1",
  provider: "overpass",
  response_status: "completed",
  request_configuration: {},
  fresh: false,
  coverage: 1,
  note: null,
  activity_id: null,
};

const routeOption = (
  identity: string,
  {
    distance = 900,
    duration = 720,
    heatValue = 38,
    shadePercent = 60,
    shadeConfidence = "sufficient",
    buildingCoverage = 0.8,
    explicitFraction = 0.6,
    inferredFraction = 0.2,
    unknownFraction = 0.2,
    recommended = false,
    recommendationReason = null,
    limitations = [],
  }: {
    distance?: number;
    duration?: number;
    heatValue?: number;
    shadePercent?: number;
    shadeConfidence?: "sufficient" | "insufficient" | "not_applicable";
    buildingCoverage?: number;
    explicitFraction?: number;
    inferredFraction?: number;
    unknownFraction?: number;
    recommended?: boolean;
    recommendationReason?: string | null;
    limitations?: string[];
  } = {}
) => ({
  identity,
  distance_m: distance,
  duration_s: duration,
  geometry: [
    [-98.49, 29.42],
    [-98.48, 29.43],
  ],
  heat_value: heatValue,
  heat_unit: "C",
  heat_metric: "tcm",
  heat_status: "elevated",
  heat_coverage: 1,
  heat_source: "shared_corridor",
  heat_interpretation: {
    metric: "tcm",
    value_celsius: heatValue,
    band: "provider_higher",
    band_label: "Higher provider temperature",
    action_threshold_band: "provider_higher",
    guidance_policy: "standard",
    is_actual_heat_index: false,
    noaa_heat_index_available: false,
    action_required: true,
    policy_applied: "standard_heat_guidance",
  },
  modeled_shade_percent: shadePercent,
  shade_confidence: shadeConfidence,
  building_coverage: buildingCoverage,
  building_explicit_fraction: explicitFraction,
  building_inferred_levels_fraction: inferredFraction,
  building_unknown_fraction: unknownFraction,
  building_explicit_count: 3,
  building_inferred_levels_count: 1,
  building_unknown_count: 1,
  dropped_building_geometry_count: 0,
  shade_limitations: limitations,
  recommended,
  recommendation_reason: recommendationReason,
  shade_model_label:
    "modeled OSM building-shade estimate, not measured real-world shade",
});

const shadiestRoutes = {
  alternatives: [
    routeOption("route-1", {
      distance: 900,
      shadePercent: 40,
      recommended: false,
    }),
    routeOption("route-2", {
      distance: 1200,
      shadePercent: 75,
      recommended: true,
      recommendationReason: "highest modeled shade among returned routes",
    }),
  ],
  recommended_id: "route-2",
  lowest_heat_route_id: "route-1",
  reason:
    "highest modeled OSM building shade among returned routes is recommended",
  heat_status: "elevated",
  corridor_heat_value: 38,
  heat_metric: "tcm",
  heat_unit: "C",
  coverage: 1,
  confidence: "sufficient",
  comparison_scope: "returned alternatives",
  route_set_state: "alternatives_returned",
  decision_state: "shade_shadiest_recommended",
  provenance: routesProvenance,
  routing_provenance: routesProvenance,
  heat_provenance: routesProvenance,
  building_provenance: buildingProvenance,
  solar_provenance: solarProvenance,
  fallback_reason: null,
  heat_interpretation: {
    metric: "tcm",
    value_celsius: 38,
    band: "provider_higher",
    band_label: "Higher provider temperature",
    action_threshold_band: "provider_higher",
    guidance_policy: "standard",
    is_actual_heat_index: false,
    noaa_heat_index_available: false,
    action_required: true,
    policy_applied: "standard_heat_guidance",
  },
};

const insufficientRoutes = {
  ...shadiestRoutes,
  recommended_id: null,
  decision_state: "insufficient_shade_comparison_required",
  confidence: "insufficient",
  reason:
    "daytime building-shade evidence is insufficient; compare returned route trade-offs",
  fallback_reason:
    "building-height coverage or solar evidence was insufficient",
  alternatives: [
    routeOption("route-1", {
      shadePercent: 70,
      shadeConfidence: "sufficient",
      buildingCoverage: 0.8,
      explicitFraction: 0.7,
      inferredFraction: 0.1,
      unknownFraction: 0.2,
      limitations: ["building search is limited to 250 m around the route"],
    }),
    routeOption("route-2", {
      shadePercent: 45,
      shadeConfidence: "insufficient",
      buildingCoverage: 0.5,
      explicitFraction: 0.4,
      inferredFraction: 0.1,
      unknownFraction: 0.5,
    }),
  ],
};

/** Hours 8..19, coolest at 09:00, hottest at 14:00. */
const HOURLY_VALUES: Record<number, number> = {
  8: 30.4,
  9: 29,
  10: 31.2,
  11: 33.1,
  12: 34.8,
  13: 36.2,
  14: 37.5,
  15: 36.9,
  16: 35.4,
  17: 34,
  18: 32.6,
  19: 31.1,
};

const hourlySeries = Object.entries(HOURLY_VALUES).map(([hour, value]) => ({
  hour: Number(hour),
  metric: {
    value,
    unit: "C",
    label: "provider_tcm",
    is_actual_heat_index: false,
  },
}));

const concernProfile = (
  hour: number,
  { elevated = 0, high = 0, notReported = 0 } = {}
) => ({
  hour,
  concerns: [
    {
      parameter: "apparent_temperature_celsius",
      value: HOURLY_VALUES[hour] + 4,
      unit: "C",
      available: true,
      concern_level: high > 0 ? "high" : elevated > 0 ? "elevated" : "none",
      threshold: 41,
      threshold_source: "noaa_heat_index_caution",
    },
  ],
  elevated_count: elevated,
  high_count: high,
  not_reported_count: notReported,
  primary_thermal_value: HOURLY_VALUES[hour],
  primary_thermal_metric: "tcm",
});

/** A full window response: an hourly series plus two returned routes. */
const seriesResponse = {
  ...successResponse,
  best_time: {
    ...successResponse.best_time,
    hourly: hourlySeries,
    environmental_concerns: [
      concernProfile(9),
      concernProfile(13, { elevated: 2 }),
      concernProfile(14, { high: 1, elevated: 1 }),
    ],
  },
  routes: shadiestRoutes,
};

/** The same trip re-analyzed for 14:00 only. */
const overrideResponse = {
  ...seriesResponse,
  request_identity: "curated:2024-07-15:14-15",
  best_time: {
    ...seriesResponse.best_time,
    hourly: [hourlySeries[6]],
    recommendation_hour: 14,
    recommended_hour_tcm_celsius: 37.5,
    environmental_concerns: [concernProfile(14, { high: 1, elevated: 1 })],
  },
  routes: {
    ...shadiestRoutes,
    // The single-hour analysis returns its own decision: at 14:00 the shortest
    // route is the shadiest one.
    recommended_id: "route-1",
    corridor_heat_value: 41.5,
    heat_interpretation: {
      ...shadiestRoutes.heat_interpretation,
      value_celsius: 41.5,
    },
    alternatives: [
      routeOption("route-1", {
        distance: 900,
        shadePercent: 22,
        heatValue: 41.5,
        recommended: true,
        recommendationReason: "highest modeled shade among returned routes",
      }),
      routeOption("route-2", {
        distance: 1200,
        shadePercent: 18,
        heatValue: 41.5,
      }),
    ],
  },
};

/**
 * The real fixture answer for a narrowed window.
 *
 * Fixture replay only matches the committed 08:00-20:00 scenario, so the server
 * legitimately reports a single hour as unavailable rather than analyzing it.
 */
const refusedOverrideResponse = {
  request_identity: "curated:2024-07-15:14-15",
  mode: "curated",
  execution_mode: "fixture",
  state: "unavailable",
  environment: null,
  best_time: null,
  hotels: null,
  routes: null,
  unavailable: {
    reason: "no matching fixture for the requested trip",
    recoverable: true,
    code: "scenario_unavailable",
    action: "edit_setup_or_use_live_data",
  },
  degraded_reasons: null,
};

const fixtureHealth = {
  status: "ok",
  deployment_profile: "local",
  mode: "fixture",
  execution_capability: "fixture-only",
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(...responses: Array<Response | Promise<Response>>) {
  const fetchMock = vi.fn();
  responses.forEach((response) => fetchMock.mockResolvedValueOnce(response));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Walk from the welcome screen to the trip setup form, as a traveler does. */
async function openSetup(user: ReturnType<typeof userEvent.setup>) {
  render(<App />);
  await user.click(screen.getByRole("link", { name: /Plan a walk/ }));
  const analyze = await screen.findByRole("button", { name: "Analyze trip" });
  // Submission is gated on the health probe, so every flow starts from a
  // settled application mode.
  await waitFor(() => expect(analyze).toBeEnabled());
  return analyze;
}

beforeEach(() => {
  // The cache lives at module scope to protect billable calls across
  // navigation, so it must not leak between tests.
  resetTripAnalysisCache();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("trip setup", () => {
  it("loads fixture mode and submits the complete setup exactly once", async () => {
    const fetchMock = mockFetch(
      jsonResponse(fixtureHealth),
      jsonResponse(successResponse)
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);

    expect(screen.getByText("Fixture replay")).toBeInTheDocument();
    // One flow: the canonical walk is only the prefill, and the map that can
    // move either pin is always on the setup screen.
    expect(
      screen.getByRole("button", { name: "Origin: Menger Hotel" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Destination: The Alamo" })
    ).toBeInTheDocument();
    expect(document.querySelector(".leaflet-container")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Curated trip" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Explore another trip" })
    ).toBeNull();
    expect(screen.getByLabelText("Date")).toHaveValue("2024-07-15");
    expect(screen.getByLabelText("Start time")).toHaveValue("8");
    expect(screen.getByLabelText("End time")).toHaveValue("20");
    expect(screen.getByLabelText(/Cautious guidance/)).not.toBeChecked();
    expect(screen.getByText("08:00 to 19:00")).toBeInTheDocument();
    // The always-present map carries its own United States hint, so this
    // assertion names the setup copy rather than matching both.
    expect(
      screen.getByText(
        /Live provider requests are supported in the United States/
      )
    ).toBeInTheDocument();

    await user.click(analyze);

    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
    expect(screen.getByText("Lower provider temperature")).toBeInTheDocument();
    expect(
      screen.getByText(/29.0 °C provider temperature metric/)
    ).toBeInTheDocument();
    expect(screen.getByText(/NOAA Heat Index unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Recommended visit: 09:00")).toBeInTheDocument();
    expect(
      screen.getByText("coolest period with no environmental concerns")
    ).toBeInTheDocument();
    expect(screen.getByText(/4.0 hours above 35.0 °C/)).toBeInTheDocument();
    expect(
      screen.getByText(/Fixture replay.*historical.*fresh/i)
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/health", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/trip/analyze",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "curated",
          origin_latitude: 29.4245914,
          origin_longitude: -98.4864288,
          destination_latitude: 29.425833,
          destination_longitude: -98.485833,
          landmark_name: "The Alamo",
          district_name: "Downtown San Antonio",
          date: "2024-07-15",
          start_hour: 8,
          end_hour: 20,
          cautious: false,
          execution_mode: "fixture",
        }),
      })
    );
  });

  it("sends exploratory once an endpoint leaves the canonical pair", async () => {
    // The traveler no longer picks a mode, so the wire mode is derived from the
    // endpoints: fixture replay only matches the canonical pair, and the server
    // rejects `curated` for anything else.
    const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
      void init;
      if (input === "/health") return jsonResponse(fixtureHealth);
      if (input.startsWith("/api/places/search"))
        return jsonResponse({
          places: [
            {
              id: "riverwalk",
              name: "River Walk",
              context: "San Antonio, TX",
              latitude: 29.4252,
              longitude: -98.4861,
            },
          ],
        });
      // The client rejects a response whose identity does not match the request
      // it sent (dataClient.ts:418-421), so an exploratory request needs an
      // exploratory answer.
      return jsonResponse({
        ...successResponse,
        request_identity: "exploratory:2024-07-15:8-20",
        mode: "exploratory",
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.type(screen.getByLabelText("Search places"), "river");
    await user.click(await screen.findByRole("option", { name: /River Walk/ }));
    expect(
      screen.getByRole("button", { name: "Destination: The Alamo" })
    ).toBeInTheDocument();

    await user.click(analyze);

    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
    const analyzeCall = fetchMock.mock.calls.find(
      ([url]) => url === "/api/trip/analyze"
    );
    expect(JSON.parse(String(analyzeCall?.[1]?.body))).toMatchObject({
      mode: "exploratory",
      origin_latitude: 29.4252,
      origin_longitude: -98.4861,
      landmark_name: "The Alamo",
    });
  });

  it("preserves edits and retries when application mode is unavailable", async () => {
    const fetchMock = mockFetch(
      Promise.reject(new Error("offline")),
      jsonResponse({
        status: "ok",
        deployment_profile: "protected-live",
        mode: "live",
        execution_capability: "fixture-and-live",
      })
    );
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole("link", { name: /Plan a walk/ }));

    expect(
      await screen.findByText("Application mode unavailable")
    ).toBeInTheDocument();
    const date = screen.getByLabelText("Date");
    await user.clear(date);
    await user.type(date, "2026-09-01");
    expect(screen.getByRole("button", { name: "Analyze trip" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Check again" }));

    expect(await screen.findByText("Live data")).toBeInTheDocument();
    expect(date).toHaveValue("2026-09-01");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("locks public fixture facts while keeping cautious guidance selectable", async () => {
    const fetchMock = mockFetch(
      jsonResponse({
        status: "ok",
        deployment_profile: "public-fixture",
        mode: "fixture",
        execution_capability: "fixture-only",
      }),
      jsonResponse(seriesResponse)
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);

    expect(screen.getByText("Fixture replay")).toBeInTheDocument();
    expect(screen.getByText("public-fixture")).toBeInTheDocument();
    expect(
      screen.getByText(
        /fixed to the committed scenario: 2024-07-15, 08:00 to 19:00/
      )
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Date")).toBeDisabled();
    expect(screen.getByLabelText("Start time")).toBeDisabled();
    expect(screen.getByLabelText("End time")).toBeDisabled();

    await user.click(screen.getByLabelText(/Cautious guidance/));
    await user.click(analyze);

    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/trip/analyze",
      expect.objectContaining({
        body: expect.stringContaining(
          '"date":"2024-07-15","start_hour":8,"end_hour":20,"cautious":true,"execution_mode":"fixture"'
        ),
      })
    );

    // The hour override spends a second billable analysis, so the public
    // demonstration presents the series without offering one.
    expect(
      screen.getByText(
        /Hour selection is unavailable on the public demonstration/
      )
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^14:00,/ })).toBeNull();
  });

  it("validates fields without submitting or auto-submitting edits", async () => {
    const fetchMock = mockFetch(jsonResponse(fixtureHealth));
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    const date = screen.getByLabelText("Date");
    await user.clear(date);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.click(analyze);

    expect(screen.getByText("Enter a valid date.")).toBeInTheDocument();
    expect(date).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("validates time order and the 12-hour maximum without submitting", async () => {
    const fetchMock = mockFetch(jsonResponse(fixtureHealth));
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    const start = screen.getByLabelText("Start time");
    const end = screen.getByLabelText("End time");

    await user.selectOptions(start, "20");
    await user.click(analyze);
    expect(
      screen.getByText("Start time must be earlier than end time.")
    ).toBeInTheDocument();
    expect(end).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.selectOptions(start, "0");
    await user.selectOptions(end, "13");
    await user.click(analyze);
    expect(
      screen.getByText("The time window cannot exceed 12 hours.")
    ).toBeInTheDocument();
    expect(end).toHaveFocus();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("announces busy state and disables setup controls", async () => {
    let resolveAnalysis!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolveAnalysis = resolve;
    });
    mockFetch(jsonResponse(fixtureHealth), pending);
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    expect(screen.getByRole("status")).toHaveTextContent("Analyzing trip...");
    expect(screen.getByLabelText("Date")).toBeDisabled();
    expect(screen.getByLabelText("Start time")).toBeDisabled();
    expect(screen.getByLabelText("End time")).toBeDisabled();
    expect(screen.getByLabelText(/Cautious guidance/)).toBeDisabled();
    resolveAnalysis(jsonResponse(successResponse));
    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
  });

  it.each([
    [
      "malformed response",
      jsonResponse({ ...successResponse, execution_mode: "live" }),
    ],
    [
      "mismatched request identity",
      jsonResponse({
        ...successResponse,
        request_identity: "curated:2024-07-15:9-20",
      }),
    ],
    [
      "inconsistent degraded response",
      jsonResponse({
        ...successResponse,
        state: "degraded",
        hotels: null,
        degraded_reasons: { routes: "Route confidence is limited." },
      }),
    ],
    ["request failure", jsonResponse({ detail: "failed" }, 503)],
    [
      "domain error",
      jsonResponse({
        ...successResponse,
        state: "error",
        best_time: null,
        hotels: null,
        routes: null,
        unavailable: { reason: "Provider timeout", recoverable: true },
      }),
    ],
  ])("offers a retry after %s", async (_name, failedResponse) => {
    const fetchMock = mockFetch(
      jsonResponse(fixtureHealth),
      failedResponse,
      jsonResponse(successResponse)
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    expect(
      await screen.findByText("We could not analyze this trip.")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });
});

describe("trip results", () => {
  it("accepts and displays the raw nullable environmental series", async () => {
    mockFetch(
      jsonResponse(fixtureHealth),
      jsonResponse({
        ...successResponse,
        state: "series_ready",
        environment: {
          entries: [
            {
              valid_time: "2024-07-15T08:00:00-05:00",
              heat_index_celsius: 31.4,
              humidity_percent: 72.5,
              parameters: {
                heat_index_celsius: 31.4,
                relative_humidity_percent: 72.5,
                apparent_temperature_celsius: 35.1,
              },
            },
            {
              valid_time: "2024-07-15T09:00:00-05:00",
              heat_index_celsius: null,
              humidity_percent: 68,
              parameters: {
                heat_index_celsius: null,
                relative_humidity_percent: 68,
                apparent_temperature_celsius: null,
              },
            },
          ],
          timezone: "GMT-5",
          temperature_anchor_celsius: 34.2,
          warning: "fixed temperature anchor; not a real 24-hour forecast",
          provenance: {
            source: "fixture",
            data_date: "2024-07-15",
            confidence: "sufficient",
            retrieved_at: "2026-08-24T00:00:00Z",
            transformation_version: "environment-series-v1",
            provider: "fortyguard",
            response_status: "completed",
            request_configuration: { forecast: false },
            fresh: true,
            coverage: 1,
            note: null,
            activity_id: null,
          },
        },
        best_time: null,
        hotels: null,
        routes: null,
      })
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    expect(
      await screen.findByRole("region", { name: "Environmental conditions" })
    ).toBeInTheDocument();
    expect(screen.getByText("34.2 C")).toBeInTheDocument();
    expect(screen.getByText("08:00 GMT-5")).toBeInTheDocument();
    expect(screen.getByText("31.4 C")).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    expect(
      screen.getByText("fixed temperature anchor; not a real 24-hour forecast")
    ).toBeInTheDocument();
    expect(screen.queryByText(/best time/i)).not.toBeInTheDocument();
  });

  it("retains degraded detail and clears it when the setup changes", async () => {
    mockFetch(
      jsonResponse(fixtureHealth),
      jsonResponse({
        ...successResponse,
        state: "degraded",
        hotels: null,
        degraded_reasons: {
          hotels: "Hotel ranking is temporarily unavailable.",
        },
      })
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    const outcome = await screen.findByRole("status", {
      name: "Trip analysis outcome",
    });
    expect(
      within(outcome).getByText("Trip analysis ready with limitations")
    ).toBeInTheDocument();
    expect(
      within(outcome).getByText("Hotel ranking is temporarily unavailable.")
    ).toBeInTheDocument();
    expect(screen.getByText("Lower provider temperature")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Edit setup" }));
    const staleSetup = screen.getByRole("button", { name: "Analyze trip" });
    await user.selectOptions(screen.getByLabelText("Start time"), "9");

    // The retained analysis no longer describes the requested trip, so walking
    // back reaches the results route, finds nothing to show, and redirects into
    // a freshly mounted setup screen. That remount is the only visible trace of
    // the round trip, so it is what the wait watches for.
    await user.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Analyze trip" })).not.toBe(
        staleSetup
      )
    );
    expect(
      screen.queryByRole("status", { name: "Trip analysis outcome" })
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Trip analysis ready/)).not.toBeInTheDocument();
  });

  it("shows domain unavailability with recovery guidance", async () => {
    mockFetch(
      jsonResponse(fixtureHealth),
      jsonResponse({
        ...successResponse,
        state: "unavailable",
        best_time: null,
        hotels: null,
        routes: null,
        unavailable: {
          reason: "No fixture matches that date and hour.",
          recoverable: true,
          code: "fixture_miss",
          action: "edit_setup_or_use_live_data",
        },
      })
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    const notice = await screen.findByRole("alert");
    expect(
      within(notice).getByText("No fixture matches that date and hour.")
    ).toBeInTheDocument();
    expect(
      within(notice).getByText(
        "Edit the setup, or ask a maintainer to enable live data."
      )
    ).toBeInTheDocument();
    expect(
      within(notice).getByText("Reported code: fixture_miss")
    ).toBeInTheDocument();

    await user.click(within(notice).getByRole("link", { name: "Edit setup" }));
    expect(
      await screen.findByRole("button", { name: "Analyze trip" })
    ).toBeInTheDocument();
  });

  it("presents recommended modeled route shade with quality evidence", async () => {
    mockFetch(
      jsonResponse(fixtureHealth),
      jsonResponse({ ...successResponse, routes: shadiestRoutes })
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    const comparison = await screen.findByRole("region", {
      name: "Walking routes",
    });
    const heading = within(comparison).getByRole("heading", {
      name: "Shadiest route recommended",
    });
    // The set-level reason is stated beside the heading. Route cards repeat it,
    // so the assertion is scoped rather than global.
    expect(heading.parentElement).toHaveTextContent(
      "highest modeled OSM building shade among returned routes is recommended"
    );
    expect(within(comparison).getAllByText("Recommended route")).toHaveLength(
      1
    );
    expect(within(comparison).getAllByText("Alternative route")).toHaveLength(
      1
    );
    expect(within(comparison).getByText("75%")).toBeInTheDocument();
    expect(within(comparison).getByText("40%")).toBeInTheDocument();
    expect(within(comparison).getAllByText("80%")).toHaveLength(2);
    expect(within(comparison).getAllByText("sufficient")).toHaveLength(2);
    expect(
      within(comparison).getByText(/Modeled OSM building shade, not measured/)
    ).toBeInTheDocument();
    expect(within(comparison).getAllByText(/\d+\.\d{2} km/)).toHaveLength(2);
  });

  it("presents incomplete shade comparisons without a recommendation", async () => {
    mockFetch(
      jsonResponse(fixtureHealth),
      jsonResponse({
        ...successResponse,
        state: "degraded",
        routes: insufficientRoutes,
        degraded_reasons: {
          routes: "Route comparison requires manual trade-off review.",
        },
      })
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    const comparison = await screen.findByRole("region", {
      name: "Walking routes",
    });
    expect(
      within(comparison).getByRole("heading", {
        name: "Compare route trade-offs",
      })
    ).toBeInTheDocument();
    expect(
      within(comparison).getByText(
        "No route is recommended because shade evidence is incomplete."
      )
    ).toBeInTheDocument();
    expect(
      within(comparison).queryByText("Recommended route")
    ).not.toBeInTheDocument();
    expect(within(comparison).getByText("insufficient")).toBeInTheDocument();
    expect(
      within(comparison).getByText(
        "building search is limited to 250 m around the route"
      )
    ).toBeInTheDocument();
    expect(within(comparison).getByText("Explicit 70%")).toBeInTheDocument();
    expect(within(comparison).getAllByText("Inferred 10%")).toHaveLength(2);
    expect(within(comparison).getByText("Unknown 20%")).toBeInTheDocument();
    expect(within(comparison).getByText("Unknown 50%")).toBeInTheDocument();

    // The internal decision token never reaches the traveler; the buildings
    // arrived and only their heights were thin, so the copy says exactly that
    // and does not offer a retry that cannot help.
    const notice = await screen.findByRole("note");
    expect(
      within(notice).getByRole("heading", {
        name: "Routes are listed, but not ranked",
      })
    ).toBeInTheDocument();
    expect(
      within(notice).getByText(/do not publish enough height data/)
    ).toBeInTheDocument();
    expect(
      within(notice).getByText(/will not change this/)
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/insufficient_shade_comparison_required/)
    ).not.toBeInTheDocument();
    // The engineering fragment is not repeated beside the human explanation.
    expect(
      screen.queryByText("Route comparison requires manual trade-off review.")
    ).not.toBeInTheDocument();
  });

  it("distinguishes unreachable building data from thin height coverage", async () => {
    mockFetch(
      jsonResponse(fixtureHealth),
      jsonResponse({
        ...successResponse,
        state: "degraded",
        routes: {
          ...insufficientRoutes,
          building_provenance: {
            ...buildingProvenance,
            source: "unavailable",
            response_status: "unavailable",
            confidence: "insufficient",
            fresh: false,
            coverage: 0,
            note: "overpass request failed",
          },
        },
        degraded_reasons: {
          routes: "modeled building-shade evidence is insufficient",
        },
      })
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    // Fixture replay puts a note on the setup screen too, so the results have
    // to be on screen before the notice can be read unambiguously.
    const comparison = await screen.findByRole("region", {
      name: "Walking routes",
    });
    const notice = screen.getByRole("note");
    expect(
      within(notice).getByText(/could not reach the building data/)
    ).toBeInTheDocument();
    expect(
      within(notice).getByText(/may reach the building data/)
    ).toBeInTheDocument();
    expect(
      within(notice).getByText("overpass request failed")
    ).toBeInTheDocument();
    // The permanent coverage wording must not be shown for a transient failure.
    expect(
      within(notice).queryByText(/do not publish enough height data/)
    ).not.toBeInTheDocument();
    // The routes themselves stay listed, just unranked.
    expect(
      within(comparison).queryByText("Recommended route")
    ).not.toBeInTheDocument();
    expect(within(comparison).getAllByText(/\d+\.\d{2} km/)).toHaveLength(2);
  });
});

describe("custom hour override", () => {
  it("re-analyzes a chosen hour, then serves the repeat from cache", async () => {
    const fetchMock = mockFetch(
      jsonResponse(fixtureHealth),
      jsonResponse(seriesResponse),
      jsonResponse(overrideResponse)
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    const chart = await screen.findByRole("region", {
      name: "Hourly heat by hour",
    });
    expect(within(chart).getAllByRole("button")).toHaveLength(12);
    const recommended = within(chart).getByRole("button", {
      name: /^09:00,.*recommended hour$/,
    });
    expect(recommended).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("40% modeled shade")).toBeInTheDocument();

    // Choosing another hour must not spend an analysis on its own.
    await user.click(within(chart).getByRole("button", { name: /^14:00,/ }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(
      screen.getByRole("group", { name: "Custom hour override" })
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Recalculate for 14:00" })
    );

    expect(
      await screen.findByText("Showing 14:00, not the recommended hour.")
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/trip/analyze",
      expect.objectContaining({
        body: expect.stringContaining(
          '"date":"2024-07-15","start_hour":14,"end_hour":15,"cautious":false,"execution_mode":"fixture"'
        ),
      })
    );
    // The map and cards move to the recalculated hour; the chart keeps the
    // window the traveler originally asked to compare.
    expect(screen.getByText("22% modeled shade")).toBeInTheDocument();
    expect(screen.queryByText("40% modeled shade")).not.toBeInTheDocument();
    expect(within(chart).getAllByRole("button")).toHaveLength(12);
    expect(screen.getByText(/recalculated for 14:00 only/)).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Return to recommended hour/ })
    );
    expect(screen.getByText("40% modeled shade")).toBeInTheDocument();

    // The same hour again is answered from the session cache: no re-billing.
    await user.click(within(chart).getByRole("button", { name: /^14:00,/ }));
    await user.click(
      screen.getByRole("button", { name: "Recalculate for 14:00" })
    );
    expect(
      await screen.findByText("Showing 14:00, not the recommended hour.")
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("keeps the analyzed window when the server declines one hour", async () => {
    const fetchMock = mockFetch(
      jsonResponse(fixtureHealth),
      jsonResponse(seriesResponse),
      jsonResponse(refusedOverrideResponse)
    );
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    const chart = await screen.findByRole("region", {
      name: "Hourly heat by hour",
    });
    await user.click(within(chart).getByRole("button", { name: /^14:00,/ }));
    await user.click(
      screen.getByRole("button", { name: "Recalculate for 14:00" })
    );

    const refusal = await screen.findByRole("alert");
    expect(
      within(refusal).getByRole("heading", {
        name: "14:00 could not be analyzed",
      })
    ).toBeInTheDocument();
    expect(
      within(refusal).getByText("no matching fixture for the requested trip")
    ).toBeInTheDocument();
    expect(
      within(refusal).getByText(
        "Edit the setup, or ask a maintainer to enable live data."
      )
    ).toBeInTheDocument();
    expect(
      within(refusal).getByText(/Everything below still describes 09:00/)
    ).toBeInTheDocument();

    // The refused hour never becomes the active analysis: the recommended
    // hour's routes and its outcome banner are still the ones on screen.
    expect(screen.getByText("40% modeled shade")).toBeInTheDocument();
    expect(screen.getByText("Trip analysis ready")).toBeInTheDocument();
    expect(screen.getByText("Produced by fixture replay.")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Trip analysis unavailable" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Showing 14:00, not the recommended hour.")
    ).not.toBeInTheDocument();

    // Choosing a different hour retires a refusal that named only 14:00.
    await user.click(within(chart).getByRole("button", { name: /^13:00,/ }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("opens the full dossier for a chosen route", async () => {
    mockFetch(jsonResponse(fixtureHealth), jsonResponse(seriesResponse));
    const user = userEvent.setup();

    const analyze = await openSetup(user);
    await user.click(analyze);

    const comparison = await screen.findByRole("region", {
      name: "Walking routes",
    });
    await user.click(within(comparison).getByRole("link", { name: /route-2/ }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "route-2" })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Turn-by-turn directions are not included/)
    ).toBeInTheDocument();
    expect(screen.getByText("75% modeled shade estimate")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Optional context is unavailable because this result set carries no token."
      )
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("link", { name: "Return to trip results" })
    );
    expect(
      await screen.findByRole("region", { name: "Walking routes" })
    ).toBeInTheDocument();
  });

  it("returns to setup when results were never produced", async () => {
    mockFetch(jsonResponse(fixtureHealth));

    window.history.pushState({}, "", "/trip/results");
    render(<App />);

    expect(
      await screen.findByRole("button", { name: "Analyze trip" })
    ).toBeInTheDocument();
  });
});
