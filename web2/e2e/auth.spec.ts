import { STAFF, emailedToken, expect, signIn, test, unique } from "./helpers";

const NEW_PASSWORD = "violet harbour quietly sixteen";
const WRITE = { "X-Requested-With": "outbound" };

test("an admin invites a member, who chooses a password and sees only that workspace", async ({ page, browser }) => {
  await signIn(page);
  await page.goto("/settings?tab=team");
  const email = `pat-${Date.now().toString(36)}@customer.example`;
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send invitation" }).click();
  await expect(page.getByText("Invitation sent.")).toBeVisible();
  await expect(page.getByRole("cell", { name: email })).toBeVisible();
  const token = await emailedToken(page, "invite", email);

  const invited = await (await browser.newContext()).newPage();
  await invited.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
  await invited.goto(`/invite/${token}`);
  await expect(invited.getByRole("heading", { name: "Join default" })).toBeVisible();
  await invited.getByLabel("Your name").fill("Pat Doe");
  await invited.getByLabel("Choose a password").fill(NEW_PASSWORD);
  await invited.getByText("I accept the Terms of Service").click();
  await invited.getByRole("button", { name: "Create my account" }).click();
  await expect(invited.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(invited).toHaveURL(/\/w\/default\/$/);

  await invited.getByRole("button", { name: "Switch workspace" }).click();
  await expect(invited.getByRole("menuitem")).toHaveCount(1);
  await invited.keyboard.press("Escape");
  // a member sees the team but cannot invite
  await invited.goto("/w/default/settings?tab=team");
  await expect(invited.getByText("Only admins invite people")).toBeVisible();
  // the link worked once
  await invited.goto(`/invite/${token}`);
  await expect(invited.getByRole("heading", { name: "This invitation cannot be used" })).toBeVisible();
});

test("a forgotten password is reset from an emailed link", async ({ page, browser }) => {
  await signIn(page);
  const email = `sam-${Date.now().toString(36)}@customer.example`;
  await page.request.post("/api/team/invitations", { data: { email }, headers: WRITE });
  const invite = await emailedToken(page, "invite", email);
  const accepted = await page.request.post(`/api/auth/invitations/${invite}/accept`, {
    data: { password: "first password, long enough", accept_terms: true },
    headers: WRITE,
  });
  expect(accepted.ok()).toBeTruthy();

  const person = await (await browser.newContext()).newPage();
  await person.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
  await person.goto("/sign-in");
  await person.getByRole("link", { name: "Forgot your password?" }).click();
  await person.getByLabel("Email").fill(email);
  await person.getByRole("button", { name: "Email me a link" }).click();
  await expect(person.getByText("Check your email")).toBeVisible();

  const token = await emailedToken(page, "reset", email);
  await person.goto(`/reset-password?token=${token}`);
  await person.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
  await person.getByLabel("New password again").fill(NEW_PASSWORD);
  await person.getByRole("button", { name: "Save and sign in" }).click();
  await expect(person.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("a superadmin reads a workspace behind a banner and cannot change anything", async ({ page }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  await page.getByRole("link", { name: /default/ }).click();
  await expect(page.getByText("Superadmin view of default, read-only")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Add target" })).toHaveCount(0);

  const me = await (await page.request.get("/api/auth/me")).json();
  const workspace = me.workspaces.find((w: { slug: string }) => w.slug === "default").id;
  const write = await page.request.post("/api/targets", { data: { website: unique("staff") }, headers: { ...WRITE, "X-Workspace-Id": workspace } });
  expect(write.status()).toBe(403);

  await page.getByRole("button", { name: "Exit" }).click();
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
});

test("signing out ends the session and an old link asks to sign in again", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Your account" }).click();
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.goto("/w/default/leads");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page).toHaveURL(/next=%2Fw%2Fdefault%2Fleads/);
});

test("a new customer's admin is taken to the guided setup, which starts empty", async ({ page, browser }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  const email = `boss-${Date.now().toString(36)}@globex.example`;
  const made = await page.request.post("/api/admin/customers", { data: { name: "Globex Ltd", website: "globex.example", admin_email: email }, headers: WRITE });
  expect(made.status()).toBe(201);
  const token = await emailedToken(page, "invite", email);

  const boss = await (await browser.newContext()).newPage();
  await boss.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
  await boss.goto(`/invite/${token}`);
  await expect(boss.getByRole("heading", { name: "Join Globex Ltd" })).toBeVisible();
  await boss.getByLabel("Choose a password").fill("violet harbour quietly sixteen");
  await boss.getByText("I accept the Terms of Service").click();
  await boss.getByRole("button", { name: "Create my account" }).click();

  await expect(boss).toHaveURL(/\/w\/globex-ltd\/onboarding$/);
  await expect(boss.getByRole("heading", { name: "Set up your workspace" })).toBeVisible();
  await expect(boss.getByRole("button", { name: /Your company/ })).toHaveAttribute("aria-current", "step");
  // nothing of anyone else's was copied in
  await expect(boss.getByText("Quantra")).toHaveCount(0);
  await boss.getByRole("button", { name: /A mailbox/ }).click();
  await expect(boss.getByText("No mailbox connected")).toBeVisible();
  await boss.getByRole("link", { name: "Dashboard" }).click();
  await expect(boss.getByText("Get started")).toBeVisible();
});

test("a free customer reaches its limit, sees it everywhere, and what waits is kept", async ({ page, browser }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  const email = `owner-${Date.now().toString(36)}@limits.example`;
  const made = await page.request.post("/api/admin/customers", { data: { name: "Limits Ltd", admin_email: email }, headers: WRITE });
  expect(made.status()).toBe(201);
  const token = await emailedToken(page, "invite", email);

  const owner = await (await browser.newContext()).newPage();
  await owner.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
  await owner.goto(`/invite/${token}`);
  await owner.getByLabel("Choose a password").fill("violet harbour quietly sixteen");
  await owner.getByText("I accept the Terms of Service").click();
  await owner.getByRole("button", { name: "Create my account" }).click();
  await expect(owner).toHaveURL(/\/w\/limits-ltd\/onboarding$/);

  for (let n = 0; n < 6; n++) {
    const added = await owner.request.post("/api/targets", { data: { website: `limit${n}-${Date.now().toString(36)}.com`, country: "UK" }, headers: WRITE });
    expect(added.ok()).toBeTruthy();
  }
  await owner.goto("/w/limits-ltd/settings?tab=plan");
  await expect(owner.getByRole("heading", { name: "Free plan" })).toBeVisible();
  const manual = owner.getByRole("row", { name: /Leads you add/ });
  await expect(manual).toContainText("5");
  await expect(manual.getByRole("meter")).toHaveAttribute("aria-label", "0 left");
  await expect(owner.getByText("No credits left for leads you add")).toBeVisible(); // the banner, everywhere
  await expect(owner.getByText("1 you added is waiting to become leads")).toBeVisible();

  await owner.goto("/w/limits-ltd/attention");
  await expect(owner.getByRole("heading", { name: /Waiting for credits/ })).toBeVisible();
  await owner.goto("/w/limits-ltd/targets");
  await expect(owner.getByText("1 company is waiting for credits")).toBeVisible();
  await owner.getByRole("button", { name: "Resume", exact: true }).click();
  await expect(owner.getByText("No credits yet.")).toBeVisible(); // refused without a credit, kept

  await owner.goto("/w/limits-ltd/settings?tab=plan");
  await owner.getByRole("button", { name: "Ask for more credits" }).click();
  await owner.getByLabel("What do you need more of?").selectOption("manual");
  await owner.getByRole("button", { name: "Send request" }).click();
  await expect(owner.getByText("Sent. The team will get back to you.")).toBeVisible();
});
