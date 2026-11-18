import { expect, test, signIn, STAFF } from "./helpers";

test("a platform admin opens the console, finds a customer and grants credits", async ({ page }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  await page.goto("/admin");
  await expect(page.getByText(/Admin console · platform staff/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  await page.getByRole("link", { name: "Customers" }).click();
  await expect(page.getByRole("heading", { name: "Customers" })).toBeVisible();
  await page.getByRole("link", { name: /default/i }).first().click();

  await page.getByRole("button", { name: "Grant AI credits" }).click();
  await page.getByLabel("Note").fill("e2e pilot extension");
  await page.getByRole("button", { name: /^Grant \d+/ }).click();
  await expect(page.getByText(/Granted 500 credits/)).toBeVisible();
  await page.getByRole("button", { name: "Done" }).click();

  await page.getByRole("link", { name: "Audit log" }).click();
  await expect(page.getByRole("cell", { name: "credits granted" }).first()).toBeVisible();
});

test("the other console pages load", async ({ page }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  for (const name of ["Users", "Plans", "Settings", "Lead directory"]) {
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

test("staff add an AI model with everything it needs, make it the default, and go back", async ({ page }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  await page.goto("/admin/vendors");
  await page.getByRole("button", { name: "Add a model" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name shown here").fill("E2E DeepSeek");
  await dialog.getByLabel("Code").fill("e2e-deepseek");
  await dialog.getByLabel("Provider type").selectOption("openai_compatible");
  await dialog.getByLabel("Model name at the provider").fill("deepseek-ai/DeepSeek-V3");
  await expect(dialog.getByRole("button", { name: "Save model" })).toBeDisabled(); // needs a base URL
  await dialog.getByLabel(/Base URL/).fill("https://api.deepinfra.com/v1/openai");
  await dialog.getByLabel("API key").fill("e2e-placeholder-key-1234");
  await dialog.getByLabel("AI credits per million input tokens").fill("30");
  await dialog.getByLabel("AI credits per million output tokens").fill("110");
  await dialog.getByRole("button", { name: "Save model" }).click();
  await expect(page.getByText("E2E DeepSeek")).toBeVisible();
  await expect(page.getByText("••••1234")).toBeVisible();
  await page.getByRole("button", { name: "Make default" }).click();
  await expect(page.getByText("default", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Go back to the environment's settings" }).click();
  await expect(page.getByText(/No default chosen/)).toBeVisible();
  await page.getByRole("row", { name: /E2E DeepSeek/ }).getByRole("button", { name: "Remove" }).click();
  await expect(page.getByText("E2E DeepSeek")).toHaveCount(0);
});
