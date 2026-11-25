import { readFile } from "node:fs/promises";
import { chromium, devices } from "playwright";

const path = process.argv[2];
if (!path || !process.env.SAFEORBIT_CHECK_KEY) {
  throw new Error("Usage: SAFEORBIT_CHECK_KEY=... node checkout-check.mjs checkout.json");
}
const config = JSON.parse(await readFile(path, "utf8"));
const shop = new URL(config.url);
const report = new URL(config.reportTo);
if (shop.protocol !== "https:" || report.origin !== "https://safeorbit.com.pl" ||
    !/^\/signals\/checkout\/\d+$/.test(report.pathname) || !Array.isArray(config.steps) ||
    config.steps.length < 1 || config.steps.length > 8) {
  throw new Error("Invalid checkout configuration.");
}
const browser = await chromium.launch();
const context = await browser.newContext(devices["iPhone 13"]);
const page = await context.newPage();
const start = Date.now();
let status = "ok";
let step = "Відкрити товар";
let screenshot;
try {
  const result = await page.goto(shop.href, { waitUntil: "domcontentloaded", timeout: 15000 });
  if (!result?.ok() || new URL(page.url()).origin !== shop.origin) throw new Error("Product page unavailable.");
  for (const action of config.steps) {
    step = String(action.name).slice(0, 160);
    if (!action.click || !action.expect) throw new Error("A step needs a click and a success selector.");
    await page.locator(action.click).click({ timeout: 8000 });
    if (new URL(page.url()).origin !== shop.origin) throw new Error("Navigation left the storefront.");
    await page.locator(action.expect).first().waitFor({ state: "visible", timeout: 8000 });
  }
} catch (error) {
  status = "failed";
  console.error(step, error.message);
  const image = await page.screenshot({ path: "checkout-failure.png", timeout: 4000 }).catch(() => null);
  if (image?.length <= 450000) screenshot = image.toString("base64");
}
await browser.close();
const result = await fetch(report, {
  method: "POST",
  signal: AbortSignal.timeout(8000),
  headers: {
    authorization: "Bearer " + process.env.SAFEORBIT_CHECK_KEY,
    "content-type": "application/json",
  },
  body: JSON.stringify({ url: shop.origin, status, step, ms: Date.now() - start, screenshot }),
});
if (!result.ok) throw new Error("SafeOrbit rejected the result. HTTP " + result.status);
process.exitCode = status === "ok" ? 0 : 1;
