import { addTarget, expect, runEngine, signIn, test, unique } from "./helpers";

test("Failed leads can be searched and filtered, and a row opens its details", async ({ page }) => {
  await signIn(page);
  const first = unique("decide-a", "in");
  const second = unique("decide-b", "in");
  for (const domain of [first, second]) await addTarget(page, { website: domain, country: "IN" });
  await runEngine(page);

  await page.goto("/attention");
  const rows = page.getByRole("listitem");
  await expect(rows.filter({ hasText: first })).toBeVisible();
  await expect(rows.filter({ hasText: second })).toBeVisible();

  // Search narrows the list to one lead, and says how many of how many.
  await page.getByLabel("Search by company, website or person").fill(first);
  await expect(rows.filter({ hasText: second })).toHaveCount(0);
  await expect(rows.filter({ hasText: first })).toBeVisible();
  await expect(page.getByText(/Showing 1 of \d+ leads/)).toBeVisible();

  // Each row says where it stands and opens its details.
  const row = rows.filter({ hasText: first });
  await row.getByRole("button", { name: /Details/ }).click();
  await expect(row.getByText(/Why it fits|No fit details were recorded/).first()).toBeVisible();

  // A filter that nothing matches leaves no row; Clear brings them back.
  await page.getByLabel("Search by company, website or person").fill("");
  // A held lead did not stop at any step, so this filter leaves nothing.
  await page.getByLabel("Step that stopped").selectOption("research");
  await expect(rows.filter({ hasText: first })).toHaveCount(0);
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(rows.filter({ hasText: first })).toBeVisible();
});

test("LinkedIn ready has filters and sort in the address, and a clear way back", async ({ page }) => {
  await signIn(page);
  await page.goto("/linkedin");
  await expect(page.getByRole("heading", { name: "LinkedIn ready" })).toBeVisible();
  await page.getByRole("button", { name: /Hot only/ }).click();
  await expect(page).toHaveURL(/hot=true/);
  await page.getByLabel("Sort by").selectOption("company");
  await expect(page).toHaveURL(/sort=company/);
  await page.getByRole("button", { name: "No email", exact: true }).click();
  await expect(page).toHaveURL(/email=none/);
  // Nothing in the fake world is hot with no email: the page says so and offers to clear.
  await expect(page.getByText("No message matches")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page).not.toHaveURL(/hot=true/);
});
