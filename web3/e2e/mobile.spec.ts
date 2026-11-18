import { addTarget, leadId, runEngine, signIn, test, unique, expect } from "./helpers";

// On a touch phone: nothing sticks out sideways and every control is a comfortable target.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

const TARGET = 44;

test("on a phone no control is smaller than 44 px and no content is cut off", async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page);
  const domain = unique("mobile");
  await addTarget(page, { website: domain, country: "US" });
  await runEngine(page);
  const id = await leadId(page, domain);
  const routes = ["/", "/review", "/attention", "/leads", `/leads/${id}`, "/targets", "/runs", "/reports", "/campaigns", "/compliance", "/settings", "/settings?tab=mailboxes", "/settings?tab=team"];
  const found: string[] = [];
  for (const route of routes) {
    await page.goto(`/w/default${route}`);
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    const bad = await page.evaluate((minimum) => {
      const out: string[] = [];
      const width = document.documentElement.clientWidth;
      const nodes = document.querySelectorAll<HTMLElement>("button, a[href], select, input:not([type=checkbox]):not([type=radio]):not([type=hidden]), [role=tab], [role=radio], [role=switch]");
      for (const el of nodes) {
        const box = el.getBoundingClientRect();
        if (box.width <= 1 || box.height <= 1 || getComputedStyle(el).visibility === "hidden") continue;
        // A link inside a sentence is text, not a button.
        if (el.tagName === "A" && getComputedStyle(el).display === "inline") continue;
        const name = (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 30);
        if (box.height < minimum - 0.5) out.push(`short ${Math.round(box.height)}px: ${name}`);
        // Wide tables scroll inside their own box; anything else must fit the screen.
        let scrolls = false;
        for (let p: HTMLElement | null = el.parentElement; p; p = p.parentElement) {
          const o = getComputedStyle(p).overflowX;
          if (o === "auto" || o === "scroll") scrolls = true;
        }
        if (!scrolls && box.right > width + 1) out.push(`past the edge (${Math.round(box.right)}px): ${name}`);
      }
      return out;
    }, TARGET);
    for (const line of [...new Set(bad)]) found.push(`${route.replace(/[0-9a-f-]{36}/, ":id")}: ${line}`);
  }
  expect(found, found.join("\n")).toEqual([]);
});
