import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "e2e-password-123";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
});

async function startRunAndWait(page: Page) {
  await page.getByRole("link", { name: "Runs" }).click();
  const before = await page.locator("tbody tr").count();
  await page.getByRole("button", { name: "Start run" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(before + 1);
  await expect(page.locator("tbody tr").first()).toContainText("succeeded", { timeout: 30_000 });
}

// A company in a country whose rule is "consent required" is held before any person is known.
// Releasing it must not send it round the same loop; adding a consenting person must end it.
test("a consent hold is ended by adding the person who consented, not by releasing it", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await page.getByRole("link", { name: "Targets" }).click();
  await page.getByLabel("Website or domain").fill("tata-test.in");
  await page.getByLabel("Country").fill("IN");
  await page.getByRole("button", { name: "Add target" }).click();
  await expect(page.getByText("accepted").first()).toBeVisible();
  await startRunAndWait(page);

  await page.getByRole("link", { name: "Leads", exact: true }).click();
  await page.getByRole("link", { name: "tata-test.in", exact: true }).click();
  await expect(page.getByText("needs prior consent, and nobody at this company has given it")).toBeVisible();

  // Releasing changes nothing, and the page says so instead of looping.
  await page.getByRole("button", { name: "Release hold" }).click();
  await expect(page.getByRole("alert")).toContainText("Nothing has changed");
  await expect(page.getByText("Held: consent required")).toBeVisible();

  // Add the person who consented: the hold is released as part of it.
  await page.getByLabel("Person's name").fill("Asha Rao");
  await page.getByLabel("This person has given consent to be contacted").check();
  await page.getByLabel("Evidence").fill("Asked for a demo at the 2026 grid summit");
  await page.getByRole("button", { name: "Add person and release the hold" }).click();
  await expect(page.getByText("Held: consent required")).toBeHidden();

  // The next run no longer holds it for the same reason.
  await startRunAndWait(page);
  await page.getByRole("link", { name: "Leads", exact: true }).click();
  await page.getByRole("link", { name: "tata-test.in", exact: true }).click();
  await expect(page.getByText("Held: consent required")).toBeHidden();
  await expect(page.getByText("Asha Rao").first()).toBeVisible();
});
