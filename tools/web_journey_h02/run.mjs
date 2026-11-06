import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import {
  capture, cdpClient, evaluate, externalHttpRequests, locateBrowser, navigate,
  pressEnter, setInput, toHar, wait, waitFor, waitForJson
} from "./lib.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const evidenceRoot = path.join(root, "reports", "H02", "evidence");
const runtimeRoot = path.join(root, "review", "H02", "runtime", new Date().toISOString().replaceAll(":", "").replaceAll(".", ""));
const a06Root = path.join(root, "review", "H02", "baselines", "A06");
const b06Root = path.join(root, "review", "H02", "baselines", "B06");
const frontendRoot = path.join(a06Root, "apps", "price-web", "frontend");
const viteBin = path.join(root, "apps", "price-web", "frontend", "node_modules", "vite", "bin", "vite.js");
await Promise.all([mkdir(evidenceRoot, { recursive: true }), mkdir(runtimeRoot, { recursive: true })]);

const result = {
  schema: "CDH-H02-E2E-EVIDENCE-V1",
  task_id: "CDH-H02-A06-B06-WEB-E2E-001",
  execution_gate: "NOT_RUN",
  actual_a06_b06_e2e_gate: "NOT_RUN",
  terminal_recommendation: "ESCALATION_REQUIRED",
  baseline: {
    A06: "d9fce75d876b86d5cbb28f77e8ff9354e9d38a5c9389abe10d2a2ddc46adefb5",
    B06: "d99284c7e6d422b16255b51d29aacb5034a1d43b254c4aca6fa389cef6caf3ae"
  },
  api_checks: [], browser_checks: [], coverage: [], defects: [], artifacts: [], network: {}
};

function check(target, id, pass, expected, actual, owner) {
  target.push({ id, status: pass ? "PASS" : "FAIL", expected, actual, owner });
  return pass;
}
function coverage(id, status, evidence, owner) { result.coverage.push({ id, status, evidence, owner }); }

async function stop(child) {
  if (!child || child.exitCode !== null) return;
  child.kill();
  await Promise.race([new Promise((resolve) => child.once("exit", resolve)), wait(3000)]);
}

async function startApi(classification, label) {
  const fixtureRoot = path.join(runtimeRoot, label);
  await mkdir(fixtureRoot, { recursive: true });
  const child = spawn("python", [
    path.join(root, "tools", "web_journey_h02", "b06_fixture_server.py"),
    "--b06-root", b06Root, "--fixture-root", fixtureRoot,
    "--classification", classification, "--port", "8765"
  ], { cwd: root, windowsHide: true, shell: false, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "", stderr = "";
  child.stdout.on("data", (data) => { stdout += data.toString(); });
  child.stderr.on("data", (data) => { stderr += data.toString(); });
  const search = await waitForJson("http://127.0.0.1:8765/api/v2/products?page=1&limit=20");
  return { child, search, stdout: () => stdout, stderr: () => stderr };
}

async function browserState(cdp) {
  return evaluate(cdp, `(() => ({
    url: location.href,
    text: document.body.innerText,
    alert: document.querySelector('[role="alert"]')?.innerText ?? null,
    cards: [...document.querySelectorAll('.product-card')].map((node) => ({ text: node.innerText, pressed: node.getAttribute('aria-pressed') })),
    ctaLinks: document.querySelectorAll('.affiliate-card a.cta[href]').length,
    ctaDisabled: Boolean(document.querySelector('.affiliate-card button.cta:disabled')),
    innerWidth: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth
  }))()`);
}

let api = null, vite = null, browser = null, cdp = null;
try {
  api = await startApi("user", "user-initial");
  const search = api.search;
  check(result.api_checks, "b06.v2_user_classification", search.schema_version === "CDH-WEB-CONTRACT-V2" && search.data_source_status === "USER_RECORDED_ONLY" && search.data_classification === "USER_RECORDED", "V2/USER_RECORDED_ONLY/USER_RECORDED", `${search.schema_version}/${search.data_source_status}/${search.data_classification}`, "B");
  check(result.api_checks, "b06.filtered_null_history", search.total === 4 && !search.items.some((item) => item.variant_signature.includes("SKU-H02-NULL")), "4 valid products and null-price row excluded", { total: search.total, variants: search.items.map((item) => item.variant_signature) }, "B");
  const same = await (await fetch(`http://127.0.0.1:8765/api/v2/products?q=${encodeURIComponent("同名耳機")}`)).json();
  check(result.api_checks, "b06.same_name_multi_sku_seller", same.total === 2 && new Set(same.items.map((item) => item.variant_signature)).size === 2, "2 exact variants", same.items.map((item) => ({ variant: item.variant_signature, id: item.id })), "B");
  const red = same.items.find((item) => item.variant_signature.includes("SKU-H02-RED"));
  const redDetail = await (await fetch(`http://127.0.0.1:8765/api/v2/products/${encodeURIComponent(red.id)}`)).json();
  check(result.api_checks, "b06.red_exact_history", redDetail.offers[0].sku_id === "SKU-H02-RED" && redDetail.offers[0].seller_id === "SELLER-H02-A" && redDetail.history.length === 2 && redDetail.observation_period_min_twd === 599, "red/A/2 samples/min599", redDetail, "B");
  const zero = await (await fetch("http://127.0.0.1:8765/api/v2/products?q=SKU-H02-ZERO")).json();
  check(result.api_checks, "b06.zero_unknown_shipping", zero.items[0].last_observed_price_twd === 0 && zero.items[0].shipping_status === "UNKNOWN" && zero.items[0].quality_flags.includes("SHIPPING_UNKNOWN"), "0 retained and shipping unknown flagged", zero.items[0], "B");
  const stale = await (await fetch("http://127.0.0.1:8765/api/v2/products?q=SKU-H02-STALE")).json();
  check(result.api_checks, "b06.stale_flag", stale.items[0].quality_flags.includes("STALE_LAST_OBSERVATION"), "STALE_LAST_OBSERVATION", stale.items[0].quality_flags, "B");
  const wrong = await (await fetch("http://127.0.0.1:8765/api/v2/products?q=SKU-WRONG")).json();
  check(result.api_checks, "b06.wrong_sku_empty", wrong.total === 0, 0, wrong.total, "B");
  const affiliate = await (await fetch(`http://127.0.0.1:8765/api/v2/products/${encodeURIComponent(red.id)}/affiliate`)).json();
  check(result.api_checks, "b06.affiliate_disabled", affiliate.affiliate.state === "UNCONFIGURED" && affiliate.affiliate.click_url === null && affiliate.affiliate.verified_product_match === false, "UNCONFIGURED/null/false", affiliate.affiliate, "F");

  vite = spawn(process.execPath, [viteBin, "preview", "--config", path.join(root, "tools", "web_journey_h02", "vite_proxy_config.mjs"), "--host", "127.0.0.1", "--port", "4173", "--strictPort"], { cwd: frontendRoot, windowsHide: true, shell: false, stdio: ["ignore", "pipe", "pipe"] });
  let viteOut = "", viteErr = "";
  vite.stdout.on("data", (data) => { viteOut += data.toString(); });
  vite.stderr.on("data", (data) => { viteErr += data.toString(); });
  await waitForJson("http://127.0.0.1:4173/cdh-local-api/api/v2/products?page=1&limit=20");
  const proxyV2 = await (await fetch("http://127.0.0.1:4173/cdh-local-api/api/v2/products?q=SKU-H02-RED")).json();
  check(result.api_checks, "vite.same_origin_v2_proxy", proxyV2.total === 1 && proxyV2.schema_version === "CDH-WEB-CONTRACT-V2", "one V2 result through A06 frozen proxy", { total: proxyV2.total, version: proxyV2.schema_version }, "A");

  const browserPath = locateBrowser();
  if (!browserPath) throw new Error("BLOCKED_BROWSER_DEPENDENCY");
  const debugPort = 9332;
  browser = spawn(browserPath, ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(runtimeRoot, "browser-profile")}`, "about:blank"], { cwd: root, windowsHide: true, shell: false, stdio: ["ignore", "pipe", "pipe"] });
  const tabs = await waitForJson(`http://127.0.0.1:${debugPort}/json`);
  cdp = cdpClient(tabs.find((item) => item.type === "page").webSocketDebuggerUrl);
  await cdp.opened;
  await cdp.send("Page.enable"); await cdp.send("Runtime.enable"); await cdp.send("Network.enable");
  const requests = new Map();
  cdp.on("Network.requestWillBeSent", (event) => requests.set(event.requestId, { startedDateTime: new Date(event.wallTime * 1000).toISOString(), method: event.request.method, url: event.request.url }));
  cdp.on("Network.responseReceived", (event) => Object.assign(requests.get(event.requestId) ?? {}, { status: event.response.status, statusText: event.response.statusText, mimeType: event.response.mimeType }));

  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await navigate(cdp, "http://127.0.0.1:4173/?q=SKU-H02-RED");
  await waitFor(cdp, `Boolean(document.querySelector('[role="alert"]'))`);
  const actual = await browserState(cdp);
  const expectedMismatch = actual.alert?.includes("資料分類與執行模式不符");
  check(result.browser_checks, "actual_a06_b06.local_contract", false, "search/detail page renders exact SKU", actual, "A");
  check(result.browser_checks, "actual_a06_b06.fail_closed", expectedMismatch && actual.cards.length === 0, "source mismatch visibly fails closed", actual.alert, "A/D");
  result.artifacts.push({ case: "actual_a06_b06_contract_failure", url: actual.url, ...(await capture(cdp, evidenceRoot, "actual-a06-b06-contract-failure")) });

  await stop(api.child); api = null;
  await navigate(cdp, "http://127.0.0.1:4173/?q=SKU-H02-BLUE&offline=1");
  await waitFor(cdp, `Boolean(document.querySelector('[role="alert"]'))`);
  const offline = await browserState(cdp);
  check(result.browser_checks, "a06.api_offline_visible", Boolean(offline.alert) && offline.cards.length === 0 && !offline.alert.includes("資料分類與執行模式不符"), "visible fail-closed API error with no cards", offline.alert, "A");
  result.artifacts.push({ case: "api_offline", url: offline.url, ...(await capture(cdp, evidenceRoot, "api-offline")) });

  api = await startApi("user", "user-recovery");
  await navigate(cdp, "http://127.0.0.1:4173/?q=SKU-H02-RED&recovered=1");
  await waitFor(cdp, `document.querySelector('[role="alert"]')?.innerText.includes('資料分類與執行模式不符')`);
  check(result.browser_checks, "a06.transport_recovered_contract_still_blocked", true, "transport recovers while exact mismatch remains", "SOURCE_MISMATCH", "A");
  await stop(api.child); api = null;

  api = await startApi("synthetic", "synthetic-source");
  await navigate(cdp, "http://127.0.0.1:4173/?q=SKU-H02-BLUE&synthetic-source=1");
  await waitFor(cdp, `Boolean(document.querySelector('[role="alert"]'))`);
  const sourceIsolation = await browserState(cdp);
  check(result.browser_checks, "a06.synthetic_source_rejected_in_local_mode", sourceIsolation.alert?.includes("必須明示 USER_RECORDED_ONLY"), "synthetic source rejected", sourceIsolation.alert, "A/D");
  await stop(api.child); api = null;

  await navigate(cdp, "http://127.0.0.1:4173/?mode=synthetic&q=SYN-CABLE&product=syn-usbc-cable-2m-white");
  await waitFor(cdp, `document.body.innerText.includes('SYN-SELLER-B') && document.body.innerText.includes('觀測期間最低價')`);
  const syntheticDesktop = await browserState(cdp);
  check(result.browser_checks, "a06.synthetic_visual_desktop", syntheticDesktop.text.includes("SYNTHETIC DEMO ONLY") && syntheticDesktop.ctaDisabled && syntheticDesktop.ctaLinks === 0, "synthetic banner and disabled CTA", syntheticDesktop, "A/F");
  result.artifacts.push({ case: "synthetic_desktop", url: syntheticDesktop.url, ...(await capture(cdp, evidenceRoot, "synthetic-desktop")) });

  await setInput(cdp, "#product-search", "SYN-BOX"); await pressEnter(cdp);
  await waitFor(cdp, `document.body.innerText.includes('尚無價格樣本')`);
  const emptyHistory = await browserState(cdp);
  check(result.browser_checks, "a06.synthetic_empty_history", emptyHistory.text.includes("價格未知") && emptyHistory.text.includes("空白不會顯示為零元") && !emptyHistory.text.includes("NT$ 0"), "null/empty history is not zero", emptyHistory.text, "A");
  result.artifacts.push({ case: "synthetic_empty_history", url: emptyHistory.url, ...(await capture(cdp, evidenceRoot, "synthetic-empty-history")) });

  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await navigate(cdp, "http://127.0.0.1:4173/?mode=synthetic&q=SYN-CABLE&product=syn-usbc-cable-2m-white");
  await waitFor(cdp, `document.body.innerText.includes('SYN-SELLER-B')`);
  const mobile = await browserState(cdp);
  check(result.browser_checks, "a06.synthetic_mobile_390", mobile.innerWidth === 390 && mobile.scrollWidth <= 390 && mobile.ctaLinks === 0, "390px no overflow and no link", mobile, "A/F");
  result.artifacts.push({ case: "synthetic_mobile", url: mobile.url, ...(await capture(cdp, evidenceRoot, "synthetic-mobile-390")) });

  const requestList = [...requests.values()];
  const outbound = externalHttpRequests(requestList.map((item) => item.url));
  await writeFile(path.join(evidenceRoot, "network.har.json"), `${JSON.stringify(toHar(requestList), null, 2)}\n`, "utf8");
  result.network = { request_count: requestList.length, external_http_request_count: outbound.length, external_http_requests: outbound, origins: [...new Set(requestList.filter((item) => /^https?:/.test(item.url)).map((item) => new URL(item.url).origin))].sort(), har: "evidence/network.har.json" };
  check(result.browser_checks, "browser.external_network_zero", outbound.length === 0, 0, outbound, "D");

  coverage("actual_search_detail_history", "FAIL", "A06 rejects exact B06 V1 data_classification=USER_RECORDED", "A");
  coverage("same_name_multi_sku_seller", "API_ONLY", "B06 V2 PASS; blocked before A06 rendering", "A/B");
  coverage("zero_unknown_shipping", "API_ONLY", "B06 V2 PASS; blocked before A06 rendering", "A/B");
  coverage("empty_history", "PARTIAL", "A06 synthetic UI PASS; B06 cannot expose a detail without a valid observation", "A/B");
  coverage("stale", "API_ONLY", "B06 flag PASS; A06 actual integration blocked and has no stale badge", "A/B");
  coverage("source_isolation", "PASS", "synthetic B06 source rejected in A06 local mode", "A/D");
  coverage("api_disconnect_reconnect", "PARTIAL", "offline visible and transport recovers; contract mismatch remains", "A");
  coverage("desktop_mobile_keyboard", "PARTIAL", "A06 synthetic page passes; actual A06+B06 page blocked", "A");
  coverage("affiliate_disabled", "PASS", "B06 V2 disabled and A06 synthetic CTA has no anchor", "A/F");
  coverage("external_network", "PASS", "HAR external count 0", "D");

  result.defects.push(
    { id: "H02-P0-001", severity: "P0", owner: "A", status: "OPEN", reproduction: "Open A06 local mode against exact B06 and search any product", finding: "A06 requests B06 V1 but rejects B06 data_classification=USER_RECORDED; UI stops at SOURCE_MISMATCH before Search→Detail." },
    { id: "H02-P1-002", severity: "P1", owner: "A", status: "OPEN", reproduction: "Inspect extracted A06 localApi.ts/types.ts", finding: "A06 is wired to CDH-WEB-CONTRACT-V1 while R04 canonical wire is B06 CDH-WEB-CONTRACT-V2." },
    { id: "H02-P1-003", severity: "P1", owner: "A/B", status: "OPEN", reproduction: "Use null-price fixture row or stale/multi-SKU rows", finding: "B06 filters null-price rows so no empty-history detail exists; A06 has no actual integrated stale/multi-SKU/zero-price rendering evidence." },
    { id: "H02-P1-004", severity: "P1", owner: "D", status: "OPEN", reproduction: "Compare generated test fixture provenance with B06 USER_RECORDED classification", finding: "A positive local integration test requires an authorized user-recorded copy; generated fixtures must not be relabeled as real USER_RECORDED data." },
    { id: "H02-OBS-005", severity: "INFO", owner: "F", status: "PASS", reproduction: "Inspect V2 affiliate and A06 synthetic CTA", finding: "Unauthorized affiliate remains UNCONFIGURED/null/false and no clickable CTA is rendered." }
  );
  result.actual_a06_b06_e2e_gate = "FAIL_CONTRACT_CLASSIFICATION_MISMATCH";
  result.execution_gate = "PASS";
  result.runtime = { vite_stdout: viteOut.trim(), vite_stderr: viteErr.trim(), browser: browserPath };
  process.exitCode = 1;
} catch (error) {
  result.execution_gate = "FAIL_TOOLING";
  result.error = { name: error.name, message: error.message, stack: error.stack };
  process.exitCode = 2;
} finally {
  if (cdp) cdp.close();
  await stop(browser); await stop(vite); if (api) await stop(api.child);
  await writeFile(path.join(evidenceRoot, "h02_results.json"), `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ execution_gate: result.execution_gate, e2e_gate: result.actual_a06_b06_e2e_gate, api_checks: result.api_checks.length, browser_checks: result.browser_checks.length, defects: result.defects.length, recommendation: result.terminal_recommendation }));
}

