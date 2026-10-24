import { expect, test as base, type Page } from "@playwright/test";

// The accounts scripts/e2e_server.py creates.
export const EMAIL = "operator@e2e.example"; // admin of the "default" workspace
export const STAFF = "staff@e2e.example"; // a superadmin with no workspace of their own
export const PASSWORD = "e2e-password-1234567";
const WRITE = { "X-Requested-With": "outbound" };

/**
 * Every test fails if the page throws, logs an error, or gets a 5xx from the server. A 4xx answer is a refusal the page shows to the person (a 401 before signing in, a rejected form), so its console line is allowed.
 * The guided tour is marked as seen, so it does not cover the page (tour.spec.ts tests it).
 */
export const test = base.extend<{ problems: string[] }>({
  problems: [
    async ({ page }, use) => {
      const problems: string[] = [];
      page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
      page.on("console", (message) => {
        if (message.type() === "error" && !/status of 4\d\d/.test(message.text())) problems.push(`console: ${message.text()}`);
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

/** Sign in on the sign-in page. Without ``landed``, wait for the workspace's dashboard. */
export async function signIn(page: Page, email = EMAIL, landed = true) {
  await page.goto("/sign-in");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  if (landed) await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

/** The token in the newest emailed link of this kind (the test server keeps every email). */
export async function emailedToken(page: Page, kind: "invite" | "reset", to: string): Promise<string> {
  const pattern = kind === "invite" ? /\/invite\/([\w-]+)/ : /reset-password\?token=([\w-]+)/;
  const sent: { to: string; text: string }[] = await (await page.request.get("/e2e/outbox")).json();
  const found = sent.filter((m) => m.to === to).map((m) => m.text.match(pattern)?.[1]).filter(Boolean);
  expect(found.length, `an emailed ${kind} link to ${to}`).toBeGreaterThan(0);
  return found[found.length - 1]!;
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
