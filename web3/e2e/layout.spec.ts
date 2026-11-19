import { addTarget, expect, leadId, runEngine, signIn, test, unique } from "./helpers";

// No screen may scroll sideways as a whole, on a laptop or on a phone. Wide tables scroll inside their own frame; a long
// unbroken value (a link in a note) wraps inside its box. Found on the live site by looking at every screen.
const SIZES = [
  { name: "laptop", width: 1440, height: 900 },
  { name: "phone", width: 390, height: 844 },
] as const;

test("no screen scrolls sideways on a laptop or a phone", async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page);
  const domain = unique("layout");
  await addTarget(page, { website: domain, country: "US" });
  await runEngine(page);
  const id = await leadId(page, domain);
  // A note with a very long link in it, as discovery writes them.
  await page.route(new RegExp(`/api/companies/${id}$`), async (route) => {
    const real = await (await route.fetch()).json();
    real.notes = [{ id: "n1", body: `Found by discovery (articles): Sales research. | https://example.com/${"x".repeat(90)}`, source: "import", created_at: new Date().toISOString() }];
    await route.fulfill({ json: real });
  });

  const routes = ["/", "/review", "/linkedin", "/attention", "/leads", "/leads?bucket=ready", "/targets", "/runs", "/campaigns", "/reports", "/compliance", "/settings", "/settings?tab=limits", `/leads/${id}`, `/leads/${id}?tab=journey`, "/onboarding"];
  const wide: string[] = [];
  for (const size of SIZES) {
    await page.setViewportSize({ width: size.width, height: size.height });
    for (const route of routes) {
      await page.goto(`/w/default${route}`);
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (over > 1) wide.push(`${size.name} ${route.replace(id, ":id")}: ${over}px too wide`);
      // The cause of the Leads page's sideways scroll: an absolutely placed element (the hidden "Links" label) inside a
      // scrolling frame that does not contain it sits where the table's scrolled width ends and stretches the page.
      const leaks = await page.evaluate(() => {
        const out: string[] = [];
        for (const el of document.querySelectorAll<HTMLElement>("*")) {
          if (getComputedStyle(el).position !== "absolute") continue;
          let frame: HTMLElement | null = null;
          for (let p = el.parentElement; p; p = p.parentElement) {
            const o = getComputedStyle(p).overflowX;
            if (o === "auto" || o === "scroll") {
              frame = p;
              break;
            }
          }
          if (frame && el.offsetParent && !frame.contains(el.offsetParent)) out.push(`${el.tagName.toLowerCase()} "${(el.textContent ?? "").trim().slice(0, 20)}"`);
        }
        return out;
      });
      if (leaks.length && size.name === "laptop") wide.push(`${route.replace(id, ":id")}: positioned outside its scrolling frame: ${[...new Set(leaks)].join(", ")}`);
    }
  }
  expect(wide, wide.join("\n")).toEqual([]);
});
