import { addTarget, expect, leadId, runEngine, signIn, test, unique } from "./helpers";

test("a lead held for consent is released by adding a person who consented", async ({ page }) => {
  await signIn(page);
  const domain = unique("consent", "in");
  await addTarget(page, { website: domain, country: "IN" });
  await runEngine(page);

  // Needs attention offers the action that fixes it, not a release the server would refuse.
  await page.goto("/attention");
  const row = page.getByRole("listitem").filter({ hasText: domain });
  await expect(row).toBeVisible();
  await row.getByRole("link", { name: "Add a person with consent" }).click();

  await expect(page.getByText("Held: Consent required")).toBeVisible();
  const card = page.locator("#add-person");
  await card.getByLabel("Name").fill("Asha");
  // One word without an email is refused: the address finder needs both names.
  await expect(card.getByText("First and last name, or give their work email")).toBeVisible();
  await card.getByLabel("Name").fill("Asha Rao");
  await card.getByText("This person has given consent to be contacted").click();
  await expect(card.getByRole("button", { name: "Add person and release the hold" })).toBeDisabled();
  await card.getByLabel("Evidence").fill("Business card from the energy expo, 2026");
  await card.getByRole("button", { name: "Add person and release the hold" }).click();
  await expect(page.getByText("Added, and the hold is released.")).toBeVisible();
  await expect(page.getByText("Held: Consent required")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.getByText("consent recorded")).toBeVisible();
});

test("edit a lead; delete needs the typed domain and removes it", async ({ page }) => {
  await signIn(page);
  const domain = unique("delete-me");
  await addTarget(page, { website: domain, country: "US" });
  await page.goto(`/leads/${await leadId(page, domain)}`);

  await page.getByRole("textbox", { name: "Name", exact: true }).last().fill("Delete Me Ltd");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("heading", { name: "Delete Me Ltd" })).toBeVisible();
  await expect(page.getByText("Set by you, kept as you set it")).toBeVisible();

  await page.getByRole("button", { name: "Delete permanently…" }).click();
  const dialog = page.getByRole("dialog");
  const go = dialog.getByRole("button", { name: "Delete permanently" });
  await expect(go).toBeDisabled();
  await dialog.getByLabel(`Type ${domain} to confirm`).fill("wrong.com");
  await expect(go).toBeDisabled();
  await dialog.getByLabel(`Type ${domain} to confirm`).fill(domain);
  await go.click();
  await expect(page).toHaveURL(/\/leads$/);
  await page.goto(`/leads?q=${domain}`);
  await expect(page.getByText("No lead matches")).toBeVisible();
});

test("suppressing a domain asks first and reports what it cancelled", async ({ page }) => {
  await signIn(page);
  const domain = unique("suppress-me");
  await addTarget(page, { website: domain, country: "US" });
  await page.goto(`/leads/${await leadId(page, domain)}`);
  await page.getByRole("button", { name: "Suppress this domain" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Suppress domain" }).click();
  await expect(page.getByText(/Suppressed\. \d+ unsent email/)).toBeVisible();
});
