import { expect, test } from "@playwright/test";

import { API, apiToken, login, watch } from "./helpers.mjs";

test.describe("OpsPilot dashboard - core journeys in a real browser", () => {
  test("login with a demo account button and reach the overview", async ({ page }) => {
    const problems = watch(page);
    await page.goto("/login");
    await expect(page.getByText("Your AI workforce, under control.")).toBeVisible();
    await page.getByRole("button", { name: /ops@acme-demo\.test|Olive Operator|operator/i }).first().click();
    await page.locator('button[type="submit"]').click();
    await page.waitForURL(/\/overview/);
    await expect(page.getByText(/active agents/i).first()).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("every page renders real data without errors", async ({ page }) => {
    const problems = watch(page);
    await login(page);
    for (const [path, marker] of [
      ["/overview", /workflows executed/i],
      ["/agents", /Lead Qualification Agent/],
      ["/workflows", /Workflow runs/i],
      ["/workflows/definitions", /lead_to_crm|New lead/],
      ["/approvals", /Approval center/i],
      ["/tasks", /Tasks/],
      ["/integrations", /Sandbox/],
      ["/analytics", /Analytics/],
      ["/audit", /Audit trail/],
      ["/incidents", /Incidents/],
      ["/documents", /Shipping & Returns FAQ/],
      ["/evaluations", /Evaluations/],
      ["/admin", /Administration/],
    ]) {
      await page.goto(path);
      await expect(page.getByText(marker).first(), `page ${path}`).toBeVisible();
    }
    expect(problems).toEqual([]);
  });

  test("agent playground runs an agent and shows the result", async ({ page }) => {
    const problems = watch(page);
    await login(page, "ops@acme-demo.test");
    await page.goto("/agents/lead_qualification");
    await page.getByRole("tab", { name: /Playground/ }).click();
    const editor = page.locator("textarea").first();
    await editor.fill(JSON.stringify({ lead: { name: "Browser Test", email: `browser-${Date.now()}@example.test`, company: "Example", title: "CEO", company_size: 120, budget: 20000, timeline: "this quarter", message: "We need help automating onboarding." } }, null, 2));
    await page.getByRole("button", { name: /Run agent/ }).click();
    await expect(page.getByText(/scored/i).first()).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("operator starts a workflow, approver approves it, run completes", async ({ page, request }) => {
    const problems = watch(page);
    // Kick off the lead workflow through the UI.
    await login(page, "ops@acme-demo.test");
    await page.goto("/workflows");
    await page.getByRole("button", { name: /Start workflow/ }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.locator("#wf-key").click();
    await page.getByRole("option", { name: /New lead/ }).click();
    await expect(dialog.locator("textarea").first()).toHaveValue(/lead/);
    await dialog.locator("textarea").first().fill(JSON.stringify({ lead: { name: "UI Flow", email: `ui-${Date.now()}@globex.test`, company: "Globex", title: "VP Operations", industry: "logistics", company_size: 900, budget: 80000, timeline: "this quarter", message: "We need to automate warehouse exception handling." } }));
    await dialog.getByRole("button", { name: /Start run/ }).click();
    await page.waitForURL(/\/workflows\/[0-9a-f-]{36}/);
    const runId = page.url().split("/").pop();
    await expect(page.getByText(/waiting approval/i).first()).toBeVisible();

    // Approver decides in the approval center.
    await page.context().clearCookies();
    await page.evaluate(() => localStorage.clear());
    await login(page, "approver@acme-demo.test");
    const token = await apiToken(request, "approver@acme-demo.test");
    const pending = await (await request.get(`${API}/approvals?run_id=${runId}&status=pending`, { headers: { Authorization: `Bearer ${token}` } })).json();
    expect(pending.items.length).toBeGreaterThan(0);
    await page.goto(`/approvals?id=${pending.items[0].id}`);
    if (!(await page.getByRole("button", { name: /^Approve$/ }).isVisible())) {
      await page.getByText(pending.items[0].action_type).first().click();
    }
    await page.getByRole("button", { name: /^Approve$/ }).click();
    await page.getByRole("dialog").last().getByRole("button", { name: /^Approve$/ }).click();
    await expect(page.getByText(/Approved and executed/)).toBeVisible();

    await page.goto(`/workflows/${runId}`);
    await expect(page.getByText(/^completed$/i).first()).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("command palette navigates", async ({ page }) => {
    await login(page);
    await page.keyboard.press("Control+k");
    await page.keyboard.type("Approvals");
    await page.keyboard.press("Enter");
    await page.waitForURL(/\/approvals/);
  });
});
