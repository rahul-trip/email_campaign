import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "e2e-password-123";
const tour = (page: Page) => page.getByRole("dialog", { name: "Product tour" });

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** One lead waiting for review, so every screen in the tour has something to point at. */
async function makeALead(page: Page) {
  await page.getByRole("link", { name: "Targets" }).click();
  await page.getByLabel("Website or domain").fill("tour-test.com");
  await page.getByLabel("Country").fill("US");
  await page.getByRole("button", { name: "Add target" }).click();
  await expect(page.getByText("accepted").first()).toBeVisible();
  await page.getByRole("link", { name: "Runs" }).click();
  await page.getByRole("button", { name: "Start run" }).click();
  await expect(page.locator("tbody tr").first()).toContainText("succeeded", { timeout: 30_000 });
}

test("the tour opens on a first visit, and End tour closes it for good", async ({ page }) => {
  await signIn(page);
  await expect(tour(page)).toContainText("Welcome to Outbound");
  await page.getByRole("button", { name: "End tour" }).click();
  await expect(tour(page)).toBeHidden();
  await page.reload();
  await expect(page.getByRole("link", { name: /Review/ })).toBeVisible();
  await expect(tour(page)).toBeHidden();
  // It can be started again by hand.
  await page.getByRole("button", { name: "Tour" }).click();
  await expect(tour(page)).toContainText("Welcome to Outbound");
});

test("Skip section jumps to the first step of the next screen", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(tour(page)).toContainText("Targets · section 2");
  await expect(page).toHaveURL(/\/targets$/);
  await page.getByRole("button", { name: "Skip section" }).click();
  await expect(tour(page)).toContainText("Runs · section 3");
  await expect(tour(page)).toContainText("step 1 of");
  await expect(page).toHaveURL(/\/runs$/);
  // Escape ends it too.
  await page.keyboard.press("Escape");
  await expect(tour(page)).toBeHidden();
});

test("every step of the tour points at something that exists", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
  await signIn(page);
  await makeALead(page);
  await page.getByRole("button", { name: "Tour" }).click();
  for (let guard = 0; guard < 60 && (await tour(page).isVisible()); guard++) {
    // "none" is a centred message with nothing to point at; anything else must be found.
    await expect(tour(page)).toHaveAttribute("data-target-found", /true|none/);
    const button = page.getByRole("button", { name: /^(Next|Finish)$/ });
    await button.click();
  }
  await expect(tour(page)).toBeHidden();
});
