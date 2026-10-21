import { addTarget, expect, leadId, runEngine, signIn, test, unique } from "./helpers";

test("targets to review to draft, and an unapproved email is never drafted", async ({ page }) => {
  await signIn(page);
  const approved = unique("approve-me");
  const waiting = unique("leave-me");

  // 1. Add two targets on the Add leads screen.
  for (const domain of [approved, waiting]) {
    await page.getByRole("link", { name: "Add leads" }).click();
    await page.getByLabel("Website or domain").fill(domain);
    await page.getByLabel(/^Country/).fill("US");
    await page.getByRole("button", { name: "Add company" }).click();
    await expect(page.getByText("Accepted").first()).toBeVisible();
  }

  // 2. Start a run from the Runs screen; the worker executes it.
  await page.getByRole("link", { name: "Runs" }).click();
  await page.getByRole("button", { name: "Start run" }).click();
  await expect(page.getByText("Succeeded").first()).toBeVisible({ timeout: 30_000 });

  // 3. Both emails wait for review. Approve one with an edit: the diff shows the change.
  await page.getByRole("link", { name: /^Review/ }).click();
  await page.getByRole("navigation", { name: "Emails waiting" }).getByRole("button", { name: new RegExp(approved) }).click();
  const text = page.getByLabel("Email text");
  const original = await text.inputValue();
  await text.fill(original.replace("Would a short call", "Is a short call"));
  await expect(page.getByLabel("Changes")).toContainText("Is");
  await page.getByRole("button", { name: "Approve with my edit" }).click();
  await expect(page.getByRole("navigation", { name: "Emails waiting" }).getByRole("button", { name: new RegExp(approved) })).toHaveCount(0);

  // 4. Run again: only the approved lead is drafted.
  await runEngine(page);
  await page.goto(`/leads?q=${approved}`);
  await expect(page.getByRole("row", { name: /In sequence/ })).toHaveCount(1);
  await page.goto(`/leads?q=${waiting}`);
  await expect(page.getByRole("row", { name: /Copy ready/ })).toHaveCount(1);

  // 5. The drafted lead's page shows its emails, vendor calls and timeline.
  await page.goto(`/leads/${await leadId(page, approved)}`);
  await expect(page.getByRole("heading", { name: "Vendor calls" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.getByText("edited", { exact: false }).first()).toBeVisible();

  // 6. The journey: how it arrived, eight stages as keyboard tabs.
  await page.getByRole("link", { name: "Journey" }).click();
  await expect(page.getByText("How this lead arrived")).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(8);
  await page.getByRole("tab", { name: /Email address/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("Vendor calls");
  await page.getByRole("tab", { name: /Email address/ }).press("ArrowRight");
  await expect(page.getByRole("tab", { selected: true })).toContainText("Copy");
});

test("rejecting needs a reason, and the email leaves the queue", async ({ page }) => {
  await signIn(page);
  const domain = unique("reject-me");
  await addTarget(page, { website: domain, country: "US" });
  await runEngine(page);
  await page.goto("/review");
  await page.getByRole("navigation", { name: "Emails waiting" }).getByRole("button", { name: new RegExp(domain) }).click();
  await page.getByRole("button", { name: "Reject…" }).click();
  const confirm = page.getByRole("dialog").getByRole("button", { name: "Reject" });
  await expect(confirm).toBeDisabled();
  await page.getByRole("dialog").getByLabel("Reason").fill("Not a fit for this test");
  await confirm.click();
  await expect(page.getByRole("navigation", { name: "Emails waiting" }).getByRole("button", { name: new RegExp(domain) })).toHaveCount(0);
  await page.goto(`/leads?q=${domain}`);
  await expect(page.getByRole("row", { name: /Rejected/ })).toHaveCount(1);
});

test("a lead held by its country rule goes on once the rule is skipped, and approval asks to confirm it", async ({ page }) => {
  await signIn(page);
  const domain = unique("skip-rule");
  await addTarget(page, { website: domain, country: "IN" }); // India: consent required by default
  await runEngine(page);
  await page.goto(`/leads/${await leadId(page, domain)}`);
  await expect(page.getByText("Held: ")).toBeVisible();

  // Skip the country rule from where it held the lead, with a reason.
  const card = page.locator("[data-tour=lead-policy]");
  await card.getByLabel("Why").fill("They asked us for details at the expo");
  await card.getByRole("button", { name: "Skip the country rule" }).click();
  await expect(card.getByText(/Country rule skipped from/)).toBeVisible();

  // The engine carries on and writes the email; approving needs the confirmation.
  await runEngine(page);
  await page.goto("/review");
  await page.getByRole("navigation", { name: "Emails waiting" }).getByRole("button", { name: new RegExp(domain) }).click();
  await expect(page.getByText("This email relies on checks you skipped")).toBeVisible();
  const approve = page.getByRole("button", { name: "Approve", exact: true });
  await expect(approve).toBeDisabled();
  await page.getByText("I know these checks were skipped").click();
  await approve.click();
  await expect(page.getByRole("navigation", { name: "Emails waiting" }).getByRole("button", { name: new RegExp(domain) })).toHaveCount(0);
});
