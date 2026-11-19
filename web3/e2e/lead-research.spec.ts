import { addTarget, expect, leadId, runEngine, signIn, test, unique } from "./helpers";

// A lead's page opens with the research, organised in blocks, and the other cards follow it.
test("the lead page leads with Research: fit, criteria cards, what we learned, the news", async ({ page }) => {
  await signIn(page);
  const domain = unique("research-top");
  await addTarget(page, { website: domain, country: "US" });
  await runEngine(page);
  const id = await leadId(page, domain);
  await page.route(new RegExp(`/api/companies/${id}$`), async (route) => {
    const real = await (await route.fetch()).json();
    real.company.fit_reason = "Meets 1 of 2 must-haves.";
    real.company.research = {
      ...real.company.research,
      hooks: ["Series A last month"],
      // Six products make "What we learned" long enough to start folded.
      products: ["Compiler", "Cloud", "Runtime", "Profiler", "Scheduler", "Dashboard"],
      summary: "Builds an inference compiler for open models.",
      news_items: [{ headline: "Raises a Series A", url: "https://example.com/a", date: "2026-10-30" }],
      qualification: {
        score: 70,
        criteria: [
          { id: "m1", kind: "must_have", criterion: "Builds developer tools", weight: 1, verdict: "met", evidence: "Sells a compiler" },
          { id: "m2", kind: "must_have", criterion: "Remote friendly", weight: 1, verdict: "not_met", evidence: "In person only" },
          { id: "m3", kind: "must_have", criterion: "Has a technical founder", weight: 1, verdict: "unknown" },
          { id: "s1", kind: "signal", criterion: "Open AI roles", weight: 1, verdict: "unknown" },
          { id: "d1", kind: "disqualifier", criterion: "Agency", weight: 1, verdict: "not_met" },
        ],
        why_now: "A fresh round.",
        risks: ["Very small team"],
      },
    };
    await route.fulfill({ json: real });
  });
  await page.goto(`/leads/${id}`);

  const research = page.locator("[data-tour=lead-research]");
  await expect(research).toBeVisible();
  for (const heading of ["How well they fit", "What we learned", "In the news"]) await expect(research.getByRole("heading", { name: heading })).toBeVisible();
  const fold = (name: string) => research.getByRole("button", { name: new RegExp(`^${name}`) });

  // The first block is open; the short news block is open; the long one folds and says what is inside.
  await expect(fold("How well they fit")).toHaveAttribute("aria-expanded", "true");
  await expect(research.getByText("1 of 3 met")).toBeVisible();
  // What was found is a card; what was not is one short list, not a card each.
  await expect(research.getByText("Remote friendly")).toBeVisible();
  await expect(research.getByText("Nothing found either way (1)")).toHaveCount(2); // must-haves and signs
  await expect(research.getByText("Has a technical founder")).toBeVisible();
  await expect(research.getByText("none triggered")).toBeVisible();
  await expect(research.getByText("A fresh round.")).toBeVisible();
  await expect(research.getByText("Very small team")).toBeVisible();
  await expect(fold("In the news")).toHaveAttribute("aria-expanded", "true");
  await expect(fold("What we learned")).toHaveAttribute("aria-expanded", "false");
  await expect(fold("What we learned")).toContainText("Builds an inference compiler");
  await expect(research.getByText("Scheduler")).toHaveCount(0);

  // The reader's choice wins: open it, close another, then the two buttons.
  await fold("What we learned").click();
  await expect(research.getByText("Scheduler")).toBeVisible();
  await fold("In the news").click();
  await expect(research.getByRole("link", { name: "Raises a Series A" })).toHaveCount(0); // folded: only the summary line is left
  await research.getByRole("button", { name: "Collapse all" }).click();
  await expect(fold("How well they fit")).toHaveAttribute("aria-expanded", "false");
  await expect(fold("How well they fit")).toContainText("1 of 3 must-haves met");
  await research.getByRole("button", { name: "Expand all" }).click();
  await expect(research.getByText("Very small team")).toBeVisible();

  // Research comes first, then Emails, then People (with Add a person), as the page's top-to-bottom order.
  const top = (name: string | RegExp) => page.getByRole("heading", { name }).first().evaluate((el) => el.getBoundingClientRect().top);
  const [r, e, p] = [await top("Research"), await top(/^Emails \(/), await top(/^People and addresses/)];
  expect(r).toBeLessThan(e);
  expect(e).toBeLessThan(p);
});
