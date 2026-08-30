import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../app/App";

const successResponse = {
  request_identity: "curated:2026-08-23:8-20",
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
    recommendation_time: "2026-08-23T09:00:00-05:00",
    recommendation_timezone: "America/Chicago",
    temporal_evidence: "exact",
    environmental_concerns: [],
    provenance: {
      source: "fixture",
      data_date: "2026-08-23",
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
  data_date: "2026-08-23",
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
  data_date: "2026-08-23",
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

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("curated Trip Setup", () => {
  it("loads fixture mode and submits the complete setup exactly once", async () => {
    const fetchMock = mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse(successResponse)
    );
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByText("Fixture replay")).toBeInTheDocument();
    expect(screen.getByText("Menger Hotel")).toBeInTheDocument();
    expect(screen.getByText("The Alamo")).toBeInTheDocument();
    expect(
      screen.getByText("Downtown San Antonio / Alamo Plaza")
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Date")).toHaveValue("2026-08-23");
    expect(screen.getByLabelText("Start time")).toHaveValue("8");
    expect(screen.getByLabelText("End time")).toHaveValue("20");
    expect(screen.getByLabelText(/Cautious guidance/)).not.toBeChecked();
    expect(screen.getByText(/United States/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

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
          date: "2026-08-23",
          start_hour: 8,
          end_hour: 20,
          cautious: false,
          execution_mode: "fixture",
        }),
      })
    );
  });

  it("preserves edits and retries when application mode is unavailable", async () => {
    const fetchMock = mockFetch(
      Promise.reject(new Error("offline")),
      jsonResponse({ status: "ok", mode: "live" })
    );
    const user = userEvent.setup();

    render(<App />);

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

  it("validates fields without submitting or auto-submitting edits", async () => {
    const fetchMock = mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    const date = screen.getByLabelText("Date");
    await user.clear(date);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    expect(screen.getByText("Enter a valid date.")).toBeInTheDocument();
    expect(date).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("validates time order and the 12-hour maximum without submitting", async () => {
    const fetchMock = mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    const start = screen.getByLabelText("Start time");
    const end = screen.getByLabelText("End time");

    await user.selectOptions(start, "20");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));
    expect(
      screen.getByText("Start time must be earlier than end time.")
    ).toBeInTheDocument();
    expect(end).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.selectOptions(start, "0");
    await user.selectOptions(end, "13");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));
    expect(
      screen.getByText("The time window cannot exceed 12 hours.")
    ).toBeInTheDocument();
    expect(end).toHaveFocus();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("accepts and displays the raw nullable environmental series", async () => {
    mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse({
        ...successResponse,
        state: "series_ready",
        environment: {
          entries: [
            {
              valid_time: "2026-08-23T08:00:00-05:00",
              heat_index_celsius: 31.4,
              humidity_percent: 72.5,
              parameters: {
                heat_index_celsius: 31.4,
                relative_humidity_percent: 72.5,
                apparent_temperature_celsius: 35.1,
              },
            },
            {
              valid_time: "2026-08-23T09:00:00-05:00",
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
            data_date: "2026-08-23",
            confidence: "sufficient",
            retrieved_at: "2026-08-24T00:00:00+00:00",
            transformation_version: "trip-environment-series-v1",
            provider: "fortyguard",
            response_status: "completed",
            request_configuration: {},
            fresh: true,
            coverage: null,
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

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    expect(
      await screen.findByRole("heading", { name: "Environmental conditions" })
    ).toBeInTheDocument();
    expect(screen.getByText("08:00 GMT-5")).toBeInTheDocument();
    expect(screen.getByText("31.4 C")).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    expect(screen.getByText("68.0 %")).toBeInTheDocument();
    expect(screen.getByText("34.2 C")).toBeInTheDocument();
    expect(
      screen.getByText("fixed temperature anchor; not a real 24-hour forecast")
    ).toBeInTheDocument();
    expect(screen.queryByText(/best time/i)).not.toBeInTheDocument();
  });

  it("presents recommended modeled route shade with quality evidence", async () => {
    mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse({ ...successResponse, routes: shadiestRoutes })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    const comparison = await screen.findByRole("region", {
      name: "Walking routes",
    });
    expect(
      within(comparison).getByRole("heading", {
        name: "Shadiest route recommended",
      })
    ).toBeInTheDocument();
    expect(
      within(comparison).getByText(/highest modeled OSM building shade/)
    ).toBeInTheDocument();
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
      jsonResponse({ status: "ok", mode: "fixture" }),
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

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

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
  });

  it("announces busy state and disables setup controls", async () => {
    let resolveAnalysis!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolveAnalysis = resolve;
    });
    mockFetch(jsonResponse({ status: "ok", mode: "fixture" }), pending);
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    expect(screen.getByRole("status")).toHaveTextContent("Analyzing trip...");
    expect(screen.getByLabelText("Date")).toBeDisabled();
    expect(screen.getByLabelText("Start time")).toBeDisabled();
    expect(screen.getByLabelText("End time")).toBeDisabled();
    expect(screen.getByLabelText(/Cautious guidance/)).toBeDisabled();
    resolveAnalysis(jsonResponse(successResponse));
    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
  });

  it("retains degraded detail and clears it when setup changes", async () => {
    mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
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

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    const outcome = await screen.findByRole("status", {
      name: "Trip analysis outcome",
    });
    expect(
      within(outcome).getByText("Trip analysis ready with limitations")
    ).toBeInTheDocument();
    expect(
      within(outcome).getByText("Hotel ranking is temporarily unavailable.")
    ).toBeInTheDocument();
    expect(
      within(outcome).getByText("Lower provider temperature")
    ).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Start time"), "9");
    expect(screen.queryByText(/Trip analysis ready/)).not.toBeInTheDocument();
  });

  it("shows domain unavailability and returns to editing", async () => {
    mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse({
        ...successResponse,
        state: "unavailable",
        best_time: null,
        hotels: null,
        routes: null,
        unavailable: {
          reason: "No fixture matches that date and hour.",
          recoverable: true,
        },
      })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    expect(
      await screen.findByText("No fixture matches that date and hour.")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit setup" }));
    expect(
      screen.queryByText("No fixture matches that date and hour.")
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Date")).toHaveFocus();
  });

  it("keeps analyzed setup values aligned across route remounts", async () => {
    mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse({
        ...successResponse,
        request_identity: "curated:2026-08-23:9-20",
      }),
      jsonResponse({ status: "ok", mode: "fixture" })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.selectOptions(screen.getByLabelText("Start time"), "9");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));
    await screen.findByText("Trip analysis ready");

    window.history.pushState({}, "", "/walk/date");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await screen.findByText("Choose a place");
    await user.click(
      screen.getByRole("link", { name: "Heat-Aware Tourism Guide home" })
    );

    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
    expect(screen.getByLabelText("Start time")).toHaveValue("9");
  });

  it("clears a retained result when application mode changes", async () => {
    mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse(successResponse),
      jsonResponse({ status: "ok", mode: "live" })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));
    await screen.findByText("Trip analysis ready");

    window.history.pushState({}, "", "/walk/date");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await screen.findByText("Choose a place");
    await user.click(
      screen.getByRole("link", { name: "Heat-Aware Tourism Guide home" })
    );

    expect(await screen.findByText("Live data")).toBeInTheDocument();
    expect(screen.queryByText("Trip analysis ready")).not.toBeInTheDocument();
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
        request_identity: "curated:2026-08-23:9-20",
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
      jsonResponse({ status: "ok", mode: "fixture" }),
      failedResponse,
      jsonResponse(successResponse)
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    expect(
      await screen.findByText("We could not analyze this trip.")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });
});
