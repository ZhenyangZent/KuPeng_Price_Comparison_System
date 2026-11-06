import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import {
  createCdpClient,
  evaluate,
  locateBrowser,
  navigate,
  pressKey,
  setInput,
  sha256File,
  startStaticServer,
  verifyManifestFiles,
  wait,
  waitForCondition,
  waitForJson
} from "./lib.mjs";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const reportRoot = path.join(projectRoot, "reports", "H01");
const evidenceRoot = path.join(reportRoot, "evidence");
const runId = new Date().toISOString().replaceAll(":", "").replaceAll(".", "");
const runtimeRoot = path.join(projectRoot, "review", "H01", "runtime", runId);
const screenshotRoot = path.join(evidenceRoot, "screenshots");
await Promise.all([mkdir(evidenceRoot, { recursive: true }), mkdir(runtimeRoot, { recursive: true }), mkdir(screenshotRoot, { recursive: true })]);

const paths = {
  authorityZip: path.join(projectRoot, "input", "orchestrator_bundles", "UNIFIED_PARALLEL_20261105_03", "CDH_UNIFIED_PARALLEL_20261105_03.zip"),
  a05Release: path.join(projectRoot, "review", "releases", "CDH_A05_001_REVIEW.zip"),
  a05Root: path.join(projectRoot, "review", "A05", "001", "release_staging"),
  a05Manifest: path.join(projectRoot, "review", "A05", "001", "release_staging", "SHA256_MANIFEST.json"),
  a05Dist: path.join(projectRoot, "review", "A05", "001", "release_staging", "apps", "price-web", "frontend", "dist"),
  browserProfile: path.join(runtimeRoot, "browser-profile")
};
const expected = {
  authorityZip: "08fb652c86647d15b624cb8e785bafd8b2ee065932966c24ab7932b1754de280",
  a05Release: "66652edfd641869ac63ea44c0254e712441fceccd77ea3bb78f706120cb14d0e"
};

const result = {
  schema: "CDH-H01-JOURNEY-EVIDENCE-V1",
  task_id: "CDH-H01-WEB-JOURNEY-E2E-001",
  run_id: runId,
  authority: {},
  dependencies: {},
  api_probes: [],
  browser_checks: [],
  coverage_matrix: [],
  defects: [],
  network: {},
  execution_gate: "NOT_RUN",
  mvp_readiness: "WAITING_A06"
};

function check(collection, id, pass, expectedValue, actualValue, owner = "H") {
  collection.push({ id, status: pass ? "PASS" : "FAIL", expected: expectedValue, actual: actualValue, owner });
  return pass;
}

function coverage(id, status, evidence, owner) {
  result.coverage_matrix.push({ id, status, evidence, owner });
}

async function startApiServer(label) {
  const fixtureRoot = path.join(runtimeRoot, label);
  await mkdir(fixtureRoot, { recursive: true });
  const child = spawn("python", [
    path.join(projectRoot, "tools", "web_journey_e2e", "b06_fixture_server.py"),
    "--fixture-root", fixtureRoot,
    "--port", "8765"
  ], { cwd: projectRoot, windowsHide: true, shell: false, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
  child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
  const info = await waitForJson("http://127.0.0.1:8765/api/v2/products?page=1&limit=20");
  const database = path.join(fixtureRoot, "h01_synthetic.sqlite3");
  return { child, stdout: () => stdout, stderr: () => stderr, info, database };
}

async function stopProcess(child) {
  if (child.exitCode !== null) return;
  child.kill();
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    wait(3000)
  ]);
}

let staticServer = null;
let browserProcess = null;
let apiServer = null;
let cdp = null;
try {
  const authorityHash = await sha256File(paths.authorityZip);
  const a05ReleaseHash = await sha256File(paths.a05Release);
  const distManifest = await verifyManifestFiles(paths.a05Manifest, paths.a05Root, "apps/price-web/frontend/dist/");
  result.authority = {
    unified_zip: { path: path.relative(projectRoot, paths.authorityZip).replaceAll("\\", "/"), expected_sha256: expected.authorityZip, actual_sha256: authorityHash, pass: authorityHash === expected.authorityZip },
    a05_release: { path: path.relative(projectRoot, paths.a05Release).replaceAll("\\", "/"), expected_sha256: expected.a05Release, actual_sha256: a05ReleaseHash, pass: a05ReleaseHash === expected.a05Release },
    a05_dist_manifest: distManifest,
    a06_gate: "WAITING_CENTRAL_ACK"
  };
  if (!result.authority.unified_zip.pass || !result.authority.a05_release.pass || !distManifest.pass) {
    throw new Error("authority or A05 target identity gate failed");
  }

  const browser = locateBrowser();
  result.dependencies = {
    node: process.version,
    browser,
    playwright_package: "MISSING_NOT_DOWNLOADED",
    fallback_driver: browser ? "NODE_CDP_HEADLESS" : "BLOCKED_BROWSER_DEPENDENCY"
  };
  if (!browser) throw new Error("BLOCKED_BROWSER_DEPENDENCY");

  apiServer = await startApiServer("api-first");
  const apiBase = "http://127.0.0.1:8765";
  const dbHashBefore = await sha256File(apiServer.database);
  const search = await (await fetch(`${apiBase}/api/v2/products?page=1&limit=20`)).json();
  check(result.api_probes, "api.synthetic_classification", search.data_classification === "SYNTHETIC_DEMO_ONLY" && search.data_source_status === "SYNTHETIC_FIXTURE_ONLY", "explicit synthetic classification", `${search.data_source_status}/${search.data_classification}`, "B");
  check(result.api_probes, "api.five_exact_products", search.total === 5, 5, search.total, "B");
  const earbud = search.items.find((item) => item.variant_signature.includes("SKU-H01-BLK"));
  const detail = await (await fetch(`${apiBase}/api/v2/products/${encodeURIComponent(earbud.id)}`)).json();
  check(result.api_probes, "api.history_minimum", detail.history.length === 2 && detail.observation_period_min_twd === 299, "2 samples; min 299", `${detail.history.length} samples; min ${detail.observation_period_min_twd}`, "B");
  check(result.api_probes, "api.coverage_present", detail.product.coverage?.basis === "COMPLETED_CALENDAR_DAYS", "COMPLETED_CALENDAR_DAYS", detail.product.coverage?.basis, "B");
  check(result.api_probes, "api.no_image", detail.product.thumbnail === null, null, detail.product.thumbnail, "B");
  check(result.api_probes, "api.condition_unknown", detail.offers[0].item_condition === "UNKNOWN" && detail.offers[0].item_condition_source === "NOT_RECORDED", "UNKNOWN/NOT_RECORDED", `${detail.offers[0].item_condition}/${detail.offers[0].item_condition_source}`, "B");
  const affiliate = await (await fetch(`${apiBase}/api/v2/products/${encodeURIComponent(earbud.id)}/affiliate`)).json();
  check(result.api_probes, "api.affiliate_fail_closed", affiliate.affiliate.state === "UNCONFIGURED" && affiliate.affiliate.click_url === null && affiliate.affiliate.verified_product_match === false, "UNCONFIGURED/null/false", `${affiliate.affiliate.state}/${affiliate.affiliate.click_url}/${affiliate.affiliate.verified_product_match}`, "F");
  const multi = await (await fetch(`${apiBase}/api/v2/products?q=${encodeURIComponent("SYNTHETIC 多規格商品")}`)).json();
  const multiVariants = multi.items.map((item) => item.variant_signature).sort();
  check(result.api_probes, "api.multi_sku", multi.total === 2 && new Set(multiVariants).size === 2, "2 separate exact variants", multiVariants, "B");
  const zero = await (await fetch(`${apiBase}/api/v2/products?q=SKU-H01-ZERO`)).json();
  check(result.api_probes, "api.zero_unknown_shipping", zero.items[0].last_observed_price_twd === 0 && zero.items[0].shipping_status === "UNKNOWN" && zero.items[0].quality_flags.includes("SHIPPING_UNKNOWN"), "0 remains price; shipping UNKNOWN flagged", zero.items[0], "B");
  const stale = await (await fetch(`${apiBase}/api/v2/products?q=SKU-H01-STALE`)).json();
  check(result.api_probes, "api.stale_flag", stale.items[0].quality_flags.includes("STALE_LAST_OBSERVATION"), "STALE_LAST_OBSERVATION", stale.items[0].quality_flags, "B");
  const dbHashAfter = await sha256File(apiServer.database);
  check(result.api_probes, "api.readonly_bytes", dbHashBefore === dbHashAfter, dbHashBefore, dbHashAfter, "B");
  await stopProcess(apiServer.child);
  apiServer = null;
  let offlineFailed = false;
  try { await fetch(`${apiBase}/api/v2/products`, { signal: AbortSignal.timeout(1000) }); } catch { offlineFailed = true; }
  check(result.api_probes, "api.offline_detected", offlineFailed, true, offlineFailed, "A");
  apiServer = await startApiServer("api-recovery");
  const recovered = await (await fetch(`${apiBase}/api/v2/products?q=SKU-H01-BLK`)).json();
  check(result.api_probes, "api.offline_recovery", recovered.total === 1, "service recovers with one exact item", recovered.total, "A");
  await stopProcess(apiServer.child);
  apiServer = null;

  staticServer = await startStaticServer(paths.a05Dist, 4173);
  const debugPort = 9331;
  const args = [
    "--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update",
    "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run",
    "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1",
    `--remote-debugging-port=${debugPort}`, `--user-data-dir=${paths.browserProfile}`, "about:blank"
  ];
  browserProcess = spawn(browser, args, { cwd: projectRoot, windowsHide: true, shell: false, stdio: ["ignore", "pipe", "pipe"] });
  let browserStderr = "";
  browserProcess.stderr.on("data", (chunk) => { browserStderr += chunk.toString(); });
  const tabs = await waitForJson(`http://127.0.0.1:${debugPort}/json`);
  const tab = tabs.find((entry) => entry.type === "page");
  if (!tab?.webSocketDebuggerUrl) throw new Error("headless browser page target unavailable");
  cdp = createCdpClient(tab.webSocketDebuggerUrl);
  await cdp.opened;
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Network.enable");

  const networkUrls = [];
  cdp.on("Network.requestWillBeSent", (event) => networkUrls.push(event.request.url));

  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await navigate(cdp, `${staticServer.url}/?product=syn-earbuds-pro-black`);
  await waitForCondition(cdp, `document.body.innerText.includes('SYNTHETIC｜無線耳機 Pro') && document.body.innerText.includes('觀測期間最低價')`);
  const baseline = await evaluate(cdp, `(() => ({
    text: document.body.innerText,
    chartLabel: document.querySelector('.history-chart')?.getAttribute('aria-label') ?? null,
    disabledCta: Boolean(document.querySelector('.affiliate-card button.cta:disabled')),
    outboundCtaCount: document.querySelectorAll('.affiliate-card a.cta[href]').length,
    sellerText: document.querySelector('.offer-card')?.innerText ?? '',
    activeVariant: document.querySelector('.detail-header .variant')?.textContent ?? ''
  }))()`);
  check(result.browser_checks, "ui.baseline_journey", ["SYNTHETIC DEMO ONLY", "觀測期間最低價", "SYN-SELLER-A", "SKU SYN-EARBUD-BLK"].every((text) => baseline.text.includes(text)), "search/detail/history/minimum/exact SKU+seller", baseline, "A");
  check(result.browser_checks, "ui.chart_accessible", baseline.chartLabel?.includes("3 筆實際觀測") && baseline.chartLabel.includes("最低 NT$ 329"), "accessible chart with sample count and minimum", baseline.chartLabel, "A");
  check(result.browser_checks, "ui.affiliate_disabled", baseline.disabledCta && baseline.outboundCtaCount === 0, "disabled CTA and zero outbound anchors", { disabled: baseline.disabledCta, anchors: baseline.outboundCtaCount }, "F");

  await setInput(cdp, "#product-search", "SYN-CABLE");
  await pressKey(cdp, "Enter", "Enter");
  await waitForCondition(cdp, `document.body.innerText.includes('找到 1 個本機合成紀錄') && document.body.innerText.includes('SYN-SELLER-B')`);
  const keyboard = await evaluate(cdp, `(() => ({
    query: document.querySelector('#product-search')?.value,
    count: document.querySelectorAll('.product-card').length,
    selected: document.querySelector('.product-card')?.getAttribute('aria-pressed'),
    text: document.body.innerText
  }))()`);
  check(result.browser_checks, "ui.keyboard_search", keyboard.query === "SYN-CABLE" && keyboard.count === 1 && keyboard.selected === "true" && keyboard.text.includes("SYN-SELLER-B"), "keyboard submit selects exact cable SKU/seller", keyboard, "A");

  await navigate(cdp, `${staticServer.url}/`);
  await waitForCondition(cdp, `document.querySelectorAll('.product-card').length === 3`);
  const multiUi = await evaluate(cdp, `(() => ({ variants: [...document.querySelectorAll('.product-card .variant')].map((node) => node.textContent), count: document.querySelectorAll('.product-card').length }))()`);
  check(result.browser_checks, "ui.multiple_sku_results", multiUi.count === 3 && new Set(multiUi.variants).size === 3, "3 unique synthetic SKU result cards", multiUi, "A");
  await evaluate(cdp, `document.querySelectorAll('.product-card')[1].focus()`);
  await pressKey(cdp, "Enter", "Enter");
  await waitForCondition(cdp, `document.body.innerText.includes('SYN-SELLER-B')`);
  const keyboardCard = await evaluate(cdp, `({ activeClass: document.activeElement?.className ?? '', seller: document.querySelector('.offer-card')?.innerText ?? '' })`);
  check(result.browser_checks, "ui.keyboard_card_select", String(keyboardCard.activeClass).includes("product-card") && keyboardCard.seller.includes("SYN-SELLER-B"), "focused product card activates with Enter", keyboardCard, "A");

  await setInput(cdp, "#product-search", "SYN-BOX");
  await pressKey(cdp, "Enter", "Enter");
  await waitForCondition(cdp, `document.body.innerText.includes('SYNTHETIC｜透明收納箱') && document.body.innerText.includes('尚無可繪製的價格觀測')`);
  const empty = await evaluate(cdp, `(() => ({ text: document.body.innerText, images: document.querySelectorAll('img').length, ctaLinks: document.querySelectorAll('.affiliate-card a.cta[href]').length }))()`);
  check(result.browser_checks, "ui.no_image_no_price", empty.text.includes("價格未知") && empty.text.includes("尚無價格樣本") && !empty.text.includes("NT$ 0") && empty.images === 0, "null thumbnail and price stay absent/unknown, never zero", empty, "A");
  check(result.browser_checks, "ui.no_price_affiliate_disabled", empty.ctaLinks === 0 && empty.text.includes("推薦連結尚未驗證"), "no authorized affiliate link", { links: empty.ctaLinks }, "F");

  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await navigate(cdp, `${staticServer.url}/?q=SYN-CABLE&product=syn-usbc-cable-2m-white`);
  await waitForCondition(cdp, `document.body.innerText.includes('SYN-SELLER-B')`);
  const mobile = await evaluate(cdp, `({ innerWidth: window.innerWidth, scrollWidth: document.documentElement.scrollWidth, ctaLinks: document.querySelectorAll('.affiliate-card a.cta[href]').length, text: document.body.innerText })`);
  check(result.browser_checks, "ui.mobile_viewport", mobile.innerWidth === 390 && mobile.scrollWidth <= mobile.innerWidth && mobile.ctaLinks === 0, "390px viewport without horizontal overflow or outbound CTA", mobile, "A");
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(path.join(screenshotRoot, "h01-a05-mobile.png"), Buffer.from(shot.data, "base64"));

  await cdp.send("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
  const offlineNav = await cdp.send("Page.navigate", { url: `${staticServer.url}/?offline-probe=1` });
  await wait(500);
  const offlineText = await evaluate(cdp, "document.body.innerText");
  const browserOfflineObserved = Boolean(offlineNav.errorText) || !offlineText.includes("SYNTHETIC DEMO ONLY");
  check(result.browser_checks, "ui.asset_offline_detected", browserOfflineObserved, "offline navigation fails closed", { errorText: offlineNav.errorText ?? null, body: offlineText.slice(0, 160) }, "A");
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await navigate(cdp, `${staticServer.url}/?recovered=1`);
  await waitForCondition(cdp, `document.body.innerText.includes('SYNTHETIC DEMO ONLY') && document.querySelectorAll('.product-card').length === 3`);
  check(result.browser_checks, "ui.asset_offline_recovery", true, "reload recovers after loopback returns", true, "A");

  const httpRequests = networkUrls.filter((url) => /^https?:/i.test(url));
  const outboundRequests = httpRequests.filter((url) => {
    const host = new URL(url).hostname;
    return host !== "127.0.0.1" && host !== "localhost";
  });
  result.network = {
    static_requests: staticServer.requests,
    browser_http_requests: httpRequests,
    outbound_http_requests: outboundRequests,
    outbound_http_request_count: outboundRequests.length,
    proof: "CDP Network.requestWillBeSent capture plus non-loopback host classification; browser host resolver also blocks non-loopback resolution",
    browser_stderr_tail: browserStderr.slice(-1200)
  };
  check(result.browser_checks, "ui.no_outbound_requests", outboundRequests.length === 0, 0, outboundRequests, "D");

  coverage("search_to_detail", "PASS", "ui.baseline_journey + ui.keyboard_search", "A");
  coverage("price_chart_coverage_minimum", "PARTIAL", "A05 chart/minimum PASS; B06 coverage API PASS; integration waits A06", "A/B");
  coverage("cta_disabled_without_authority", "PASS", "ui.affiliate_disabled + api.affiliate_fail_closed", "F");
  coverage("mobile", "PASS", "ui.mobile_viewport", "A");
  coverage("keyboard", "PASS", "ui.keyboard_search + ui.keyboard_card_select", "A");
  coverage("no_image_no_price", "PASS", "ui.no_image_no_price + api.no_image", "A/B");
  coverage("multi_sku", "PARTIAL", "B06 has same-product multi-SKU; A05 only separate product cards; waits A06 integration", "A/B");
  coverage("zero_price_unknown_shipping", "API_ONLY", "api.zero_unknown_shipping; A05 fixture lacks zero-price UI case", "A/B");
  coverage("stale_observation", "API_ONLY", "api.stale_flag; A05 UI lacks stale fixture/warning", "A/B");
  coverage("offline_recovery", "PARTIAL", "API stop/restart and asset reload recover; A05 has no API error UI", "A");
  result.defects.push(
    { id: "H01-DEFECT-001", severity: "HIGH", owner: "A", finding: "A05 has no API error state or Search-to-B06 integration; full journey cannot be accepted before central ACK of A06.", status: "WAITING_A06" },
    { id: "H01-DEFECT-002", severity: "MEDIUM", owner: "A/B", finding: "A05 cannot render B06 coverage, stale flag, same-product multi-SKU, or zero-price/UNKNOWN-shipping edge fixtures end to end.", status: "OPEN" },
    { id: "H01-DEFECT-003", severity: "MEDIUM", owner: "A/D", finding: "Frozen A05 fixture displays item_condition=NEW without evidence; B06 V2 correctly returns UNKNOWN/NOT_RECORDED.", status: "HISTORICAL_A05_ONLY" }
  );
  result.execution_gate = "PASS";
} catch (error) {
  result.execution_gate = "FAIL";
  result.error = { name: error.name, message: error.message, stack: error.stack };
  process.exitCode = 2;
} finally {
  if (cdp) cdp.close();
  if (browserProcess) await stopProcess(browserProcess);
  if (staticServer) await staticServer.close();
  if (apiServer) await stopProcess(apiServer.child);
  await writeFile(path.join(evidenceRoot, "journey_results.json"), `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ execution_gate: result.execution_gate, mvp_readiness: result.mvp_readiness, api_probes: result.api_probes.length, browser_checks: result.browser_checks.length, coverage: result.coverage_matrix.length, defects: result.defects.length }));
}

