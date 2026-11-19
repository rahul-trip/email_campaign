import { addTarget, expect, runEngine, signIn, test, unique } from "./helpers";

// Today's emails row asks for ten emails, best first and without each lead's research, not the whole queue, and shows
// placeholders (not a gap) while they arrive. The whole queue took 11 seconds to load on the live site.
test("Today asks for only its ten best emails, slim, and shows placeholders while they load", async ({ page }) => {
  await signIn(page);
  for (const domain of [unique("fast-one"), unique("fast-two")]) await addTarget(page, { website: domain, country: "US" });
  await runEngine(page);

  const asked: string[] = [];
  await page.route("**/api/review?**", async (route) => {
    asked.push(new URL(route.request().url()).search);
    await new Promise((resolve) => setTimeout(resolve, 1200)); // a slow answer, so the placeholders can be seen
    await route.continue();
  });
  await page.goto("/");
  await expect(page.getByRole("status", { name: "Loading the emails" })).toBeVisible();
  await expect(page.locator("[data-tour=ready-drafts]")).toBeVisible();
  await expect(page.getByRole("status", { name: "Loading the emails" })).toHaveCount(0);

  expect(asked.length).toBeGreaterThan(0);
  for (const query of asked) {
    expect(query).toContain("limit=10");
    expect(query).toContain("best=true");
    expect(query).toContain("slim=true");
  }
  // The headline still counts them all, from the status, not from the list.
  await expect(page.getByRole("heading", { level: 1 })).toContainText("emails are ready for you");
});
