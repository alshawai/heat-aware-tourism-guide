import { expect, test } from "@playwright/test";

test("analyzes the curated trip entirely from fixtures", async ({ page }) => {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "127.0.0.1") {
      await route.continue();
    } else {
      await route.abort("blockedbyclient");
    }
  });
  await page.goto("/");

  await expect(page.getByText("Fixture replay", { exact: true })).toBeVisible();
  await expect(
    page
      .getByLabel("Curated trip places")
      .getByText("The Alamo", { exact: true })
  ).toBeVisible();
  const analysisResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/trip/analyze")
  );
  await page.getByRole("button", { name: "Analyze trip" }).click();

  const response = await analysisResponse;
  expect(response.ok()).toBe(true);
  await expect(response.json()).resolves.toMatchObject({
    state: "success",
    execution_mode: "fixture",
    best_time: { provenance: { source: "fixture" } },
    routes: {
      alternatives: expect.arrayContaining([
        expect.objectContaining({ geometry: expect.any(Array) }),
      ]),
    },
  });
  await expect(page.getByText("Trip analysis ready")).toBeVisible();
  await page.getByRole("link", { name: "Compare returned routes" }).click();
  await expect(
    page.getByRole("heading", { name: "Compare returned alternatives" })
  ).toBeVisible();
  await expect(page.getByText("short")).toBeVisible();
  await expect(page.getByText("shady")).toBeVisible();
  await expect(page.getByText("80% modeled shade")).toBeVisible();
  await expect(
    page.getByText(/best among returned alternatives/i)
  ).toBeVisible();
});
