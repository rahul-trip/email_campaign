import { expect, signIn, test } from "./helpers";

// The Outbound mark ("The Infinite Vector"): the favicon is served, and the mark is on the sign-in page and in the app.
test("the logo is the favicon, on the sign-in page and in the sidebar", async ({ page, request }) => {
  const icon = await request.get("/favicon.svg");
  expect(icon.status()).toBe(200);
  expect(icon.headers()["content-type"]).toContain("svg");
  expect(await icon.text()).toContain("<svg");

  // Browsers that cannot use the SVG (Safari's tabs, a phone's home screen) get a PNG.
  for (const file of ["/favicon-32.png", "/apple-touch-icon.png"]) {
    const png = await request.get(file);
    expect(png.status(), file).toBe(200);
    expect(png.headers()["content-type"], file).toContain("image/png");
  }

  await page.goto("/sign-in");
  await expect(page.locator("link[rel=icon][type='image/svg+xml']")).toHaveAttribute("href", "/favicon.svg");
  await expect(page.locator("link[rel=icon][type='image/png']")).toHaveAttribute("href", "/favicon-32.png");
  await expect(page.locator("link[rel=apple-touch-icon]")).toHaveAttribute("href", "/apple-touch-icon.png");
  await expect(page.locator("[data-brand-mark]")).toBeVisible();

  await signIn(page);
  const mark = page.locator("aside [data-brand-mark]").first();
  await expect(mark).toBeVisible();
  // It follows the theme: indigo from the primary token, the arrow from the teal one.
  await expect(mark.locator("path").first()).toHaveAttribute("stroke", "var(--primary)");
  await expect(mark.locator("path").last()).toHaveAttribute("stroke", "var(--teal)");
});
