import { expect, test, type Page } from "@playwright/test";

type Scenario = {
  name: string;
  origin?: { query: string; name: string };
  destination?: { query: string; name: string };
};

const scenarios: Scenario[] = [
  { name: "canonical" },
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

async function blockNonLoopback(page: Page) {
  await page.route("**/*", async (route) => {
    const hostname = new URL(route.request().url()).hostname;
    if (["127.0.0.1", "::1", "localhost"].includes(hostname)) {
      await route.continue();
    } else {
      await route.abort("blockedbyclient");
    }
  });
}

async function selectPlace(
  page: Page,
  endpoint: "origin" | "destination",
  place: { query: string; name: string }
) {
  if (endpoint === "destination") {
    await page.getByRole("button", { name: /^Destination:/ }).click();
  }
  const search = page.getByLabel("Search places");
  await search.fill(place.query);
  await page
    .getByRole("button", { name: `Set ${endpoint} to ${place.name}` })
    .click();
}

for (const scenario of scenarios) {
  test(`runs the ${scenario.name} fixture flow without external requests`, async ({
    page,
  }) => {
    await blockNonLoopback(page);
    await page.goto("/");
    await expect(
      page.getByText("Fixture replay", { exact: true })
    ).toBeVisible();

    if (scenario.origin && scenario.destination) {
      await page.getByRole("button", { name: "Explore another trip" }).click();
      await selectPlace(page, "origin", scenario.origin);
      await selectPlace(page, "destination", scenario.destination);
    } else {
      await page.getByLabel("Date").fill("2024-07-15");
    }

    const analysisResponse = page.waitForResponse((response) =>
      response.url().endsWith("/api/trip/analyze")
    );
    await page.getByRole("button", { name: "Analyze trip" }).click();
    const response = await analysisResponse;
    expect(response.ok()).toBe(true);
    const result = await response.json();
    expect(result.schema_version).toBe("trip-contract-v2");

    if (scenario.name === "Briscoe") {
      expect(result).toMatchObject({
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
        page.getByText(/Required provider data is missing/)
      ).toBeVisible();
      await expect(
        page.getByText(/Retry later or edit the trip setup/)
      ).toBeVisible();
      return;
    }

    await expect(
      page.getByRole("heading", {
        name: "Trip analysis ready with limitations",
      })
    ).toBeVisible();

    if (scenario.name === "Cathedral") {
      expect(result.routes).toMatchObject({
        route_set_state: "alternatives_returned",
        decision_state: "insufficient_shade_comparison_required",
        recommended_id: null,
        confidence: "insufficient",
      });
      expect(result.routes.alternatives).toHaveLength(2);
      expect(result.hotels.enrichment.code).toBe("optional_provider_failure");
      await expect(page.getByText(/No route is recommended/)).toBeVisible();
      await expect(
        page.getByText(/base hotel ranking remains available/i)
      ).toBeVisible();
      await page.getByRole("link", { name: "Compare returned routes" }).click();
      await expect(
        page.getByText(/Building-height coverage is weak/)
      ).toBeVisible();
      await expect(page.getByText("route-1", { exact: true })).toBeVisible();
      await expect(page.getByText("route-2", { exact: true })).toBeVisible();
      await expect(page.getByText("Recommended", { exact: true })).toHaveCount(
        0
      );
      return;
    }

    if (scenario.name === "canonical") {
      expect(result.best_time.temporal_evidence).toBe("inconsistent");
      await expect(
        page.getByRole("note").filter({ hasText: "hour-only recommendation" })
      ).toBeVisible();
    }
    expect(result.routes.route_set_state).toBe("single_route");
    expect(result.routes.alternatives).toHaveLength(1);
    await expect(page.getByText(/no alternatives to compare/i)).toBeVisible();
    await page.getByRole("link", { name: "Compare returned routes" }).click();
    await expect(page.getByText(/One returned route is usable/)).toBeVisible();
    await expect(page.getByText("route-1", { exact: true })).toBeVisible();
  });
}
