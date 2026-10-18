import { expect, test } from "@playwright/test";

const PASSWORD = "e2e-password-123";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
});

test("a lead is deleted only after its domain is typed, and is then gone", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("link", { name: "Targets" }).click();
  await page.getByLabel("Website or domain").fill("delete-me.com");
  await page.getByLabel("Country").fill("US");
  await page.getByRole("button", { name: "Add target" }).click();
  await expect(page.getByText("accepted").first()).toBeVisible();

  await page.getByRole("link", { name: "Leads", exact: true }).click();
  await page.getByRole("link", { name: "delete-me.com", exact: true }).click();

  const remove = page.getByRole("button", { name: "Delete this lead permanently" });
  await expect(remove).toBeDisabled();
  await page.getByLabel("Type delete-me.com to confirm").fill("delete-me");
  await expect(remove).toBeDisabled(); // close is not enough
  await page.getByLabel("Type delete-me.com to confirm").fill("delete-me.com");
  await expect(remove).toBeEnabled();
  await remove.click();

  await expect(page).toHaveURL(/\/leads$/);
  await expect(page.getByRole("link", { name: "delete-me.com", exact: true })).toHaveCount(0);
  // Because the domain was not blocked, it can simply be added again.
  await page.getByRole("link", { name: "Targets" }).click();
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Website or domain").fill("delete-me.com");
  await page.getByRole("button", { name: "Add target" }).click();
  await expect(page.getByRole("row", { name: /accepted delete-me\.com/ })).toBeVisible();
});
