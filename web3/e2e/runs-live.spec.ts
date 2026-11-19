import { expect, signIn, test } from "./helpers";

// A run that is going now shows as a card with its steps, and beside it what already waits in Emails ready.
test("a live run is a card with its steps, and says how many drafts wait", async ({ page }) => {
  await signIn(page);
  await page.route("**/api/runs", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const real = await (await route.fetch()).json();
    const now = new Date().toISOString();
    const live = { id: "live-1", kind: "engine", status: "running", params: { mode: "discovery" }, counts: { research: { advanced: 6 }, gate: { advanced: 4 } }, credits_milli: 420, started_at: now, finished_at: null, created_at: now };
    await route.fulfill({ json: [live, ...real] });
  });
  await page.route("**/api/runs/auto-discovery", async (route) => {
    const real = await (await route.fetch()).json();
    await route.fulfill({ json: { ...real, waiting_for_review: 4 } });
  });
  await page.goto("/runs");
  await expect(page.getByRole("heading", { name: "A run is working right now" })).toBeVisible();
  await expect(page.getByText("Step 3 of 6: Find people").first()).toBeVisible();
  await expect(page.getByRole("list", { name: "Steps of a run" }).getByRole("listitem")).toHaveCount(6);
  await expect(page.getByRole("heading", { name: "4 emails are waiting for you" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Start reviewing" })).toBeVisible();
});
