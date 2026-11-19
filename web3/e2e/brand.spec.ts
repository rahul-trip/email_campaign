import { expect, signIn, test } from "./helpers";

// The Outbound mark ("The Infinite Vector"): the favicon is served, and the mark is on the sign-in page and in the app.
test("the logo is the favicon, on the sign-in page and in the sidebar", async ({ page, request }) => {
  const icon = await request.get("/favicon.svg");
  expect(icon.status()).toBe(200);
  expect(icon.headers()["content-type"]).toContain("svg");
  expect(await icon.text()).toContain("<svg");

  await page.goto("/sign-in");
  await expect(page.locator("link[rel=icon]")).toHaveAttribute("href", "/favicon.svg");
  await expect(page.locator("[data-brand-mark]")).toBeVisible();

  await signIn(page);
  const mark = page.locator("aside [data-brand-mark]").first();
  await expect(mark).toBeVisible();
  // It follows the theme: indigo from the primary token, the arrow from the teal one.
  await expect(mark.locator("path").first()).toHaveAttribute("stroke", "var(--primary)");
  await expect(mark.locator("path").last()).toHaveAttribute("stroke", "var(--teal)");
});
