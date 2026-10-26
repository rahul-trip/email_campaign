import { expect, test, signIn, STAFF } from "./helpers";

test("a platform admin opens the console, finds a customer and grants credits", async ({ page }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  await page.goto("/admin");
  await expect(page.getByText("ADMIN · ALPHA")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  await page.getByRole("link", { name: "Customers" }).click();
  await expect(page.getByRole("heading", { name: "Customers" })).toBeVisible();
  await page.getByRole("link", { name: /default/i }).first().click();

  await page.getByRole("button", { name: "Grant credits" }).click();
  await page.getByLabel("Note").fill("e2e pilot extension");
  await page.getByRole("button", { name: /^Grant \d+/ }).click();
  await expect(page.getByText(/Granted 10 credits/)).toBeVisible();
  await page.getByRole("button", { name: "Done" }).click();

  await page.getByRole("link", { name: "Audit log" }).click();
  await expect(page.getByRole("cell", { name: "credits granted" }).first()).toBeVisible();
});

test("the other console pages load", async ({ page }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  for (const name of ["Users", "Plans", "Settings"]) {
    await page.goto("/admin");
    await page.getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("heading", { name, exact: false }).first()).toBeVisible();
  }
});

test("a platform admin adds a vendor key, sees it masked, reveals it and the audit log shows both", async ({ page }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  await page.goto("/admin");
  await page.getByRole("link", { name: "Vendors & keys" }).click();
  const row = page.getByRole("row", { name: /Tavily/ });
  await row.getByRole("button", { name: /Add key|Replace/ }).click();
  await page.getByLabel("New key").fill("e2e-secret-value-wxyz");
  await page.getByRole("button", { name: "Save key" }).click();
  await expect(row).toContainText("••••wxyz");
  await expect(page.getByText("e2e-secret-value-wxyz")).toHaveCount(0);
  await row.getByRole("button", { name: "Reveal" }).click();
  await expect(page.getByText("e2e-secret-value-wxyz")).toBeVisible();
  await page.getByRole("button", { name: "Done" }).click();
  await page.getByRole("link", { name: "Audit log" }).click();
  await expect(page.getByRole("cell", { name: "vendor key revealed" }).first()).toBeVisible();
});
