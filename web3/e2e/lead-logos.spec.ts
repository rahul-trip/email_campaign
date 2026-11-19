import { addTarget, expect, leadId, runEngine, signIn, test, unique } from "./helpers";

// The company's own logo (its website's icon) marks the lead everywhere the lead is the subject: the lead page, the
// Emails ready queue and reader, and Today's email cards. The icon service is stubbed so the test needs no network.
const PIXEL = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

test("the lead's logo is on the lead page and on Emails ready", async ({ page }) => {
  await page.route("https://icons.duckduckgo.com/**", (route) => route.fulfill({ status: 200, contentType: "image/png", body: PIXEL }));
  await signIn(page);
  const domain = unique("logo-lead");
  await addTarget(page, { website: domain, country: "US" });
  await runEngine(page);
  const id = await leadId(page, domain);

  // The lead page: in the page's own heading, at the large size.
  await page.goto(`/leads/${id}`);
  const header = page.getByRole("heading", { level: 1 }).locator("[data-lead-logo]");
  await expect(header).toBeVisible();
  expect((await header.boundingBox())!.width).toBeGreaterThan(44);

  // Emails ready: on the queue card and on the email being read.
  await page.goto("/review");
  await expect(page.getByRole("navigation", { name: "Emails waiting" }).locator("[data-lead-logo]").first()).toBeVisible();
  await expect(page.locator("[data-tour=review-editor] [data-lead-logo]")).toBeVisible();

  // Today: on each email card.
  await page.goto("/");
  await expect(page.locator("[data-tour=ready-drafts] [data-lead-logo]").first()).toBeVisible();
});
