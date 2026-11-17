import { test as base, type Page } from "@playwright/test";
import { EMAIL, PASSWORD, addTarget, expect, runEngine, unique } from "./helpers";

// These tests need the tour to open by itself, so they use the plain test, not the helper that
// marks the tour as seen.
const test = base;
const tour = (page: Page) => page.getByRole("dialog", { name: "Product tour" });

async function signIn(page: Page) {
  await page.goto("/sign-in");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("the tour opens on a first visit, and Skip tour closes it for good", async ({ page }) => {
  await signIn(page);
  await expect(tour(page)).toContainText("Welcome to Outbound");
  await page.getByRole("button", { name: "Skip tour" }).click();
  await expect(tour(page)).toBeHidden();
  await page.reload();
  await expect(page.locator("[data-tour=today-hero]")).toBeVisible();
  await expect(tour(page)).toBeHidden();
  // It can be started again by hand.
  await page.getByRole("button", { name: "Your account" }).click();
  await page.getByRole("menuitem", { name: "Take the guided tour" }).click();
  await expect(tour(page)).toContainText("Welcome to Outbound");
});

test("it is short: nine steps across seven screens, with buttons and arrow keys; Escape ends it", async ({ page }) => {
  await signIn(page);
  await expect(tour(page)).toContainText("1 of 9");
  await expect(page.getByRole("button", { name: "Back" })).toHaveCount(0);
  await page.getByRole("button", { name: "Show me" }).click();
  await expect(tour(page)).toContainText("Your day starts here");
  await page.getByRole("button", { name: "Back" }).click();
  await expect(tour(page)).toContainText("Welcome to Outbound");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(tour(page)).toContainText("Approve in one keystroke");
  await expect(page).toHaveURL(/\/review$/);
  await page.keyboard.press("Escape");
  await expect(tour(page)).toBeHidden();
});

test("every step of the tour points at something that exists", async ({ page }) => {
  test.setTimeout(240_000);
  await page.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
  await signIn(page);
  await expect(page.locator("[data-tour=today-hero]")).toBeVisible();
  // One lead waiting for review, so every screen has something to point at.
  await addTarget(page, { website: unique("tour-test"), country: "US" });
  await runEngine(page);
  await page.reload();
  await page.getByRole("button", { name: "Your account" }).click();
  await page.getByRole("menuitem", { name: "Take the guided tour" }).click();
  for (let guard = 0; guard < 80 && (await tour(page).isVisible()); guard++) {
    // "none" is a centred message with nothing to point at; anything else must be found.
    await expect(tour(page), await tour(page).locator("h2").textContent() ?? "").toHaveAttribute("data-target-found", /true|none/);
    await tour(page).getByRole("button", { name: /^(Show me|Next|Let's go)$/ }).click();
  }
  await expect(tour(page)).toBeHidden();
});
