import { readFile } from "node:fs/promises";
import { setTimeout as sleep } from "node:timers/promises";
import { chromium, devices } from "playwright";

const [, , filename, option] = process.argv;
const key = process.env.SAFEORBIT_CHECK_KEY;
if (!filename || !key || (option && option !== "--watch")) {
  throw new Error("Usage: SAFEORBIT_CHECK_KEY=... node checkout-check.mjs checkout.json [--watch]");
}

const config = JSON.parse(await readFile(filename, "utf8"));
const shop = new URL(config.url);
const report = new URL(config.reportTo);
const interval = config.intervalMinutes ?? 15;
if (shop.protocol !== "https:" || shop.username || shop.password ||
    report.origin !== "https://safeorbit.com.pl" || !/^\/signals\/checkout\/\d+$/.test(report.pathname) ||
    report.username || report.password || report.search || report.hash ||
    !Number.isInteger(interval) || interval < 5 || interval > 1440 ||
    !Array.isArray(config.steps) || config.steps.length < 1 || config.steps.length > 8 ||
    !config.steps.every(step => step && ["name", "click", "expect"].every(field =>
      typeof step[field] === "string" && step[field].trim().length && step[field].length <= 250))) {
  throw new Error("Invalid checkout configuration.");
}

async function check() {
  const browser = await chromium.launch();
  const started = Date.now();
  let status = "ok";
  let step = "Відкрити товар";
  let screenshot;

  try {
    const context = await browser.newContext(devices["iPhone 13"]);
    await context.route("**/*", async route => {
      const request = route.request();
      if (request.isNavigationRequest() && new URL(request.url()).origin !== shop.origin) {
        await route.abort();
      } else {
        await route.continue();
      }
    });
    const page = await context.newPage();
    try {
      const response = await page.goto(shop.href, {waitUntil: "domcontentloaded", timeout: 15000});
      if (!response?.ok() || new URL(page.url()).origin !== shop.origin) throw new Error("Product page unavailable");
      for (const action of config.steps) {
        step = action.name.trim().slice(0, 160);
        await page.locator(action.click).click({timeout: 8000});
        if (new URL(page.url()).origin !== shop.origin) throw new Error("Navigation left the storefront");
        await page.locator(action.expect).first().waitFor({state: "visible", timeout: 8000});
      }
    } catch {
      status = "failed";
      if (new URL(page.url()).origin === shop.origin) {
        const image = await page.screenshot({timeout: 4000}).catch(() => null);
        if (image && image.length <= 450000) screenshot = image.toString("base64");
      }
    }
  } finally {
    await browser.close();
  }

  const result = await fetch(report, {
    method: "POST",
    redirect: "error",
    signal: AbortSignal.timeout(8000),
    headers: {"authorization": "Bearer " + key, "content-type": "application/json"},
    body: JSON.stringify({url: shop.origin, status, step, ms: Date.now() - started, screenshot}),
  });
  if (!result.ok) throw new Error("SafeOrbit rejected the result. HTTP " + result.status);
  console.log(new Date().toISOString(), status, step);
  return status === "ok";
}

if (option === "--watch") {
  while (true) {
    try {
      await check();
    } catch (error) {
      console.error("Could not finish checkout monitoring:", error.message);
    }
    await sleep(interval * 60 * 1000);
  }
} else {
  process.exitCode = await check() ? 0 : 1;
}
