import { expect, test } from "@playwright/test";

import { PASSWORD } from "./helpers.mjs";

// Every role, every page: no server errors, no page errors, no forbidden requests, no error panels.
// Pages a role may not use must explain themselves instead of failing.
const ROLES = ["admin", "ops", "approver", "finance", "auditor", "viewer"];
const PAGES = ["/copilot", "/overview", "/agents", "/agents/lead_qualification", "/workflows", "/workflows/definitions", "/approvals", "/tasks", "/analytics", "/audit", "/incidents", "/evaluations", "/system", "/integrations", "/documents", "/admin", "/help"];

for (const role of ROLES) {
  test(`${role}: every page loads cleanly or explains missing access`, async ({ page }) => {
    test.setTimeout(240_000);
    let where = "login";
    const problems = [];
    page.on("pageerror", (e) => problems.push(`[${where}] pageerror: ${e.message}`));
    page.on("console", (m) => {
      if (m.type() === "error" && !m.text().includes("defaultProps")) problems.push(`[${where}] console: ${m.text().split("\n")[0]}`);
    });
    page.on("response", (r) => {
      const url = r.url();
      if (url.includes("/api/v1/") && (r.status() >= 500 || r.status() === 403)) problems.push(`[${where}] http ${r.status()} ${r.request().method()} ${url}`);
    });

    await page.goto("/login");
    await page.locator("#email").fill(`${role}@acme-demo.test`);
    await page.locator('input[type="password"]').fill(PASSWORD);
    await page.locator('button[type="submit"]').click();
    await page.waitForURL(/\/overview|\/copilot/);

    for (const path of PAGES) {
      where = path;
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.locator("main")).not.toBeEmpty();
      const panels = await page.locator("main [role=alert]").allInnerTexts();
      for (const text of panels) if (text.trim()) problems.push(`[${path}] error panel: ${text.replace(/\s+/g, " ").slice(0, 120)}`);
      for (const tab of await page.getByRole("tab").all()) {
        where = `${path} › ${(await tab.innerText()).trim()}`;
        await tab.click();
        await page.waitForLoadState("networkidle");
        for (const text of await page.locator("main [role=alert]").allInnerTexts()) if (text.trim()) problems.push(`[${where}] error panel: ${text.replace(/\s+/g, " ").slice(0, 120)}`);
      }
    }
    expect(problems).toEqual([]);
  });
}
