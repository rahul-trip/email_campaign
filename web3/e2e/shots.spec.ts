import { addTarget, leadId, runEngine, signIn, test, unique } from "./helpers";

// A screenshot of every screen, on demand, so a change can be looked at before and after.
// Not part of the normal run: `cd web2 && npm run build && SHOTS=1 npx playwright test shots`
// writes web2/shots/<theme>-<size>/<screen>.png. It compares nothing.
test.skip(!process.env.SHOTS, "set SHOTS=1 to write the screenshots");

const SIZES = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } } as const;
const THEMES = ["light", "dark"] as const;
// Mirrors SETTINGS_TABS in src/pages/settingsTabs.ts.
const SETTINGS_TABS = ["setup", "profile", "mailboxes", "limits", "plan", "team", "integrations", "account"];

test("screenshots of every screen", async ({ page }) => {
  test.setTimeout(600_000);
  await signIn(page);
  const domain = unique("shots");
  await addTarget(page, { website: domain, country: "US" });
  await runEngine(page);
  const id = await leadId(page, domain);

  const screens: [string, string][] = [
    ["dashboard", "/"],
    ["review", "/review"],
    ["attention", "/attention"],
    ["leads", "/leads"],
    ["lead", `/leads/${id}`],
    ["lead-journey", `/leads/${id}/journey`],
    ["add-leads", "/targets"],
    ["runs", "/runs"],
    ["onboarding", "/onboarding"],
    ["campaigns", "/campaigns"],
    ["reports", "/reports"],
    ["compliance", "/compliance"],
    ...SETTINGS_TABS.map((tab): [string, string] => [`settings-${tab}`, `/settings?tab=${tab}`]),
  ];

  for (const theme of THEMES) {
    // The same key the app stores its choice under (src/lib/theme.ts).
    await page.addInitScript((value) => localStorage.setItem("outbound.theme", value), theme);
    for (const [size, viewport] of Object.entries(SIZES)) {
      await page.setViewportSize(viewport);
      for (const [name, path] of screens) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        await page.screenshot({ path: `shots/${theme}-${size}/${name}.png`, fullPage: true });
      }
    }
  }
});

test("screenshot of the sign-in page", async ({ page, context }) => {
  await context.clearCookies();
  for (const theme of THEMES) {
    await page.addInitScript((value) => localStorage.setItem("outbound.theme", value), theme);
    for (const [size, viewport] of Object.entries(SIZES)) {
      await page.setViewportSize(viewport);
      await page.goto("/sign-in");
      await page.screenshot({ path: `shots/${theme}-${size}/sign-in.png`, fullPage: true });
    }
  }
});
