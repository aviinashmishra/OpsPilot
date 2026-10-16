import { expect } from "@playwright/test";

export const PASSWORD = "OpsPilot-Demo-2026!";
export const API = process.env.API_URL ?? "http://127.0.0.1:8000/api/v1";

/** Collects console errors and failed API calls so each test can assert a clean session. */
export function watch(page) {
  const problems = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (t.includes("defaultProps")) return; // recharts deprecation noise in dev mode
    problems.push(`console: ${t.split("\n")[0]}`);
  });
  page.on("response", (r) => {
    const url = r.url();
    // 401 on /auth/me before login and 404/409 are legitimate UI states; anything 5xx is a bug.
    if (url.includes("/api/v1/") && r.status() >= 500) problems.push(`http ${r.status()} ${r.request().method()} ${url}`);
  });
  return problems;
}

export async function login(page, email = "admin@acme-demo.test") {
  await page.goto("/login");
  const tenant = page.locator("#tenant");
  if (await tenant.count()) await tenant.fill("acme-demo");
  await page.locator("#email").fill(email);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/overview/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

export async function apiToken(request, email) {
  const r = await request.post(`${API}/auth/login`, { data: { tenant: "acme-demo", email, password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  return (await r.json()).access_token;
}
