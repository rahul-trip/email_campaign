import { addTarget, expect, runEngine, signIn, test, unique } from "./helpers";

// Failed leads on a phone: the richer rows and the filter bar stay on the screen.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test("Failed leads rows and filters fit a phone", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page);
  const domain = unique("decide-phone", "in");
  await addTarget(page, { website: domain, country: "IN" });
  await runEngine(page);
  await page.goto("/w/default/attention");
  const row = page.getByRole("listitem").filter({ hasText: domain });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: /Details/ }).click();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  const past = await page.evaluate(() => {
    const out: string[] = [];
    for (const el of document.querySelectorAll<HTMLElement>("main button, main a, main select, main input")) {
      const box = el.getBoundingClientRect();
      let scrolls = false;
      for (let p: HTMLElement | null = el.parentElement; p; p = p.parentElement) {
        const o = getComputedStyle(p).overflowX;
        if (o === "auto" || o === "scroll") scrolls = true;
      }
      if (!scrolls && box.width > 1 && box.right > document.documentElement.clientWidth + 1) out.push((el.textContent ?? el.getAttribute("aria-label") ?? "").trim().slice(0, 30));
    }
    return out;
  });
  expect(past).toEqual([]);
});
