import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "e2e-password-123";

// The tour opens by itself on a first visit and would sit over the page; tour.spec.ts covers it.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
});

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("link", { name: /Review/ })).toBeVisible();
}

async function addTarget(page: Page, website: string, country: string) {
  await page.getByRole("link", { name: "Targets" }).click();
  await page.getByLabel("Website or domain").fill(website);
  await page.getByLabel("Country").fill(country);
  await page.getByRole("button", { name: "Add target" }).click();
  await expect(page.getByText("accepted").first()).toBeVisible();
}

async function startRunAndWait(page: Page) {
  await page.getByRole("link", { name: "Runs" }).click();
  const before = await page.locator("tbody tr").count();
  await page.getByRole("button", { name: "Start run" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(before + 1);
  // Newest run is the first row; wait for that one, not an earlier run that already succeeded.
  await expect(page.locator("tbody tr").first()).toContainText("succeeded", { timeout: 30_000 });
}

test("targets to review to draft, and an unapproved lead is never drafted", async ({ page }) => {
  await signIn(page);

  // 1. Add two targets in the browser.
  await addTarget(page, "acme.co.uk", "UK");
  await addTarget(page, "beta.com", "US");

  // 2. Run the engine; the worker executes it.
  await startRunAndWait(page);

  // 3. Both emails wait for review. Approve one, with an edit.
  await page.getByRole("link", { name: /Review/ }).click();
  await expect(page.getByText("Waiting (2)")).toBeVisible();
  const text = page.getByLabel("Email text");
  const original = await text.inputValue();
  await text.fill(original.replace("Would a short call", "Is a short call"));
  await expect(page.getByLabel("Changes")).toContainText("Is");
  await page.getByRole("button", { name: "Approve with my edit" }).click();
  await expect(page.getByText("Waiting (1)")).toBeVisible();

  // 4. Run again: only the approved lead is drafted.
  await startRunAndWait(page);

  // 5. The leads table shows one in sequence and one still waiting for review.
  await page.getByRole("link", { name: "Leads" }).click();
  await expect(page.getByRole("row", { name: /in sequence/ })).toHaveCount(1);
  await expect(page.getByRole("row", { name: /copy ready/ })).toHaveCount(1);

  // 6. The lead's page shows the waterfall of vendor calls and its timeline.
  await page.getByRole("link", { name: "acme.co.uk", exact: true }).click();
  await expect(page.getByText("Waterfall: every vendor call for this lead")).toBeVisible();
  await expect(page.getByText("Timeline")).toBeVisible();

  // 7. The journey page tells the story: how it arrived, and the detail of every stage.
  await page.getByRole("link", { name: "Journey" }).click();
  await expect(page.getByText("How this lead arrived")).toBeVisible();
  await expect(page.getByText("Added by an operator via the web app")).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(8);
  await expect(page.getByRole("tab", { selected: true })).toContainText("Draft and outreach");
  await page.getByRole("tab", { name: /Email address/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("Vendor calls");
  await page.getByRole("tab", { name: /Review/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("changed by you");
  await page.getByRole("tab", { name: /Review/ }).press("ArrowRight");
  await expect(page.getByRole("tab", { selected: true })).toContainText("Draft and outreach");

  // 8. The one still waiting for review says it is the operator's turn.
  await page.getByRole("link", { name: "Leads", exact: true }).click();
  await page.getByRole("link", { name: /Journey of beta/ }).click();
  await expect(page.getByRole("status")).toContainText("Waiting for you");
  await expect(page.getByRole("tab", { selected: true })).toContainText("Review");

  // 9. The operator can edit a lead; the value becomes theirs.
  await page.getByRole("link", { name: "Open lead to act on it" }).click();
  await page.getByLabel("Name").fill("Beta Holdings");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("heading", { name: "Beta Holdings" })).toBeVisible();
  await expect(page.getByText(/set by you:.*name/)).toBeVisible();
});

test("a wrong password is refused and settings can be saved", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("not right");

  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByLabel("Legal name").fill("Quantra Energy Ltd");
  await page.getByRole("button", { name: "Confirm and save" }).click();
  await expect(page.getByText("Saved and confirmed.")).toBeVisible();

  // A list box keeps the new line you just typed, and saving says so.
  const props = page.getByLabel("Value propositions (one per line)");
  await props.fill("First point");
  await props.press("End");
  await props.press("Enter");
  await props.pressSequentially("Second point");
  await expect(props).toHaveValue("First point\nSecond point");
  await page.getByRole("button", { name: "Confirm and save" }).click();
  await expect(page.getByText("Saved and confirmed.")).toBeVisible();
  await expect(props).toHaveValue("First point\nSecond point");

  // Saving a campaign says it worked.
  await page.getByRole("tab", { name: "Campaigns" }).click();
  await page.getByRole("button", { name: "Save campaign" }).first().click();
  await expect(page.getByText("Campaign saved.")).toBeVisible();

  // Adding a mailbox says so, empties the form and lists it.
  await page.getByRole("tab", { name: "Mailboxes" }).click();
  await page.getByLabel("Address").fill("sam@quantraenergy.com");
  await page.getByRole("button", { name: "Add mailbox" }).click();
  await expect(page.getByText("Mailbox added.")).toBeVisible();
  await expect(page.getByLabel("Address")).toHaveValue("");
  await expect(page.getByText("sam@quantraenergy.com")).toBeVisible();
});
