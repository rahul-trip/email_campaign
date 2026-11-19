import { addTarget, expect, leadId, openCard, runEngine, signIn, test, unique } from "./helpers";

// Roles are picked from chips or typed, and what to do with who is found is chosen: nothing, email,
// a LinkedIn message, or both. The same dialog works for one lead and for the leads on the list.
test("find more people on a lead page: choose roles and what to do with them", async ({ page }) => {
  await signIn(page);
  const domain = unique("people");
  await addTarget(page, { website: domain, country: "US" });
  await runEngine(page);
  await page.goto(`/leads/${await leadId(page, domain)}`);
  await openCard(page, "People and addresses");
  await page.getByRole("button", { name: /Find (more|people)/ }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: /Find more people at/ })).toBeVisible();

  await dialog.getByRole("button", { name: "Recruiter", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "Recruiter", exact: true })).toHaveAttribute("aria-pressed", "true");
  await dialog.getByLabel("Another role").fill("Head of Operations");
  await dialog.getByRole("button", { name: "Add", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "Head of Operations" })).toHaveAttribute("aria-pressed", "true");
  await dialog.getByRole("radio", { name: /Both/ }).check();

  await dialog.getByRole("button", { name: "Search", exact: true }).click();
  await expect(dialog.getByRole("status")).toContainText(/Found \d+, added \d+/);
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(dialog).toHaveCount(0);
});

test("find more people for the leads on the list", async ({ page }) => {
  await signIn(page);
  const domain = unique("peoplelist");
  await addTarget(page, { website: domain, country: "US" });
  await page.goto(`/leads?q=${domain}`);
  await page.getByRole("button", { name: /Find more people/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: /Find more people at/ })).toBeVisible();
  await dialog.getByRole("button", { name: "Head of Talent", exact: true }).click();
  await dialog.getByRole("button", { name: /^Search/ }).click();
  await expect(dialog.getByRole("status")).toBeVisible();
});
