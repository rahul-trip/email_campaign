import { addTarget, expect, signIn, test, unique } from "./helpers";

test("add leads: check only saves nothing; upload is previewed before import", async ({ page }) => {
  await signIn(page);
  await page.goto("/targets");
  await page.getByLabel("Website or domain").fill(unique("check-only"));
  await page.getByText("Check only, do not save").click();
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByText("Preview only: nothing has been saved.")).toBeVisible();

  await page.getByRole("tab", { name: "Upload a file" }).click();
  const csv = `Website,Country\n${unique("upload-a")},US\n${unique("upload-b")},US\n`;
  await page.getByLabel("Targets file").setInputFiles({ name: "targets.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(page.getByRole("button", { name: "2. Import" })).toBeDisabled();
  await page.getByRole("button", { name: "1. Preview" }).click();
  await expect(page.getByText("Preview only: nothing has been saved.")).toBeVisible();
  await page.getByRole("button", { name: "2. Import" }).click();
  await expect(page.getByText("Imported. The next run researches the accepted rows.")).toBeVisible();
});

test("a company added by name waits for its website, and confirming it adds the lead", async ({ page }) => {
  await signIn(page);
  const name = `Harbor Light ${Date.now()}`;
  await addTarget(page, { company: name });
  await page.goto("/attention");
  const row = page.getByRole("listitem").filter({ hasText: name });
  const website = unique("harborlight");
  await row.getByLabel("Website for this row").fill(website);
  await row.getByRole("button", { name: "Use this website" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: name })).toHaveCount(0);
  await page.goto(`/leads?q=${website}`);
  await expect(page.getByRole("row").filter({ hasText: website })).toHaveCount(1);
});

test("the header search opens the filtered leads list", async ({ page }) => {
  await signIn(page);
  const domain = unique("findable");
  await addTarget(page, { website: domain, country: "US" });
  await page.getByLabel("Search leads").fill(domain);
  await page.getByLabel("Search leads").press("Enter");
  await expect(page).toHaveURL(new RegExp(`q=${domain}`));
  await expect(page.getByRole("link", { name: domain }).first()).toBeVisible();
  await expect(page.getByText("1 matching company")).toBeVisible();
});

test("settings: a blank budget means no limit; the profile is confirmed", async ({ page }) => {
  await signIn(page);
  await page.goto("/settings");
  await expect(page.getByText("Setup check").first()).toBeVisible();
  await page.getByRole("tab", { name: "Limits and budget" }).click();
  const budget = page.getByLabel(/Budget per prospect/);
  await budget.fill("");
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  await page.reload();
  await page.getByRole("tab", { name: "Limits and budget" }).click();
  await expect(budget).toHaveValue("");
  await budget.fill("0.50");
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();

  await page.getByRole("tab", { name: "Sender profile" }).click();
  await expect(page.getByText("Legal footer")).toBeVisible();
  await page.getByRole("button", { name: "Confirm and save" }).click();
  await expect(page.getByText("Saved and confirmed.")).toBeVisible();
});

test("policies and privacy: a rule change saves a new version; do-not-contact and forget ask first", async ({ page }) => {
  await signIn(page);
  await page.goto("/compliance");
  const row = page.getByRole("row").filter({ has: page.getByLabel("Rule for SE") });
  const before = Number((await row.getByText(/^version \d+$/).textContent())?.replace("version ", ""));
  await page.getByLabel("Rule for SE").selectOption("consent_required");
  await row.getByRole("button", { name: "Save" }).click();
  await expect(row.getByText(`version ${before + 1}`)).toBeVisible();

  await page.getByRole("tab", { name: /Do not contact/ }).click();
  await page.getByRole("textbox", { name: "Address", exact: true }).fill(`nobody-${Date.now()}@spam-test.com`);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Add to the list" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.getByRole("tab", { name: /Forget a person/ }).click();
  await page.getByLabel("Email address").fill(`gone-${Date.now()}@example-test.com`);
  await page.getByRole("button", { name: "Forget this address…" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Forget permanently" }).click();
  await expect(page.getByText(/now on the do-not-contact list/)).toBeVisible();
});

test("campaigns save", async ({ page }) => {
  await signIn(page);
  await page.goto("/campaigns");
  await page.getByRole("button", { name: "Save campaign" }).first().click();
  await expect(page.getByText("Campaign saved.")).toBeVisible();
});

test("a mailbox is managed from Settings, and the old address lands there", async ({ page }) => {
  await signIn(page);
  await page.goto("/w/default/mailboxes");
  await expect(page).toHaveURL(/settings\?tab=mailboxes/);
  const card = page.locator("section").filter({ hasText: "sam@quantra-e2e.example" });
  await expect(card.getByText("Default")).toBeVisible();
  await card.getByRole("button", { name: "Pause" }).click();
  await expect(card.getByText("Paused")).toBeVisible();
  await card.getByRole("button", { name: "Resume" }).click();
  await card.getByRole("button", { name: "Who signs" }).click();
  await page.getByLabel("Name").fill("Pat Kim");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(card.getByText("signs as Pat Kim")).toBeVisible();
});

test("connecting an IMAP server on our own network is refused", async ({ page }) => {
  await signIn(page);
  await page.goto("/w/default/settings?tab=mailboxes");
  await page.getByRole("button", { name: "Any other (IMAP)" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Email address", { exact: true }).fill("someone@example.com");
  await dialog.getByLabel("IMAP server", { exact: true }).fill("localhost");
  await dialog.getByLabel("App password", { exact: true }).fill("not-a-real-password");
  await dialog.getByRole("button", { name: "Test and connect" }).click();
  await expect(dialog.getByRole("alert")).toContainText("private or reserved");
});

test("every screen opens without errors, on a laptop and a phone", async ({ page }) => {
  await signIn(page);
  await addTarget(page, { website: unique("smoke"), country: "US" });
  const screens = ["/", "/review", "/attention", "/leads", "/targets", "/runs", "/reports", "/campaigns", "/settings?tab=mailboxes", "/compliance", "/settings", "/settings?tab=team", "/settings?tab=account"];
  const routes = ["/sign-in", "/forgot-password", ...screens.map((route) => `/w/default${route}`)];
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of routes) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${route} at ${width}px scrolls sideways`).toBeLessThanOrEqual(1);
    }
  }
  // On a phone the menu opens from the button.
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeInViewport();
});

test("an unknown address shows the not-found page", async ({ page }) => {
  await signIn(page);
  await page.goto("/no-such-page");
  await expect(page.getByText("This page does not exist")).toBeVisible();
});

test("country rules can be switched off for the workspace, with a banner, and back on", async ({ page }) => {
  await signIn(page);
  await page.goto("/compliance");
  await page.getByRole("button", { name: "Switch country rules off…" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Switch off" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Country rules are switched off" })).toBeVisible();
  await page.goto("/leads");
  await expect(page.getByRole("alert").filter({ hasText: "Country rules are switched off" })).toBeVisible();
  await page.goto("/compliance");
  await page.getByRole("button", { name: "Switch country rules back on" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Country rules are switched off" })).toHaveCount(0);
});

test("an admin turns the intake webhook on and sees the secret once", async ({ page }) => {
  await signIn(page);
  await page.goto("/w/default/settings?tab=integrations");
  await expect(page.getByText("/api/intake/webhook/")).toBeVisible();
  await page.getByRole("button", { name: "Turn the webhook on" }).click();
  await expect(page.getByText("whsec_")).toBeVisible();
  await page.reload();
  await expect(page.getByText("whsec_")).toHaveCount(0);
  await expect(page.getByText("A secret is set.")).toBeVisible();
});
