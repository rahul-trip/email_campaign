import { addTarget, expect, runEngine, signIn, test, unique } from "./helpers";

// Emails ready on a phone: the waiting emails are a row to swipe through, above the one being read.
test("Emails ready on a phone has a swipeable row of waiting emails", async ({ page }) => {
  await signIn(page);
  const [one, two] = [unique("swipe-one"), unique("swipe-two")];
  for (const domain of [one, two]) await addTarget(page, { website: domain, country: "US" });
  await runEngine(page);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/review");
  const strip = page.getByRole("navigation", { name: "Emails waiting" });
  await expect(strip).toBeVisible();
  const cards = strip.getByRole("button");
  await expect.poll(() => cards.count()).toBeGreaterThanOrEqual(2);

  // It scrolls sideways, and the page itself does not.
  const list = strip.locator("ul");
  const sizes = await list.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
  expect(sizes.scroll).toBeGreaterThan(sizes.client);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);

  // Picking a card shows that email below, and marks the card.
  const target = cards.nth(1);
  await target.scrollIntoViewIfNeeded();
  await target.click();
  await expect(target).toHaveAttribute("aria-current", "true");
  await expect(page.getByLabel("Email text")).toBeVisible();
});

test("Today's ready emails are a swipeable row on a phone", async ({ page }) => {
  await signIn(page);
  for (const domain of [unique("today-one"), unique("today-two")]) await addTarget(page, { website: domain, country: "US" });
  await runEngine(page);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const row = page.locator("[data-tour=ready-drafts]");
  await expect(row).toBeVisible();
  await expect.poll(() => row.locator("> *").count()).toBeGreaterThanOrEqual(2);
  const sizes = await row.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth, first: (el.children[0] as HTMLElement).getBoundingClientRect().width }));
  expect(sizes.scroll, "the row scrolls sideways").toBeGreaterThan(sizes.client);
  expect(sizes.first).toBeLessThan(390 * 0.9);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  // Approving stays one tap on the first card.
  await expect(row.getByRole("button", { name: "Approve" }).first()).toBeVisible();
});
