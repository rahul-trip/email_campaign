import { emailedToken, expect, signIn, STAFF, test } from "./helpers";

const WRITE = { "X-Requested-With": "outbound" };

test("a new customer reads their website, confirms, and has a search started without opening Settings", async ({ page, browser }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  const email = `boss-${Date.now().toString(36)}@initech.example`;
  const made = await page.request.post("/api/admin/customers", { data: { name: "Initech Ltd", website: "initech-sensors.com", admin_email: email }, headers: WRITE });
  expect(made.status()).toBe(201);
  const token = await emailedToken(page, "invite", email);

  const boss = await (await browser.newContext()).newPage();
  await boss.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
  await boss.goto(`/invite/${token}`);
  await boss.getByLabel("Choose a password").fill("violet harbour quietly sixteen");
  await boss.getByText("I accept the Terms of Service").click();
  await boss.getByRole("button", { name: "Create my account" }).click();
  await expect(boss).toHaveURL(/\/onboarding$/);

  // 1. What you sell: the website is read, the draft fills blanks, and the company's name stays as it was.
  await expect(boss.getByText("Step 1 of 5")).toBeVisible();
  await expect(boss.getByLabel("Your website")).toHaveValue("initech-sensors.com");
  await boss.getByRole("button", { name: "Read my website" }).click();
  await expect(boss.getByText(/Drafted from \d+ pages? of your website/)).toBeVisible();
  await expect(boss.getByLabel("Industry")).toHaveValue("industrial sensors");
  await expect(boss.getByLabel("Company name")).toHaveValue("Initech Ltd");
  await boss.getByRole("button", { name: "Confirm and continue" }).click();

  // 2. Who signs: the legal address came from the site; the person still gives their name and title.
  await expect(boss.getByText("Step 2 of 5")).toBeVisible();
  await expect(boss.getByLabel("Postal address")).toHaveValue("2 Dock Road, Hull");
  await boss.getByLabel("Your name").fill("Peter Gibbons");
  await boss.getByLabel("Your title").fill("Head of Sales");
  await boss.getByRole("button", { name: "Confirm and continue" }).click();

  // 3. Who to reach: suggested from the profile, saved by the person, and the brief appears.
  await expect(boss.getByText("Step 3 of 5")).toBeVisible();
  await expect(boss.getByLabel("Wanted job titles")).toHaveValue(/Head of Maintenance/);
  await boss.getByRole("button", { name: "Save campaign" }).click();
  await expect(boss.getByText("This is who we will look for")).toBeVisible();
  await boss.getByRole("button", { name: "Looks right, find my first leads" }).click();

  // 4. First leads: one press starts the search, and the page shows it.
  await expect(boss.getByText("Step 4 of 5")).toBeVisible();
  await boss.getByRole("button", { name: "Find 10 companies now" }).click();
  await expect(boss.getByRole("link", { name: "Watch this run" })).toBeVisible();

  for (const step of [/What you sell/, /Who signs/, /Who to reach/]) {
    await expect(boss.getByRole("button", { name: step }).getByLabel("Done")).toBeVisible();
  }
});
