import { expect, test } from "@playwright/test";

test("hotel location and ranking remain usable at every release viewport", async ({
  page,
}) => {
  await page.route("**/*", async (route) => {
    const hostname = new URL(route.request().url()).hostname;
    if (["127.0.0.1", "::1", "localhost"].includes(hostname)) {
      await route.continue();
    } else {
      await route.abort("blockedbyclient");
    }
  });
  await page.goto("/hotels/location");
  await page.getByLabel("Search mock locations").fill("downtown");
  await page.getByRole("option").first().click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/hotels\/results$/);
  await expect(
    page.getByRole("heading", { name: "Downtown San Antonio" })
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Apply local weights" })
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth
      )
    )
    .toBe(true);
  await page
    .getByRole("link", { name: /View details for/ })
    .first()
    .click();
  await expect(page.getByText("Hotel evidence", { exact: true })).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth
      )
    )
    .toBe(true);
});
