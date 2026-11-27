import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { setTimeout as sleep } from "node:timers/promises";
import { chromium, devices } from "playwright";

const site = "https://safeorbit.com.pl";
const browser = await chromium.launch({ executablePath: process.env.SAFEORBIT_CHROMIUM_PATH });
let page;
let stage = "Browser startup";

try {
  const context = await browser.newContext({
    ...devices["iPhone 13"],
    locale: "uk-UA",
    serviceWorkers: "block",
  });
  await context.route("**/*", route => {
    const request = route.request();
    if (new URL(request.url()).origin === site && ["GET", "HEAD"].includes(request.method())) {
      return route.continue();
    }
    return route.abort();
  });
  page = await context.newPage();
  page.setDefaultTimeout(12000);

  async function open(path, timeout = 25000) {
    const response = await page.goto(site + path, { waitUntil: "domcontentloaded", timeout });
    assert.ok(response?.ok(), `${path} returned HTTP ${response?.status()}`);
    assert.equal(new URL(page.url()).origin, site);
  }

  stage = "Mobile home page";
  for (let attempt = 1; ; attempt++) {
    try {
      await open("/", 40000);
      break;
    } catch (error) {
      if (attempt === 3) throw error;
      console.log("Waiting for the production site to respond before retrying.");
      await sleep(5000);
    }
  }
  const directoryLink = page.locator('a.directory-entry[href="/maistry"]');
  await directoryLink.waitFor({ state: "visible" });
  assert.equal(await directoryLink.getAttribute("href"), "/maistry");
  console.log("PASS Mobile home and directory link");

  stage = "Public marketplace search";
  await open("/maistry");
  const search = page.locator("#market-search");
  await search.locator('[name="q"]').fill("стрижка");
  await Promise.all([
    page.waitForURL(url => url.origin === site && url.searchParams.get("q") === "стрижка"),
    search.locator('button[type="submit"]').click(),
  ]);
  await page.locator("#results").waitFor({ state: "visible" });
  console.log("PASS Public marketplace search");

  stage = "Customer registration";
  await open("/maistry/register");
  await page.locator('input[name="phone"]').waitFor({ state: "visible" });
  console.log("PASS Customer registration form");

  stage = "Business registration";
  await open("/register?industry=other");
  assert.equal(await page.locator("#business-type").inputValue(), "other");
  assert.match(await page.locator('[data-industry="other"]').textContent(), /€19\.80/);
  assert.equal(await page.locator('[data-industry="other"] a').getAttribute("href"), "/terms/subscription/custom");
  console.log("PASS Business registration and Constructor offer link");

  for (const [plan, price] of [["commerce", "14.90"], ["production", "12.90"], ["custom", "19.80"]]) {
    stage = `Subscription offer: ${plan}`;
    await open(`/terms/subscription/${plan}`);
    const offer = page.getByText(`€${price}`, { exact: true });
    await offer.waitFor({ state: "visible" });
    assert.match(await page.locator(".form-description").textContent(), /редакція \d{4}-\d{2}-\d{2}/);
    console.log(`PASS Subscription offer: ${plan}`);
  }

  stage = "Pricing localization";
  await open("/taryfy");
  for (const plan of ["plan1", "plan2", "commerce", "production", "custom"]) {
    await page.locator(`#plan-${plan}`).waitFor({state: "visible"});
  }
  const picker = page.locator("[data-language-select]");
  for (const [lang, heading] of [
    ["en", "SafeOrbit plans"], ["ru", "Тарифы SafeOrbit"], ["pl", "Cennik SafeOrbit"],
    ["zh", "SafeOrbit 套餐"], ["uk", "Тарифи SafeOrbit"],
  ]) {
    await picker.selectOption(lang);
    await page.getByRole("heading", {name: heading, exact: true}).waitFor({state: "visible"});
  }
  console.log("PASS Pricing in all five languages");

  stage = "Cancellation guide and schedule audit";
  const guide = "/yak-zapovnyty-vilni-vikna-u-saloni";
  await open(guide);
  assert.equal(await page.locator('link[rel="canonical"]').getAttribute("href"), site + guide);
  await page.locator('article a[href="/login-demo"]').waitFor({state: "visible"});
  const auditLink = page.locator('article a[href="/rozbir-rozkladu"]');
  await Promise.all([
    page.waitForURL(`${site}/rozbir-rozkladu`),
    auditLink.click(),
  ]);
  await page.locator("#audit-example").click();
  await page.locator("#audit-data").waitFor({state: "visible"});
  assert.ok(Number(await page.locator("#audit-matches").textContent()) > 0);
  console.log("PASS Cancellation guide and waitlist example");
} catch (error) {
  console.error(`FAIL ${stage}`);
  if (page?.url().startsWith(site + "/")) {
    await mkdir("monitoring-output", { recursive: true });
    await page.screenshot({ path: "monitoring-output/failure.png", timeout: 4000 }).catch(() => {});
  }
  throw error;
} finally {
  await browser.close();
}
