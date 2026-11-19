import { addTarget, expect, runEngine, signIn, test, unique } from "./helpers";

// The notifications panel on a phone: it used to hang from the bell and run off the left of the screen, see-through.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test("the notifications panel fits a phone and is solid", async ({ page }) => {
  await signIn(page);
  await addTarget(page, { website: unique("bell-phone"), country: "US" });
  await runEngine(page); // a finished run leaves a notice
  await page.goto("/");
  await page.getByRole("button", { name: /^Notifications/ }).click();
  const panel = page.getByRole("dialog", { name: "Notifications" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Notifications", { exact: true })).toBeVisible();
  const box = (await panel.boundingBox())!;
  expect(box.x, "starts inside the screen").toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, "ends inside the screen").toBeLessThanOrEqual(390);
  expect(box.width).toBeGreaterThan(330); // it uses the screen, less a gutter
  const background = await panel.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(background, "solid, so the page does not show through").not.toMatch(/rgba\(.*,\s*0(\.\d+)?\)$/);
});
