import { emailedToken, expect, test, signIn, addTarget, unique, STAFF } from "./helpers";

const WRITE = { "X-Requested-With": "outbound" };

test("a customer out of AI credits waits, the admin grants credits in the console, and the lead is added", async ({ browser }) => {
  const staff = await (await browser.newContext()).newPage();
  const customer = await (await browser.newContext()).newPage();
  await staff.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
  await customer.addInitScript(() => localStorage.setItem("outbound.tour", "done"));
  await signIn(staff, STAFF, false);
  await expect(staff.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  const rows = await (await staff.request.get("/api/admin/customers")).json();
  const row = rows.find((r: { name: string }) => r.name === "default");
  const base = `/api/admin/customers/${row.id}`;
  const clear = async () => {
    const found = await (await staff.request.get(base)).json();
    for (const o of found.overrides ?? []) await staff.request.delete(`${base}/overrides/${o.id}`, { headers: WRITE });
    for (const g of found.grants ?? []) await staff.request.delete(`${base}/grants/${g.id}`, { headers: WRITE });
  };
  try {
    await clear(); // earlier tests may have granted credits to this shared customer
    // Put the customer on the Free plan with no AI credits left this month.
    await staff.request.patch(`${base}/plan`, { data: { plan: "free" }, headers: WRITE });
    await staff.request.put(`${base}/overrides`, { data: { key: "monthly_credits", value: 0 }, headers: WRITE });

    await signIn(customer);
    await addTarget(customer, { website: unique("waits"), country: "UK" });
    await customer.goto("/");
    await customer.getByRole("link", { name: "Add leads" }).first().click();
    await expect(customer.getByText(/waiting for AI credits/).first()).toBeVisible();

    // The admin grants AI credits from the console, setting waiting work going.
    await staff.goto(`/admin/customers/${row.id}`);
    await staff.getByRole("button", { name: "Grant AI credits" }).click();
    await staff.getByRole("dialog").getByRole("spinbutton", { name: "AI credits" }).fill("100");
    await staff.getByRole("button", { name: /^Grant 100 credits/ }).click();
    await expect(staff.getByText(/1 waiting added as leads/)).toBeVisible();

    await customer.reload();
    await expect(customer.getByText(/waiting for AI credits/)).toHaveCount(0);
  } finally {
    // Leave the shared customer as it was: unlimited, with no override or grant left behind.
    await clear();
    await staff.request.patch(`${base}/plan`, { data: { plan: "unlimited" }, headers: WRITE });
  }
});

test("a superadmin opens a customer's workspace and can look but not change anything", async ({ page }) => {
  await signIn(page, STAFF, false);
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  const rows = await (await page.request.get("/api/admin/customers")).json();
  const id = rows.find((r: { name: string }) => r.name === "default").id;
  await page.getByRole("link", { name: /default/ }).click();
  await expect(page.getByText(/Superadmin view of .*read-only/)).toBeVisible();
  const refused = await page.request.post("/api/targets", { data: { website: unique("nope"), country: "UK" }, headers: { ...WRITE, "X-Workspace-Id": id } });
  expect(refused.status()).toBe(403);
});

test("anyone can ask to be removed from the lead directory and confirm from the emailed link", async ({ page }) => {
  const address = `${unique("person")}`.replace(".com", "") + "@removal.example";
  await page.goto("/remove-my-data");
  await page.getByLabel("Your work email").fill(address);
  await page.getByRole("button", { name: "Email me a link" }).click();
  await expect(page.getByText("Check your email")).toBeVisible();
  const token = await emailedToken(page, "remove", address);
  await page.goto(`/remove-my-data?token=${token}`);
  await page.getByRole("button", { name: "Remove my details" }).click();
  await expect(page.getByText(/removed from the directory/)).toBeVisible();
});
