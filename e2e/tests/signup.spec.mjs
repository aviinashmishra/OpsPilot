import { expect, test } from "@playwright/test";

import { watch } from "./helpers.mjs";

test.describe("New company: self-serve sign-up and onboarding", () => {
  test("signs up, sees the checklist, runs an agent on sample data, step completes", async ({ page }) => {
    test.setTimeout(180_000);
    const problems = watch(page);
    const stamp = Date.now();
    await page.goto("/login");
    await page.getByRole("link", { name: "Create a workspace" }).click();
    await page.waitForURL(/\/signup/);

    await page.locator("#company").fill(`E2E Traders ${stamp}`);
    await page.locator("#full_name").fill("Erin Endtoend");
    await page.locator("#email").fill(`erin-${stamp}@e2e-traders.test`);
    await page.locator("#password").fill("short");
    await expect(page.getByText(/At least 10 characters/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Create workspace" })).toBeDisabled();
    await page.locator("#password").fill("Strong-Pass-2026");
    await page.getByRole("button", { name: "Create workspace" }).click();

    await page.waitForURL(/\/overview/, { timeout: 60_000 });
    const card = page.getByTestId("getting-started");
    await expect(card).toContainText(/Getting started · 0 of 6/);
    await expect(card).toContainText("sample data");

    // Every agent works out of the box: run one with its pre-filled example.
    await card.getByRole("link", { name: /Run an agent on sample data/ }).click();
    await page.waitForURL(/\/agents/);
    await page.goto("/agents/customer_support?tab=playground");
    await page.getByRole("button", { name: /Run agent/ }).click();
    await expect(page.getByText(/Agent run [0-9a-f]{8}/)).toBeVisible({ timeout: 90_000 });

    await page.goto("/overview");
    await expect(page.getByTestId("getting-started")).toContainText(/Getting started · 1 of 6/, { timeout: 30_000 });
    expect(problems).toEqual([]);
  });

  test("signs in with just email and password", async ({ page, request }) => {
    const stamp = Date.now();
    const email = `solo-${stamp}@e2e-solo.test`;
    const r = await request.post(`${process.env.API_URL ?? "http://127.0.0.1:8000/api/v1"}/auth/signup`, { data: { company: `Solo ${stamp}`, full_name: "Sam Solo", email, password: "Strong-Pass-2026" } });
    expect(r.status()).toBe(201);
    await page.goto("/login");
    await page.locator("#email").fill(email);
    await page.locator('input[type="password"]').fill("Strong-Pass-2026");
    await page.locator('button[type="submit"]').click();
    await page.waitForURL(/\/overview/);
  });
});
