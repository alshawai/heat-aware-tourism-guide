import { expect, test, type Page } from "@playwright/test";

/**
 * The whole traveler flow against the real fixture backend: welcome, setup, one
 * analysis, the unified results, an hour override, and the route dossier — plus
 * every acquired scenario the replay can answer.
 *
 * Everything the page needs is served from 127.0.0.1; map tiles and any other
 * third-party request are blocked so the run cannot depend on the network.
 */
async function blockOffsiteRequests(page: Page) {
  await page.route("**/*", async (route) => {
    const hostname = new URL(route.request().url()).hostname;
    if (["127.0.0.1", "::1", "localhost"].includes(hostname)) {
      await route.continue();
    } else {
      await route.abort("blockedbyclient");
    }
  });
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth
      )
    )
    .toBe(true);
}

function analyzeRequestBody(page: Page) {
  return page.waitForRequest(
    (request) =>
      request.url().endsWith("/api/trip/analyze") && request.method() === "POST"
  );
}

test("walks the whole trip flow from the welcome screen on fixtures", async ({
  page,
}) => {
  await blockOffsiteRequests(page);
  await page.goto("/");
  await expectNoHorizontalOverflow(page);

  await expect(
    page.getByRole("heading", {
      name: "Plan time outside with clearer heat context.",
    })
  ).toBeVisible();
  await page.getByRole("link", { name: /Plan a walk/ }).click();

  await expect(
    page.getByRole("heading", { name: "Explore trip" })
  ).toBeVisible();
  await expect(page.getByText("Fixture replay", { exact: true })).toBeVisible();
  // One flow now: the canonical walk is only the prefill, so the endpoint
  // picker that can move either pin is always on the setup screen. The wire
  // mode below still says `curated` because the endpoints are untouched, and
  // the date and window follow the acquired scenario rather than the defaults.
  await expect(
    page.getByRole("button", { name: "Origin: Menger Hotel" })
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Destination: The Alamo" })
  ).toBeVisible();
  await expect(page.getByText("08:00 to 19:00")).toBeVisible();
  await expect(page.getByRole("note")).toContainText("2024-07-15");

  const baselineRequest = analyzeRequestBody(page);
  const baselineResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/trip/analyze")
  );
  await page.getByRole("button", { name: "Analyze trip" }).click();

  // One analysis covers the whole window: the best hour and every route.
  expect((await baselineRequest).postDataJSON()).toMatchObject({
    mode: "curated",
    date: "2024-07-15",
    start_hour: 8,
    end_hour: 20,
    cautious: false,
    execution_mode: "fixture",
    landmark_name: "The Alamo",
    district_name: "Downtown San Antonio",
  });
  const response = await baselineResponse;
  expect(response.ok()).toBe(true);
  const analysis = await response.json();
  expect(analysis).toMatchObject({
    state: "degraded",
    execution_mode: "fixture",
    request_identity: "curated:2024-07-15:8-20",
    best_time: {
      temporal_evidence: "inconsistent",
      // The committed scenario is a snapshot of a genuine provider response, so
      // its provenance still names the provider that produced the numbers.
      // Replay is identified by `execution_mode`, not by rewritten provenance.
      provenance: { source: "provider" },
    },
    routes: {
      route_set_state: "single_route",
      alternatives: expect.arrayContaining([
        expect.objectContaining({ geometry: expect.any(Array) }),
      ]),
    },
  });
  const recommendedHour: number = analysis.best_time.recommendation_hour;
  const recommendedRoute: string = analysis.routes.recommended_id;

  await expect(page.getByRole("heading", { name: "Your walk" })).toBeVisible();
  await expect(
    page.getByText("Trip analysis ready with limitations")
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await expect(page.getByText("Produced by fixture replay.")).toBeVisible();
  // The acquired canonical scenario carries a provider timestamp that conflicts
  // with local time, so the recommendation is hour-only and says so.
  await expect(
    page.getByRole("note").filter({ hasText: "hour-only recommendation" })
  ).toBeVisible();

  // The best hour, its heat chart, and the routes are all on this one screen.
  const chart = page.getByRole("region", { name: "Hourly heat by hour" });
  await expect(chart.getByRole("button")).toHaveCount(
    analysis.best_time.hourly.length
  );
  const recommendedColumn = chart.getByRole("button", {
    name: new RegExp(`^0?${recommendedHour}:00,.*recommended hour$`),
  });
  await expect(recommendedColumn).toHaveAttribute("aria-pressed", "true");

  const routes = page.getByRole("region", { name: "Walking routes" });
  await expect(routes.getByText(/no alternatives to compare/i)).toBeVisible();
  await expect(
    routes.getByText(/Modeled OSM building shade, not measured/)
  ).toBeVisible();
  // Every returned route with usable geometry is drawn, and the recommended one
  // is the highlighted line.
  const map = page.locator(".leaflet-container");
  await expect(map).toBeVisible();
  await expect(map.locator("path.leaflet-interactive")).toHaveCount(
    analysis.routes.alternatives.length
  );
  await expect(
    map.locator('path.leaflet-interactive[stroke="#b9472f"]')
  ).toHaveCount(1);

  // The dossier opens the route the comparison recommended.
  await routes.getByRole("link", { name: /Recommended route/ }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: recommendedRoute })
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await expect(
    page.getByText(/Turn-by-turn directions are not included/)
  ).toBeVisible();

  await page.getByRole("link", { name: "Return to trip results" }).click();
  await expect(
    page.getByRole("region", { name: "Walking routes" })
  ).toBeVisible();
});

/**
 * The acquired exploratory scenarios, driven through the same one flow.
 *
 * Each pair was acquired for its own date and window, so selecting the endpoints
 * is the whole setup: `effectiveSetup` submits the acquired facts, which is what
 * makes fixture replay answer anything other than the canonical walk.
 */
type Scenario = {
  name: string;
  origin: { query: string; name: string };
  destination: { query: string; name: string };
};

const scenarios: Scenario[] = [
  {
    name: "Main Plaza",
    origin: { query: "main", name: "Main Plaza" },
    destination: {
      query: "market",
      name: "Historic Market Square (El Mercado)",
    },
  },
  {
    name: "Cathedral",
    origin: { query: "cathedral", name: "San Fernando Cathedral" },
    destination: { query: "palace", name: "Spanish Governor's Palace" },
  },
  {
    name: "Briscoe",
    origin: { query: "briscoe", name: "Briscoe Western Art Museum" },
    destination: { query: "tower", name: "Tower of the Americas" },
  },
];

async function selectPlace(
  page: Page,
  endpoint: "origin" | "destination",
  place: { query: string; name: string }
) {
  if (endpoint === "destination") {
    await page.getByRole("button", { name: /^Destination:/ }).click();
  }
  await page.getByLabel("Search places").fill(place.query);
  await page.getByRole("option", { name: place.name }).first().click();
}

for (const scenario of scenarios) {
  test(`analyzes the ${scenario.name} fixture scenario without external requests`, async ({
    page,
  }) => {
    await blockOffsiteRequests(page);
    await page.goto("/trip/setup");
    await expectNoHorizontalOverflow(page);
    await expect(
      page.getByText("Fixture replay", { exact: true })
    ).toBeVisible();

    await selectPlace(page, "origin", scenario.origin);
    await selectPlace(page, "destination", scenario.destination);

    const request = analyzeRequestBody(page);
    const analysisResponse = page.waitForResponse((response) =>
      response.url().endsWith("/api/trip/analyze")
    );
    await page.getByRole("button", { name: "Analyze trip" }).click();

    // Moving both pins off the canonical pair derives `exploratory`, and the
    // acquired window replaces the default one.
    expect((await request).postDataJSON()).toMatchObject({
      mode: "exploratory",
      date: "2024-07-15",
      start_hour: 10,
      end_hour: 17,
      execution_mode: "fixture",
      landmark_name: scenario.destination.name,
      district_name: "Downtown San Antonio",
    });
    const response = await analysisResponse;
    expect(response.ok()).toBe(true);
    const analysis = await response.json();
    expect(analysis.schema_version).toBe("trip-contract-v2");

    if (scenario.name === "Briscoe") {
      expect(analysis).toMatchObject({
        state: "unavailable",
        best_time: null,
        hotels: null,
        routes: null,
        unavailable: { code: "provider_data_missing" },
      });
      await expect(
        page.getByRole("heading", { name: "Trip analysis unavailable" })
      ).toBeVisible();
      await expect(
        page.getByText(/The initial TCM analysis failed/)
      ).toBeVisible();
      await expect(
        page.getByText("Retry the analysis or edit the trip setup.")
      ).toBeVisible();
      await expectNoHorizontalOverflow(page);
      return;
    }

    await expect(
      page.getByRole("heading", {
        name: "Trip analysis ready with limitations",
      })
    ).toBeVisible();
    const chart = page.getByRole("region", { name: "Hourly heat by hour" });
    await expect(chart.getByRole("button")).toHaveCount(
      analysis.best_time.hourly.length
    );
    const routes = page.getByRole("region", { name: "Walking routes" });
    await expectNoHorizontalOverflow(page);

    if (scenario.name === "Cathedral") {
      expect(analysis.routes).toMatchObject({
        route_set_state: "alternatives_returned",
        decision_state: "insufficient_shade_comparison_required",
        recommended_id: null,
        confidence: "insufficient",
      });
      expect(analysis.routes.alternatives).toHaveLength(2);
      expect(analysis.hotels.enrichment.code).toBe("optional_provider_failure");
      await expect(routes.getByText(/No route is recommended/)).toBeVisible();
      await expect(
        routes.getByRole("link", { name: /Recommended route/ })
      ).toHaveCount(0);
      await expect(
        page.locator(".leaflet-container path.leaflet-interactive")
      ).toHaveCount(2);
      await expectNoHorizontalOverflow(page);
      return;
    }

    // Main Plaza: one route, three acquired hours, so the hour override is the
    // part of the flow only a multi-hour scenario can exercise.
    expect(analysis.routes.route_set_state).toBe("single_route");
    expect(analysis.routes.alternatives).toHaveLength(1);
    await expect(routes.getByText(/no alternatives to compare/i)).toBeVisible();

    const recommendedHour: number = analysis.best_time.recommendation_hour;
    const overrideHour: number = analysis.best_time.hourly
      .map((entry: { hour: number }) => entry.hour)
      .find((hour: number) => hour !== recommendedHour);
    const clock = `${String(overrideHour).padStart(2, "0")}:00`;
    await chart.getByRole("button", { name: new RegExp(`^${clock},`) }).click();
    const overrideRequest = analyzeRequestBody(page);
    await page
      .getByRole("button", { name: `Recalculate for ${clock}` })
      .click();

    // An hour override narrows the window to exactly that hour. Fixture replay
    // only holds the acquired window, so the server declines the narrowed
    // request; the analyzed window must survive that answer intact.
    expect((await overrideRequest).postDataJSON()).toMatchObject({
      start_hour: overrideHour,
      end_hour: overrideHour + 1,
      date: "2024-07-15",
      execution_mode: "fixture",
    });
    const refusal = page.getByRole("alert");
    await expect(
      refusal.getByRole("heading", { name: `${clock} could not be analyzed` })
    ).toBeVisible();
    await expect(
      refusal.getByText(
        "no matching fixture for the requested exploratory trip"
      )
    ).toBeVisible();
    await expect(
      page.getByText("Trip analysis ready with limitations")
    ).toBeVisible();
    await expect(routes.getByText(/no alternatives to compare/i)).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
}
