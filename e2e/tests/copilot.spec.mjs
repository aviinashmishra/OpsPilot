import { expect, test } from "@playwright/test";

import { login, watch } from "./helpers.mjs";

const SUGGESTION = "Check inventory and tell me what to reorder";
const SLOW = 60_000; // mutations that hit the job queue / a busy API

/** Every 5xx response and console error counts; nothing is excluded. */
function relevant(problems) {
  return problems;
}

async function loginClean(page, problems, email) {
  await login(page, email);
  problems.length = 0;
}

test.describe("Ops Copilot, custom tools, bulk runs and scale view", () => {
  test("copilot answers a suggestion with a live trace, approval link and a follow-up", async ({ page }) => {
    test.setTimeout(180_000);
    const problems = watch(page);
    await loginClean(page, problems, "ops@acme-demo.test");

    // Sidebar entry sits at the top of OPERATE.
    await page.getByRole("link", { name: "Copilot" }).first().click();
    await page.waitForURL(/\/copilot/);
    await expect(page.getByRole("heading", { name: /Ask your operations anything/i })).toBeVisible();
    await expect(page.getByTestId("copilot-mode").first()).toBeVisible({ timeout: SLOW });
    await expect(page.getByTestId("copilot-tool-counts")).toContainText(/agents · \d+ tools · \d+ custom tool/);

    await page.getByRole("button", { name: SUGGESTION, exact: true }).click();
    await expect(page.getByTestId("copilot-user-message").first()).toContainText(SUGGESTION);
    await page.waitForURL(/\/copilot\?s=[0-9a-f-]{36}/, { timeout: SLOW });

    const first = page.getByTestId("copilot-assistant-message").first();
    await expect(first).toHaveAttribute("data-status", "done", { timeout: SLOW });
    const approvalStep = first.locator('[data-testid="copilot-step"][data-status="needs_approval"]').first();
    await expect(approvalStep).toBeVisible();
    await expect(approvalStep.getByText("Needs approval")).toBeVisible();
    await expect(first.getByText(/Step 1 · /)).toBeVisible();
    await expect(first.getByTestId("copilot-message-footer")).toContainText(/tool call/);

    // Expand the step and see its input / output.
    await approvalStep.getByRole("button", { name: /Input & output/ }).click();
    await expect(approvalStep.getByText("Output", { exact: true })).toBeVisible();

    // The approval link opens the approval center on that approval.
    const sessionUrl = page.url();
    const review = approvalStep.getByRole("link", { name: /Review approval/ }).first();
    expect(await review.getAttribute("href")).toMatch(/^\/approvals\?id=[0-9a-f-]{36}$/);
    await review.click();
    await page.waitForURL(/\/approvals\?id=/);
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: SLOW });

    // Follow-up in the same conversation.
    await page.goto(sessionUrl);
    await expect(page.getByTestId("copilot-assistant-message").first()).toHaveAttribute("data-status", "done", { timeout: SLOW });
    const composer = page.getByLabel("Message the Copilot");
    await composer.fill("Which tasks are overdue, and who owns them?");
    await composer.press("Enter");
    await expect(page.getByTestId("copilot-user-message")).toHaveCount(2);
    const second = page.getByTestId("copilot-assistant-message").nth(1);
    await expect(second).toHaveAttribute("data-status", "done", { timeout: SLOW });
    await expect(second.getByTestId("copilot-step").first()).toBeVisible();

    // Delete the chat (with confirmation) -> back to the empty state.
    await page.locator('[aria-current="true"]').locator("xpath=..").getByRole("button", { name: /^Delete chat:/ }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete chat" }).click();
    await expect(page.getByText("Chat deleted")).toBeVisible({ timeout: SLOW });
    await expect(page.getByRole("heading", { name: /Ask your operations anything/i })).toBeVisible();
    expect(relevant(problems)).toEqual([]);
  });

  test("command palette asks the copilot with the query prefilled", async ({ page }) => {
    await login(page, "ops@acme-demo.test");
    await page.keyboard.press("Control+k");
    await page.keyboard.type("Where is order ORD-5002?");
    await expect(page.getByRole("button", { name: /Ask Copilot: .Where is order ORD-5002\?./ })).toBeVisible();
    await page.keyboard.press("Control+Enter");
    await page.waitForURL(/\/copilot/);
    await expect(page.getByLabel("Message the Copilot")).toHaveValue("Where is order ORD-5002?");
  });

  test("viewer without agents:run sees an explanation instead of the copilot", async ({ page }) => {
    await login(page, "viewer@acme-demo.test");
    await page.goto("/copilot");
    await expect(page.getByText(/You don't have access to Copilot/i)).toBeVisible();
    await expect(page.getByRole("link", { name: /Go to Overview/ })).toBeVisible();
  });

  test("admin creates, tests and deletes a custom tool", async ({ page }) => {
    test.setTimeout(180_000);
    const problems = watch(page);
    const name = `e2e_tool_${Date.now()}`;
    await loginClean(page, problems, "admin@acme-demo.test");
    await page.goto("/integrations");
    await page.getByRole("tab", { name: "Custom tools" }).click();
    await expect(page.getByText(/Private-network destinations are blocked/)).toBeVisible();
    await expect(page.getByTestId("mcp-url")).toContainText(/:8000\/mcp$/);

    await page.getByRole("button", { name: "New tool" }).first().click();
    const dialog = page.getByRole("dialog");
    // Client-side validation surfaces before anything is sent.
    await dialog.getByRole("button", { name: "Create tool" }).click();
    await expect(dialog.getByText(/lowercase letters, digits and underscores/)).toBeVisible();
    await dialog.locator("#ct-name").fill(name);
    await dialog.locator("#ct-desc").fill("Looks up an order in the legacy order system (e2e).");
    await dialog.locator("#ct-url").fill("https://opspilot-e2e.invalid/v1/orders/{order_id}");
    await dialog.locator("#ct-secret").fill("e2e-secret-value");
    await dialog.locator("#ct-auth-header").fill("X-Api-Key");
    await dialog.getByRole("button", { name: "Create tool" }).click();
    await expect(dialog).toBeHidden({ timeout: SLOW });

    const row = page.getByTestId("custom-tool-row").filter({ hasText: name });
    await expect(row).toBeVisible();
    await expect(row).toContainText("secret set");

    // Test call: the host does not resolve, so the UI must show the error gracefully.
    await row.getByRole("button", { name: "Test" }).click();
    const testDialog = page.getByRole("dialog");
    await testDialog.locator("textarea").fill(JSON.stringify({ order_id: "ORD-5002" }));
    await testDialog.getByRole("button", { name: "Send test request" }).click();
    const result = testDialog.getByTestId("custom-tool-test-result");
    await expect(result).toHaveAttribute("data-ok", "false", { timeout: SLOW });
    await expect(result.getByRole("alert")).toContainText(/resolve|blocked|connect|non-public|https|timed out|HTTP/i);
    await testDialog.getByRole("button", { name: "Close", exact: true }).click();

    // Tool catalog lists it as custom.
    await page.getByRole("tab", { name: "Tool catalog" }).click();
    await page.getByLabel("Search tools").fill(name);
    await expect(page.getByText(`custom.${name}`)).toBeVisible({ timeout: SLOW });

    await page.getByRole("tab", { name: "Custom tools" }).click();
    await row.getByRole("button", { name: `Delete ${name}` }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete tool" }).click();
    await expect(row).toHaveCount(0, { timeout: SLOW });
    expect(relevant(problems)).toEqual([]);
  });

  test("bulk run of 3 leads completes with live progress", async ({ page }) => {
    test.setTimeout(180_000);
    const problems = watch(page);
    await loginClean(page, problems, "ops@acme-demo.test");
    await page.goto("/agents/lead_qualification?tab=bulk");
    const panel = page.getByRole("tabpanel");
    const stamp = Date.now();
    const items = [1, 2, 3].map((n) => ({ lead: { name: `Bulk Lead ${n}`, email: `bulk-${stamp}-${n}@example.test`, company: `Bulk Co ${n}`, title: "COO", company_size: 100 * n, budget: 15000 * n, timeline: "this quarter", message: "Evaluating automation for our support team." } }));
    await panel.locator("textarea").first().fill(JSON.stringify(items, null, 2));
    await expect(panel.getByTestId("bulk-item-count")).toContainText("3 items ready");
    await panel.getByRole("button", { name: /Start bulk run/ }).click();
    const progress = page.getByTestId("batch-progress");
    await expect(progress).toBeVisible({ timeout: SLOW });
    await expect(progress).toHaveAttribute("data-status", "completed", { timeout: 120_000 });
    await expect(progress).toContainText("3 of 3 processed");
    await expect(page.getByRole("heading", { name: "Recent bulk runs" })).toBeVisible();
    expect(relevant(problems)).toEqual([]);
  });

  test("scale & workers page shows a live worker", async ({ page }) => {
    const problems = watch(page);
    await loginClean(page, problems, "admin@acme-demo.test");
    await page.getByRole("link", { name: "Scale & workers" }).first().click();
    await page.waitForURL(/\/system/);
    await expect(page.getByRole("heading", { name: "Scale & workers", level: 1 })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Alive", exact: true }).first()).toBeVisible({ timeout: SLOW });
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByText("Auto-refresh paused")).toBeVisible();
    expect(relevant(problems)).toEqual([]);
  });
});
