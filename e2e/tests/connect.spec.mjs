import { expect, test } from "@playwright/test";

import { login, watch } from "./helpers.mjs";

test.describe("Connecting a real system", () => {
  test("guided Connect form: provider fields, help link, validation, back to sample data", async ({ page }) => {
    const problems = watch(page);
    await login(page, "admin@acme-demo.test");
    problems.length = 0;
    await page.goto("/integrations");
    const crm = page.getByTestId("integration-crm");
    await crm.getByRole("button", { name: /Configure/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Connect CRM" })).toBeVisible();

    await dialog.getByRole("radio", { name: /HubSpot/ }).click();
    await expect(dialog.getByLabel(/Private app access token/)).toBeVisible();
    await expect(dialog.getByRole("link", { name: /Where do I find these/ })).toHaveAttribute("href", /hubspot\.com/);
    await expect(dialog.getByRole("button", { name: "Save and test connection" })).toBeDisabled();

    await dialog.getByRole("radio", { name: /Sample data/ }).click();
    await dialog.getByRole("button", { name: "Use sample data" }).click();
    await expect(dialog).toBeHidden({ timeout: 30_000 });
    await expect(page.getByText(/uses sample data/)).toBeVisible();

    // Email offers the zero-setup SMTP option with server presets in the help text.
    const email = page.getByTestId("integration-email");
    await email.getByRole("button", { name: /Configure/ }).click();
    await page.getByRole("dialog").getByRole("radio", { name: /SMTP/ }).click();
    await expect(page.getByRole("dialog").getByText(/smtp\.office365\.com/)).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
    expect(problems).toEqual([]);
  });
});
