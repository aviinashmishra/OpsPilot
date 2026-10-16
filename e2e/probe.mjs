// Diagnostic probe: drive the dashboard in real Chromium and report console errors,
// failed network requests and what is on screen after each step.
import { chromium } from "@playwright/test";

const WEB = process.env.WEB_URL ?? "http://localhost:3000";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const logs = [];
page.on("console", (m) => { if (["error", "warning"].includes(m.type())) logs.push(`[console.${m.type()}] ${m.text()}`); });
page.on("pageerror", (e) => logs.push(`[pageerror] ${e.message}`));
page.on("requestfailed", (r) => logs.push(`[requestfailed] ${r.method()} ${r.url()} ${r.failure()?.errorText}`));
page.on("response", (r) => { if (r.status() >= 400) logs.push(`[http ${r.status()}] ${r.request().method()} ${r.url()}`); });

async function step(name, fn) {
  const before = logs.length;
  try {
    await fn();
    const text = (await page.locator("body").innerText()).replace(/\s+/g, " ").slice(0, 300);
    console.log(`OK   ${name} | url=${page.url()} | ${text}`);
  } catch (e) {
    console.log(`FAIL ${name}: ${String(e.message).split("\n")[0]}`);
    await page.screenshot({ path: `probe-${name.replace(/\W+/g, "_")}.png`, fullPage: true });
  }
  for (const l of logs.slice(before)) { const first = l.split("\n")[0]; if (!first.includes("defaultProps")) console.log("     " + first.slice(0, 400)); }
}

await step("open root", async () => { await page.goto(WEB, { waitUntil: "networkidle" }); });
await step("login page", async () => { await page.goto(`${WEB}/login`, { waitUntil: "networkidle" }); });
await step("login submit", async () => {
  const email = page.locator('input[type="email"], input[name="email"], #email').first();
  const pw = page.locator('input[type="password"]').first();
  const tenant = page.locator('input[name="tenant"], #tenant').first();
  if (await tenant.count()) await tenant.fill("acme-demo");
  await email.fill("admin@acme-demo.test");
  await pw.fill("OpsPilot-Demo-2026!");
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL(/overview/, { timeout: 15000 });
  await page.waitForLoadState("networkidle");
});
for (const p of ["/overview", "/agents", "/agents/lead_qualification", "/workflows", "/approvals", "/tasks", "/integrations", "/analytics", "/audit", "/incidents", "/documents", "/evaluations", "/admin", "/workflows/definitions"]) {
  await step(`page ${p}`, async () => {
    await page.goto(`${WEB}${p}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(800);
  });
}
await browser.close();
process.on("unhandledRejection", (e) => { console.log("UNHANDLED", e); });
