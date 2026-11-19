import { addTarget, expect, signIn, test } from "./helpers";

// A held lead makes its section the first on "Needs a decision". Picking the "Websites to confirm"
// tab hides it, and the section left must then be open: it is the only one, and the person came for it.
test("with a held lead on the page, the websites-to-confirm tab opens its section", async ({ page }) => {
  await signIn(page);
  const name = `Harbor Light ${Date.now()}`;
  await addTarget(page, { company: name });
  await page.route("**/api/companies?*bucket=decision*", async (route) => {
    const real = await (await route.fetch()).json();
    const held = {
      id: "held-1", domain: "held.example", name: "Held Example", source: "manual", status: "held", hold_reason: "catch_all_unverified",
      failed_stage: null, last_error: null, failure_kind: null, attempts: 0, credit_wait_step: null, country_code: "US",
      legal_entity_type: "unknown", priority: 5, fit_score: 50, fit_reason: null, campaign_id: null, research: null,
      research_answers: null, policy_decision: null, policy_skip_from: null, manual_fields: [], next_action_at: null,
      row_version: 1, created_at: null, updated_at: null, hot: false, max_tries: 5,
    };
    await route.fulfill({ json: { ...real, items: [held, ...real.items.filter((c: { status: string }) => c.status !== "held")] } });
  });
  // The rows to confirm arrive after the held lead, so its section is the first to appear.
  await page.route("**/api/targets/waiting", async (route) => {
    await new Promise((done) => setTimeout(done, 1000));
    await route.continue();
  });
  await page.goto("/attention");
  await expect(page.getByRole("link", { name: "Held Example" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /^Websites to confirm [1-9]/ })).toBeVisible();
  await page.getByRole("tab", { name: /^Websites to confirm/ }).click();
  const row = page.getByRole("listitem").filter({ hasText: name });
  await expect(row.getByLabel("Website for this row")).toBeVisible();
});
