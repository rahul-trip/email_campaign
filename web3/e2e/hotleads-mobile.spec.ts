import { expect, signIn, test } from "./helpers";

// The Hot leads page on a phone, with rows like the live workspace's: long names, a long
// "why it fits", both flags and a fit ring. Nothing may overlap or run off the screen.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

const row = (n: number, name: string, fit: number) => ({
  item: {
    id: `li-${n}`,
    company_id: `co-${n}`,
    contact_id: `ct-${n}`,
    note: `${name}'s careers page lists Founding Kernel Engineer and Cloud Inference Engineer roles for a lean in-person SF team. I build production agentic systems and would like to connect.`,
    message: "Justin, the open compiler and cloud work you are doing is close to what I build. Would a short call next week make sense?",
    state: "drafted",
    issues: [],
    edited: false,
    sent_at: null,
    created_at: "2026-11-19T10:00:00Z",
  },
  company_name: name,
  domain: `${name.toLowerCase()}.example`,
  person: "Justin Burke",
  title: "Founding Engineer and Co-founder",
  profile: "https://www.linkedin.com/in/justin-burke",
  fit_score: fit,
  hot: true,
  company_bucket: "ready",
  company_status: "failed",
  failure_kind: "no_email",
  country_code: "US",
  fit_reason: "Meets 5 of 6 must-haves; missing: remote-friendly with US Eastern/Pacific overlap; signs they may buy now: recent seed, Series A or Series B funding round, open roles for AI, LLM or agent engineers",
});

test("Hot leads rows fit a phone: nothing overlaps and nothing runs off the screen", async ({ page }) => {
  await signIn(page);
  const rows = [row(1, "Luminal", 89), row(2, "Morph", 86), row(3, "Lightning", 91)];
  await page.route("**/api/linkedin?**", (route) => route.fulfill({ json: { items: rows, total: rows.length } }));
  await page.goto("/w/default/linkedin");
  await expect(page.getByText("Luminal").first()).toBeVisible();

  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(await overflow()).toBeLessThanOrEqual(1);

  // Collapsed: the flags sit above the one-tap button, not under the fit ring or the button.
  const first = page.locator("[data-tour=linkedin-list] > div").first();
  const flag = first.getByText("No email we could prove");
  const copy = first.getByRole("button", { name: /Copy note/ });
  const ring = first.locator("svg").first();
  const [f, c] = [await flag.boundingBox(), await copy.boundingBox()];
  expect({ flag: f, copy: c }).toBeTruthy();
  expect(c!.y, `flag ${JSON.stringify(f)} copy ${JSON.stringify(c)}`).toBeGreaterThanOrEqual(f!.y + f!.height - 1);
  expect(f!.x + f!.width).toBeLessThanOrEqual(390);
  await expect(ring).toBeVisible();

  // Expanded: the draft card's buttons stay on the screen too.
  await page.getByRole("button", { name: "Expand all" }).click();
  await expect(page.getByText("Connection note").first()).toBeVisible();
  expect(await overflow()).toBeLessThanOrEqual(1);
  const past = await page.evaluate(() => {
    const out: string[] = [];
    for (const el of document.querySelectorAll<HTMLElement>("[data-tour=linkedin-list] button, [data-tour=linkedin-list] a")) {
      const box = el.getBoundingClientRect();
      if (box.width > 1 && box.right > document.documentElement.clientWidth + 1) out.push((el.textContent ?? "").trim().slice(0, 30));
    }
    return out;
  });
  expect(past).toEqual([]);
});
