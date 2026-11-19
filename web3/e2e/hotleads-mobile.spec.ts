import { expect, signIn, test } from "./helpers";

// The LinkedIn ready page on a phone, with rows like the live workspace's: long names, a long
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

// A second person at the same company: they sit together under it.
const second = (n: number, name: string) => ({ ...row(n, name, 89), item: { ...row(n, name, 89).item, id: `li-${n}b`, contact_id: `ct-${n}b` }, person: "Priya Rao", title: "Head of Talent" });

test("LinkedIn ready fits a phone: companies are a row to swipe, the people at one are together, nothing runs off the screen", async ({ page }) => {
  await signIn(page);
  const rows = [row(1, "Luminal", 89), second(1, "Luminal"), row(2, "Morph", 86), row(3, "Lightning", 91)];
  await page.route("**/api/linkedin?**", (route) => route.fulfill({ json: { items: rows, total: rows.length } }));
  await page.goto("/w/default/linkedin");
  await expect(page.getByText("Luminal").first()).toBeVisible();

  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(await overflow()).toBeLessThanOrEqual(1);

  // Three companies, not four messages: Luminal's two people share one card.
  const strip = page.locator("[data-tour=linkedin-strip] > ul");
  await expect(strip.locator(":scope > li")).toHaveCount(3);
  const luminal = strip.locator(":scope > li").first();
  await expect(luminal).toContainText("2 people");
  await expect(luminal).toContainText("Justin Burke");
  await expect(luminal).toContainText("Priya Rao");

  // The cards are a row to swipe: more than fits the screen, the first one narrower than it.
  const sizes = await strip.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth, first: (el.children[0] as HTMLElement).getBoundingClientRect().width }));
  expect(sizes.scroll, "the row scrolls sideways").toBeGreaterThan(sizes.client + 50);
  expect(sizes.first).toBeLessThan(390);

  // The chosen company reads below with both people, and its buttons stay on the screen.
  const reader = page.locator("[data-tour=linkedin-reader]");
  await expect(reader.getByText("People at Luminal (2)")).toBeVisible();
  await expect(reader.getByText("Justin Burke")).toBeVisible();
  await expect(reader.getByText("Priya Rao")).toBeVisible();
  await expect(reader.getByText("Connection note").first()).toBeVisible();
  expect(await overflow()).toBeLessThanOrEqual(1);
  const past = await page.evaluate(() => {
    const out: string[] = [];
    for (const el of document.querySelectorAll<HTMLElement>("[data-tour=linkedin-reader] button, [data-tour=linkedin-reader] a")) {
      const box = el.getBoundingClientRect();
      if (box.width > 1 && box.right > document.documentElement.clientWidth + 1) out.push((el.textContent ?? "").trim().slice(0, 30));
    }
    return out;
  });
  expect(past).toEqual([]);

  // Picking another company shows its people instead.
  await strip.locator(":scope > li").nth(1).getByRole("button").click();
  await expect(reader.getByText("People at Morph (1)")).toBeVisible();
  await expect(reader.getByText("Priya Rao")).toBeHidden();
});

// On a phone the filters are one line (search and a Filters button) that opens, not four rows of controls.
test("LinkedIn ready filters fold into one line on a phone and say how many are on", async ({ page }) => {
  await signIn(page);
  const rows = [row(1, "Luminal", 89), row(2, "Morph", 86)];
  await page.route("**/api/linkedin?**", (route) => route.fulfill({ json: { items: rows, total: rows.length } }));
  await page.goto("/w/default/linkedin");
  await expect(page.getByText("Luminal").first()).toBeVisible();

  const filters = page.getByRole("button", { name: /^Filters/ });
  const search = page.getByLabel("Search by company, website or person");
  await expect(filters).toBeVisible();
  await expect(filters).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("button", { name: "Hot only" })).toBeHidden();
  const [s, f] = [await search.boundingBox(), await filters.boundingBox()];
  expect(Math.abs(s!.y - f!.y), "search and Filters share a line").toBeLessThan(12);

  await filters.click();
  await expect(filters).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("button", { name: "Hot only" }).click();
  await expect(filters).toContainText("1"); // one filter on
  await expect(page.getByRole("button", { name: "Hot only" })).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
});
