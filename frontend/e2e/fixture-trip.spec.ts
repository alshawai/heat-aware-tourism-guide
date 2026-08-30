import { expect, test, type Page } from "@playwright/test";

/**
 * The whole traveler flow against the real fixture backend: welcome, setup, one
 * analysis, the unified results, an hour override, and the route dossier.
 *
 * Everything the page needs is served from 127.0.0.1; map tiles and any other
 * third-party request are blocked so the run cannot depend on the network.
 */
async function blockOffsiteRequests(page: Page) {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "127.0.0.1") {
      await route.continue();
    } else {
      await route.abort("blockedbyclient");
    }
  });
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

  await expect(
    page.getByRole("heading", {
      name: "Plan time outside with clearer heat context.",
    })
  ).toBeVisible();
  await page.getByRole("link", { name: /Plan a walk/ }).click();

  await expect(page.getByRole("heading", { name: "Trip Setup" })).toBeVisible();
  await expect(page.getByText("Fixture replay", { exact: true })).toBeVisible();
  await expect(
    page
      .getByLabel("Curated trip places")
      .getByText("The Alamo", { exact: true })
  ).toBeVisible();
  await expect(page.getByText("08:00 to 19:00")).toBeVisible();

  const baselineRequest = analyzeRequestBody(page);
  const baselineResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/trip/analyze")
  );
  await page.getByRole("button", { name: "Analyze trip" }).click();

  // One analysis covers the whole window: the best hour and every route.
  expect((await baselineRequest).postDataJSON()).toMatchObject({
    mode: "curated",
    date: "2026-08-23",
    start_hour: 8,
    end_hour: 20,
    cautious: false,
    execution_mode: "fixture",
    landmark_name: "The Alamo",
  });
  const response = await baselineResponse;
  expect(response.ok()).toBe(true);
  const analysis = await response.json();
  expect(analysis).toMatchObject({
    state: "success",
    execution_mode: "fixture",
    request_identity: "curated:2026-08-23:8-20",
    best_time: { provenance: { source: "fixture" } },
    routes: {
      alternatives: expect.arrayContaining([
        expect.objectContaining({ geometry: expect.any(Array) }),
      ]),
    },
  });
  const recommendedHour: number = analysis.best_time.recommendation_hour;
  const recommendedRoute: string = analysis.routes.recommended_id;

  await expect(page.getByRole("heading", { name: "Your walk" })).toBeVisible();
  await expect(page.getByText("Trip analysis ready")).toBeVisible();
  await expect(page.getByText("Produced by fixture replay.")).toBeVisible();

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
  await expect(
    routes.getByText("highest modeled shade among returned routes").first()
  ).toBeVisible();
  await expect(routes.getByText("80% modeled shade")).toBeVisible();
  await expect(routes.getByText("20% modeled shade")).toBeVisible();
  await expect(routes.getByText("shady", { exact: true })).toBeVisible();
  await expect(routes.getByText("short", { exact: true })).toBeVisible();
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

  // An hour override narrows the window to exactly that hour. Fixture replay
  // only holds the committed window, so the server declines the narrowed
  // request; the analyzed window must survive that answer intact.
  const overrideHour: number = analysis.best_time.hourly
    .map((entry: { hour: number }) => entry.hour)
    .find((hour: number) => hour !== recommendedHour);
  const clock = `${String(overrideHour).padStart(2, "0")}:00`;
  await chart.getByRole("button", { name: new RegExp(`^${clock},`) }).click();
  const overrideRequest = analyzeRequestBody(page);
  await page.getByRole("button", { name: `Recalculate for ${clock}` }).click();

  expect((await overrideRequest).postDataJSON()).toMatchObject({
    start_hour: overrideHour,
    end_hour: overrideHour + 1,
    date: "2026-08-23",
    execution_mode: "fixture",
  });
  const refusal = page.getByRole("alert");
  await expect(
    refusal.getByRole("heading", { name: `${clock} could not be analyzed` })
  ).toBeVisible();
  await expect(
    refusal.getByText("no matching fixture for the requested trip")
  ).toBeVisible();
  await expect(page.getByText("Trip analysis ready")).toBeVisible();
  await expect(routes.getByText("80% modeled shade")).toBeVisible();

  // The dossier opens the route the comparison recommended.
  await routes.getByRole("link", { name: /Recommended route/ }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: recommendedRoute })
  ).toBeVisible();
  await expect(page.getByText("80% modeled shade estimate")).toBeVisible();
  await expect(
    page.getByText(/Turn-by-turn directions are not included/)
  ).toBeVisible();

  await page.getByRole("link", { name: "Return to trip results" }).click();
  await expect(
    page.getByRole("region", { name: "Walking routes" })
  ).toBeVisible();
});
