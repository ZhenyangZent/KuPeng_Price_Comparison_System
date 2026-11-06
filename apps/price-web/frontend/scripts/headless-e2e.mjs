import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = path.resolve(frontendRoot, "../../..");
const reportRoot = path.join(projectRoot, "reports", "A10");
const screenshots = path.join(reportRoot, "screenshots");
const evidence = path.join(reportRoot, "evidence");
const runId = new Date().toISOString().replaceAll(":", "").replaceAll(".", "");
const runtime = path.join(reportRoot, "headless_runtime", runId);
const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const viteBin = path.join(frontendRoot, "node_modules", "vite", "bin", "vite.js");
await Promise.all([mkdir(screenshots, { recursive: true }), mkdir(evidence, { recursive: true }), mkdir(runtime, { recursive: true })]);

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function waitForJson(url) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try { const response = await fetch(url); if (response.ok) return response.json(); } catch { /* local endpoint not ready */ }
    await wait(100);
  }
  throw new Error(`Local endpoint did not become ready: ${url}`);
}
async function waitForHttp(url) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try { if ((await fetch(url)).ok) return; } catch { /* local endpoint not ready */ }
    await wait(100);
  }
  throw new Error(`Local endpoint did not become ready: ${url}`);
}
function cdpClient(webSocketUrl) {
  const socket = new WebSocket(webSocketUrl);
  let nextId = 1;
  const pending = new Map();
  const events = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message)); else resolve(message.result);
      return;
    }
    const listeners = events.get(message.method) ?? [];
    listeners.splice(0).forEach((resolve) => resolve(message.params));
  });
  const opened = new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  return {
    opened,
    send(method, params = {}) {
      const id = nextId++;
      return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); });
    },
    once(method) { return new Promise((resolve) => events.set(method, [...(events.get(method) ?? []), resolve])); },
    close() { socket.close(); }
  };
}

const stub = spawn(process.execPath, [path.join(frontendRoot, "scripts", "local-api-stub.mjs")], { cwd: frontendRoot, shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
const python = process.env.CDH_TEST_PYTHON ?? "python";
const b10Server = spawn(python, [path.join(frontendRoot, "scripts", "b10-actual-wsgi-server.py"), "--port", "8766", "--runtime-root", runtime], { cwd: frontendRoot, shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
// Use Vite preview of the production build: dev mode injects an inline React-refresh
// bootstrap, which is intentionally rejected by the A09 CSP (no unsafe-inline).
const vite = spawn(process.execPath, [viteBin, "preview", "--host", "127.0.0.1", "--port", "4173", "--strictPort"], { cwd: frontendRoot, shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
let stubStdout = "", stubStderr = "", b10Stdout = "", b10Stderr = "", viteStdout = "", viteStderr = "";
stub.stdout.on("data", (data) => { stubStdout += data.toString(); process.stdout.write(data); });
stub.stderr.on("data", (data) => { stubStderr += data.toString(); process.stderr.write(data); });
b10Server.stdout.on("data", (data) => { b10Stdout += data.toString(); process.stdout.write(data); });
b10Server.stderr.on("data", (data) => { b10Stderr += data.toString(); process.stderr.write(data); });
vite.stdout.on("data", (data) => { viteStdout += data.toString(); process.stdout.write(data); });
vite.stderr.on("data", (data) => { viteStderr += data.toString(); process.stderr.write(data); });

const debugPort = 9326;
const chromeProfile = path.join(runtime, "chrome-cdp");
const chromeArgs = ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${chromeProfile}`, "about:blank"];
const chromeProcess = spawn(chrome, chromeArgs, { cwd: frontendRoot, shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
let chromeStderr = "";
chromeProcess.stderr.on("data", (data) => { chromeStderr += data.toString(); });

const cases = [
  { name: "local-desktop", mode: "LOCAL_API", width: 1440, height: 1100, mobile: false, url: "http://127.0.0.1:4173/?product=p_a06_fixture", required: ["LOCAL LOOPBACK · READ ONLY", "SYNTHETIC TEST FIXTURE｜防風外套", "觀測期間最低價", "尚未取得可驗證的專屬連結"], forbidden: ["SYNTHETIC FIXTURE ONLY", "資料驗證失敗"] },
  { name: "local-mobile-sku", mode: "LOCAL_API", width: 390, height: 844, mobile: true, url: "http://127.0.0.1:4173/?q=SKU-XL-42&product=p_a06_fixture", required: ["LOCAL LOOPBACK · READ ONLY", "SKU-XL-42", "CDH-WEB-CONTRACT-V2"], forbidden: ["SYNTHETIC FIXTURE ONLY", "驗證失敗"] },
  { name: "synthetic-zero-unknown", mode: "SYNTHETIC_DEMO", width: 1024, height: 900, mobile: false, url: "http://127.0.0.1:4173/?mode=synthetic&product=syn-earbuds-white", required: ["SYNTHETIC FIXTURE ONLY", "NT$0 是記錄價格", "運費與資格仍為 UNKNOWN", "尚未取得可驗證的專屬連結"], forbidden: ["LOCAL LOOPBACK · READ ONLY"] },
  { name: "synthetic-unavailable-mobile", mode: "SYNTHETIC_DEMO", width: 390, height: 844, mobile: true, scrollSelector: ".detail-panel", url: "http://127.0.0.1:4173/?mode=synthetic&product=syn-empty", required: ["價格不可用", "此商品沒有適用、可比的價格", "不推導 NT$0、免運", "尚無可繪製的價格觀測", "尚未取得可驗證的專屬連結"], forbidden: ["href=\"https://"] }
  ,{ name: "v4-confirmed-desktop", mode: "B10_ACTUAL_WSGI", width: 1440, height: 1100, mobile: false, url: "http://127.0.0.1:4173/?mode=synthetic&contract=v4&series=series-confirmed", required: ["B10 WSGI · SYNTHETIC API", "B10 Actual｜Confirmed coupon", "已確認券後商品價", "NT$ 49", "券前商品價歷史", "已確認券後商品價歷史", "SYN-SKU-CONFIRMED", "正式連結尚未核准"], forbidden: ["href=\"https://"] },
  { name: "v4-claim-mobile", mode: "B10_ACTUAL_WSGI", width: 390, height: 844, mobile: true, scrollSelector: ".coupon-detail", scopeSelector: ".coupon-detail", url: "http://127.0.0.1:4173/?mode=synthetic&contract=v4&series=series-claim", required: ["需先領券，尚未確認", "可能券後價 NT$ 75 不會作為主價", "NT$ 100", "沒有已確認券後 raw observation"], forbidden: ["已確認券後商品價為 NT$75", "href=\"https://"] },
  { name: "v4-expired", mode: "B10_ACTUAL_WSGI", width: 1024, height: 900, mobile: false, scopeSelector: ".coupon-detail", url: "http://127.0.0.1:4173/?mode=synthetic&contract=v4&series=series-expired", required: ["優惠券已過期／目前不可用", "券前商品價", "NT$ 120", "已確認券後商品價歷史"], forbidden: ["href=\"https://"] },
  { name: "v4-zero-not-total", mode: "B10_ACTUAL_WSGI", width: 1024, height: 900, mobile: false, scopeSelector: ".coupon-detail", url: "http://127.0.0.1:4173/?mode=synthetic&contract=v4&series=series-zero", required: ["已確認券後商品價為 NT$0，但不是零成本到手", "required_total_twd 維持 null", "含運必要總額", "UNKNOWN"], forbidden: ["免費到手", "href=\"https://"] },
  { name: "v4-unknown-mobile", mode: "B10_ACTUAL_WSGI", width: 390, height: 844, mobile: true, scrollSelector: ".coupon-detail", scopeSelector: ".coupon-detail", url: "http://127.0.0.1:4173/?mode=synthetic&contract=v4&series=series-unknown", required: ["價格未知", "未提供優惠券", "SOURCE_PERMISSION_ACTIVE"], forbidden: ["NT$ 0", "href=\"https://"] },
  { name: "v4-multi-order", mode: "B10_ACTUAL_WSGI", width: 1024, height: 900, mobile: false, scopeSelector: ".coupon-detail", url: "http://127.0.0.1:4173/?mode=synthetic&contract=v4&series=series-multi", required: ["B10 Actual｜Two-item order coupon", "NT$ 75", "最低數量", "最低商品額", "NT$ 150", "ORDER_TOTAL"], forbidden: ["含運必要總額</b>NT$ 150", "href=\"https://"] },
  { name: "v4-exact-variant", mode: "B10_ACTUAL_WSGI", width: 1024, height: 900, mobile: false, scopeSelector: ".coupon-detail", url: "http://127.0.0.1:4173/?mode=synthetic&contract=v4&series=series-variant", required: ["SYN-SKU-OTHER", "SYN-SELLER-F", "NT$ 89"], forbidden: ["SYN-SKU-CONFIRMED · SYN-SELLER-A", "href=\"https://"] }
  ,{ name: "v4-empty-filter", mode: "B11_ACTUAL_WSGI", width: 1024, height: 900, mobile: false, url: "http://127.0.0.1:4173/?mode=synthetic&contract=v4&q=no-such-product", required: ["V4 snapshot 有商品，但查無符合結果", "請選擇 V4 商品序列"], forbidden: ["B10 Actual｜Confirmed coupon", "href=\"https://"] }
  ,{ name: "v4-keyboard-search", mode: "B11_ACTUAL_WSGI_KEYBOARD", width: 1024, height: 900, mobile: false, keyboardSearch: "SYN-SKU-MULTI", expectedUrlIncludes: "q=SYN-SKU-MULTI", url: "http://127.0.0.1:4173/?mode=synthetic&contract=v4", required: ["1／1 個序列", "B10 Actual｜Two-item order coupon", "SYN-SKU-MULTI", "NT$ 75"], forbidden: ["B10 Actual｜Claim required", "href=\"https://"] }
];
const results = [];

try {
  await Promise.all([waitForHttp("http://127.0.0.1:8765/api/v2/products"), waitForHttp("http://127.0.0.1:8766/api/v4/products"), waitForHttp("http://127.0.0.1:4173/")]);
  const shellResponse = await fetch("http://127.0.0.1:4173/");
  const contentSecurityPolicy = shellResponse.headers.get("content-security-policy") ?? "";
  const directSearchResponse = await fetch("http://127.0.0.1:8766/api/v4/products?q=&page=1&limit=20");
  const directSearchBody = await directSearchResponse.json();
  const missingResponse = await fetch("http://127.0.0.1:8766/api/v4/products/series-does-not-exist");
  await writeFile(path.join(evidence, "ACTUAL_B10_HTTP_PROBE.json"), `${JSON.stringify({
    content_security_policy: contentSecurityPolicy,
    csp_same_origin_only: contentSecurityPolicy.includes("connect-src 'self'") && !contentSecurityPolicy.includes("connect-src *") && !contentSecurityPolicy.includes("unsafe-inline"),
    search_status: directSearchResponse.status,
    search_schema_version: directSearchBody.schema_version,
    search_total: directSearchBody.total,
    missing_detail_status: missingResponse.status,
    missing_detail_body: await missingResponse.json()
  }, null, 2)}\n`, "utf8");
  if (!contentSecurityPolicy.includes("connect-src 'self'") || contentSecurityPolicy.includes("connect-src *") || contentSecurityPolicy.includes("unsafe-inline")) throw new Error("CSP is not same-origin strict");
  if (directSearchResponse.status !== 200 || directSearchBody.schema_version !== "CDH-COUPON-PRICE-V4" || missingResponse.status !== 404) throw new Error("Actual B10 HTTP probe failed");
  const tabs = await waitForJson(`http://127.0.0.1:${debugPort}/json`);
  const tab = tabs.find((item) => item.type === "page");
  if (!tab?.webSocketDebuggerUrl) throw new Error("Chrome page target was not available");
  const cdp = cdpClient(tab.webSocketDebuggerUrl);
  await cdp.opened;
  await cdp.send("Page.enable");
  for (const item of cases) {
    const screenshot = path.join(screenshots, `a10-${item.name}.png`);
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: item.width, height: item.height, deviceScaleFactor: 1, mobile: item.mobile });
    const loaded = cdp.once("Page.loadEventFired");
    await cdp.send("Page.navigate", { url: item.url });
    await loaded;
    await wait(700);
    if (item.keyboardSearch) {
      await cdp.send("Runtime.evaluate", { expression: 'document.querySelector("#coupon-api-search")?.focus()' });
      await cdp.send("Input.insertText", { text: item.keyboardSearch });
      await cdp.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
      await wait(900);
    }
    if (item.scrollSelector) {
      await cdp.send("Runtime.evaluate", { expression: `document.querySelector(${JSON.stringify(item.scrollSelector)})?.scrollIntoView({block:"start"})` });
      await wait(200);
    }
    const evaluation = await cdp.send("Runtime.evaluate", { expression: `({ html: document.documentElement.outerHTML, scopeHtml: ${item.scopeSelector ? `document.querySelector(${JSON.stringify(item.scopeSelector)})?.outerHTML ?? ""` : "document.documentElement.outerHTML"}, locationHref: location.href, innerWidth: window.innerWidth, scrollWidth: document.documentElement.scrollWidth })`, returnByValue: true });
    const dom = evaluation.result.value.html;
    const checkDom = evaluation.result.value.scopeHtml;
    const missing = item.required.filter((text) => !checkDom.includes(text));
    const forbiddenPresent = item.forbidden.filter((text) => checkDom.includes(text));
    const outboundAnchorCount = (checkDom.match(/<a[^>]+class="cta"/g) ?? []).length;
    const noHorizontalOverflow = evaluation.result.value.scrollWidth <= evaluation.result.value.innerWidth;
    const expectedUrlMatch = !item.expectedUrlIncludes || evaluation.result.value.locationHref.includes(item.expectedUrlIncludes);
    const captured = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(screenshot, Buffer.from(captured.data, "base64"));
    await writeFile(path.join(evidence, `HEADLESS_${item.name.toUpperCase().replaceAll("-", "_")}_DOM.html`), dom, "utf8");
    results.push({ case: item.name, data_mode: item.mode, url: item.url, url_after_interaction: evaluation.result.value.locationHref, expected_url_match: expectedUrlMatch, viewport: `${item.width}x${item.height}`, required_text_missing: missing, forbidden_text_present: forbiddenPresent, outbound_anchor_count: outboundAnchorCount, inner_width: evaluation.result.value.innerWidth, scroll_width: evaluation.result.value.scrollWidth, no_horizontal_overflow: noHorizontalOverflow, screenshot: path.relative(projectRoot, screenshot).replaceAll("\\", "/"), pass: missing.length === 0 && forbiddenPresent.length === 0 && outboundAnchorCount === 0 && noHorizontalOverflow && expectedUrlMatch });
  }
  cdp.close();
} finally {
  chromeProcess.kill();
  vite.kill();
  stub.kill();
  b10Server.kill();
}

const summary = {
  task_id: "CDH-A10-B10-ACTUAL-API-UI-INTEGRATION-001",
  browser: chrome,
  local_only: true,
  proxy_targets: ["http://127.0.0.1:8765", "http://127.0.0.1:8766"],
  api_stub_stdout: stubStdout.trim(),
  api_stub_stderr: stubStderr.trim(),
  b10_actual_wsgi_stdout: b10Stdout.trim(),
  b10_actual_wsgi_stderr: b10Stderr.trim(),
  vite_stdout: viteStdout.trim(),
  vite_stderr: viteStderr.trim(),
  chrome_stderr: chromeStderr.trim(),
  results,
  all_pass: results.length === cases.length && results.every((item) => item.pass)
};
await writeFile(path.join(evidence, "HEADLESS_E2E.json"), `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify(summary));
process.exitCode = summary.all_pass ? 0 : 1;
