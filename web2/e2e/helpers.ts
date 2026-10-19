import { expect, test as base, type Page } from "@playwright/test";

export const PASSWORD = "e2e-password-123";
const WRITE = { "X-Requested-With": "outbound" };

/**
 * Every test fails if the page throws, logs an error, or gets a 5xx from the server. The 401
 * before signing in is how the app learns it must show the sign-in form, so it is allowed.
 * The guided tour is marked as seen, so it does not cover the page (tour.spec.ts tests it).
 */
export const test = base.extend<{ problems: string[] }>({
  problems: [
    async ({ page }, use) => {
      const problems: string[] = [];
      page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
      page.on("console", (message) => {
        if (message.type() === "error" && !message.text().includes("401")) problems.push(`console: ${message.text()}`);
      });
      page.on("response", (response) => {
        if (response.status() >= 500) problems.push(`HTTP ${response.status()} ${response.url()}`);
      });
      await use(problems);
      expect(problems, "the page reported errors").toEqual([]);
    },
    { auto: true },
  ],
  page: async ({ page }, use) => {
    await page.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
    await use(page);
  },
});
export { expect };

export async function signIn(page: Page) {
  await page.goto("/");
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

/** A unique domain per test, so tests never depend on each other's leads. */
export const unique = (stem: string, tld = "com") => `${stem}-${Date.now().toString(36)}.${tld}`;

/** Add a target through the API (the Add leads screen has its own test). */
export async function addTarget(page: Page, target: Record<string, string>) {
  const response = await page.request.post("/api/targets", { data: target, headers: WRITE });
  expect(response.ok()).toBeTruthy();
}

/** Queue a run and wait until the worker has finished it. */
export async function runEngine(page: Page) {
  const run = await (await page.request.post("/api/runs", { data: {}, headers: WRITE })).json();
  await expect
    .poll(async () => (await (await page.request.get(`/api/runs/${run.id}`)).json()).status, { timeout: 30_000 })
    .toMatch(/succeeded|failed|cancelled/);
}

/** The id of the lead with this domain. */
export async function leadId(page: Page, domain: string): Promise<string> {
  const found = await (await page.request.get(`/api/companies?q=${encodeURIComponent(domain)}`)).json();
  return found.items[0].id;
}
