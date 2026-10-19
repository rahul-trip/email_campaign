import { test as base, type Page } from "@playwright/test";
import { PASSWORD, addTarget, expect, runEngine, unique } from "./helpers";

// These tests need the tour to open by itself, so they use the plain test, not the helper that
// marks the tour as seen.
const test = base;
const tour = (page: Page) => page.getByRole("dialog", { name: "Product tour" });

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("the tour opens on a first visit, and End tour closes it for good", async ({ page }) => {
  await signIn(page);
  await expect(tour(page)).toContainText("Welcome to Outbound");
  await page.getByRole("button", { name: "End tour" }).click();
  await expect(tour(page)).toBeHidden();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(tour(page)).toBeHidden();
  // It can be started again by hand.
  await page.getByRole("button", { name: "Tour" }).click();
  await expect(tour(page)).toContainText("Welcome to Outbound");
});

test("Next, Back and Skip section move through it; Escape ends it", async ({ page }) => {
  await signIn(page);
  await expect(tour(page)).toContainText("step 1 of");
  await expect(page.getByRole("button", { name: "Back" })).toHaveCount(0);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(tour(page)).toContainText("The main menu");
  await page.getByRole("button", { name: "Back" }).click();
  await expect(tour(page)).toContainText("Welcome to Outbound");
  await page.getByRole("button", { name: "Skip section" }).click();
  await expect(tour(page)).toContainText("Add leads · section 2");
  await expect(page).toHaveURL(/\/targets$/);
  await page.getByRole("button", { name: "Skip section" }).click();
  await expect(tour(page)).toContainText("Runs · section 3");
  await expect(page).toHaveURL(/\/runs$/);
  await page.keyboard.press("Escape");
  await expect(tour(page)).toBeHidden();
});

test("every step of the tour points at something that exists", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
  await signIn(page);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  // One lead waiting for review, so every screen has something to point at.
  await addTarget(page, { website: unique("tour-test"), country: "US" });
  await runEngine(page);
  await page.reload();
  await page.getByRole("button", { name: "Tour" }).click();
  for (let guard = 0; guard < 80 && (await tour(page).isVisible()); guard++) {
    // "none" is a centred message with nothing to point at; anything else must be found.
    await expect(tour(page), await tour(page).locator("h2").textContent() ?? "").toHaveAttribute("data-target-found", /true|none/);
    await page.getByRole("button", { name: /^(Next|Finish)$/ }).click();
  }
  await expect(tour(page)).toBeHidden();
});
