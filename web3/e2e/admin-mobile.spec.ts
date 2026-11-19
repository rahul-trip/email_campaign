import { expect, signIn, STAFF, test } from "./helpers";

// The admin console on a phone: nothing runs off the screen, the section links are real tap targets, and the customer,
// user and vendor lists are blocks with each value under its column's name.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test("the admin console fits a phone", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();

  const wide: string[] = [];
  for (const route of ["/", "/customers", "/users", "/plans", "/settings", "/vendors", "/directory", "/audit"]) {
    await page.goto(`/admin${route}`);
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (over > 1) wide.push(`${route}: ${over}px too wide`);
    const short = await page.getByRole("navigation", { name: "Admin sections" }).getByRole("link").evaluateAll((links) => links.filter((l) => l.getBoundingClientRect().height < 43.5).length);
    if (short) wide.push(`${route}: ${short} section links shorter than 44px`);
  }
  expect(wide, wide.join("\n")).toEqual([]);

  // A list is blocks: no header row, and a value sits under the name of its column.
  await page.goto("/admin/customers");
  await expect(page.getByRole("heading", { name: "Customers" })).toBeVisible();
  await expect(page.locator("thead").first()).toBeHidden();
  const labelled = await page.locator("td[data-label=Plan]").first().evaluate((td) => getComputedStyle(td, "::before").content);
  expect(labelled).toContain("Plan");
});
