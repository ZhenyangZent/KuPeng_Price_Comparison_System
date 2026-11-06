import { execFileSync, spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const previewRoot = path.resolve(here, "..");
const projectRoot = path.resolve(previewRoot, "../../..");
const control = path.join(previewRoot, "control.py");
const python = process.env.CDH_TEST_PYTHON ?? "python";
const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const a12 = process.argv.includes("--a12");
const version = a12 ? "A12" : "A11";
const port = a12 ? 4195 : 4194, debugPort = a12 ? 9433 : 9332;
const reportRoot = path.join(projectRoot, "reports", version);
const evidence = path.join(reportRoot, "evidence");
const screenshots = path.join(reportRoot, "screenshots");
const runId = new Date().toISOString().replaceAll(":", "").replaceAll(".", "");
const runtime = path.join(reportRoot, "browser_runtime", runId);
const state = path.join(runtime, "state");
await Promise.all([mkdir(evidence, { recursive: true }), mkdir(screenshots, { recursive: true }), mkdir(runtime, { recursive: true })]);

const controlArgs = (action) => [control, action, "--project-root", projectRoot, "--port", String(port), "--state-dir", state, "--runtime-root", path.join(reportRoot, "evidence", "runtime"), "--log-dir", path.join(reportRoot, "evidence", "server_logs"), "--timeout", "20"];
function runControl(action) {
  const output = execFileSync(python, controlArgs(action), { cwd: previewRoot, windowsHide: true, encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1" } });
  return JSON.parse(output.trim().split(/\r?\n/).at(-1));
}
const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function waitForJson(url) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try { const response = await fetch(url); if (response.ok) return response.json(); } catch { /* loopback startup */ }
    await wait(100);
  }
  throw new Error(`Endpoint not ready: ${url}`);
}
function cdpClient(webSocketUrl) {
  const socket = new WebSocket(webSocketUrl);
  let nextId = 1;
  const pending = new Map(), listeners = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const pendingCall = pending.get(message.id); pending.delete(message.id);
      if (message.error) pendingCall.reject(new Error(message.error.message)); else pendingCall.resolve(message.result);
      return;
    }
    for (const callback of listeners.get(message.method) ?? []) callback(message.params);
  });
  const opened = new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  return {
    opened,
    send(method, params = {}) { const id = nextId++; return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); }); },
    once(method) { return new Promise((resolve) => { const callback = (params) => { listeners.set(method, (listeners.get(method) ?? []).filter((value) => value !== callback)); resolve(params); }; listeners.set(method, [...(listeners.get(method) ?? []), callback]); }); },
    on(method, callback) { listeners.set(method, [...(listeners.get(method) ?? []), callback]); },
    close() { socket.close(); }
  };
}

const a11Cases = [
  { name: "confirmed-desktop", width: 1440, height: 1000, mobile: false, series: "confirmed", required: ["B11 WSGI · SYNTHETIC API", "Synthetic confirmed", "已確認券後商品價", "NT$ 49", "券前每日代表價", "已確認券後每日代表價", "這是商品觀測價，不是結帳總額", "UNKNOWN 不等於 NT$0"], forbidden: ["href=\"https://"] },
  { name: "expired-coupon", width: 1100, height: 900, mobile: false, series: "expired-coupon", required: ["Synthetic expired-coupon", "優惠券已過期", "券前商品價", "NT$ 99", "沒有已確認券後每日代表價"], forbidden: ["href=\"https://"] },
  { name: "quantity-two-mobile", width: 390, height: 844, mobile: true, series: "quantity-two", required: ["Synthetic quantity-two", "最低數量", ">2<", "最低商品額", "NT$ 150", "ORDER_TOTAL"], forbidden: ["含運必要總額</b>NT$ 150", "href=\"https://"] },
  { name: "wrong-sku-fail-closed", width: 1024, height: 900, mobile: false, series: "wrong-sku", required: ["Synthetic wrong-sku", "券前商品價", "NT$ 99", "COUPON_IDENTITY_MISMATCH"], forbidden: ["已確認券後商品價</span><strong>NT$ 49", "href=\"https://"] },
  { name: "zero-not-checkout-total", width: 1024, height: 900, mobile: false, series: "zero", required: ["Synthetic zero", "NT$ 0", "不是零成本到手", "required_total_twd 維持 null", "UNKNOWN 不等於 NT$0"], forbidden: ["免費到手", "href=\"https://"] },
  { name: "empty-search", width: 1024, height: 900, mobile: false, query: "no-such-item", required: ["V4 snapshot 有商品，但查無符合結果", "請選擇 V4 商品序列"], forbidden: ["Synthetic confirmed", "href=\"https://"] },
  { name: "invalid-response", width: 1024, height: 900, mobile: false, invalidResponse: true, required: ["V4 Search 失敗，未載入示範資料", "B10_VERSION_MISMATCH"], forbidden: ["Synthetic confirmed", "href=\"https://"] },
  { name: "keyboard-search", width: 1024, height: 900, mobile: false, keyboardSearch: "SYN-SKU-QUANTITY_TWO", required: ["1／1 個序列", "Synthetic quantity-two", "SYN-SKU-QUANTITY_TWO"], forbidden: ["Synthetic confirmed", "href=\"https://"] }
];
const point = (price) => ({ prices: [price], dates: ["2026-11-04"], samples: [1] });
const history = (before, after) => ({
  "before_coupon:raw": { prices: before === null ? [] : [before], dates: before === null ? [] : ["2026-11-04"] },
  "confirmed_after_coupon:raw": { prices: after === null ? [] : [after], dates: after === null ? [] : ["2026-11-04"] },
  "before_coupon:daily": before === null ? { prices: [], dates: [], samples: [] } : point(before),
  "confirmed_after_coupon:daily": after === null ? { prices: [], dates: [], samples: [] } : point(after)
});
const a12Cases = [
  { ...a11Cases[0], history: history(99, 49), required: [...a11Cases[0].required, "券前 raw", "已確認券後 raw", "台北日界線彙整的每日代表價"] },
  { ...a11Cases[1], history: history(99, null) },
  { ...a11Cases[2], history: history(100, 75) },
  { ...a11Cases[3], history: history(99, null) },
  { ...a11Cases[4], history: history(50, 0) },
  { name: "unavailable-unknown-price", width: 1024, height: 900, mobile: false, series: "unavailable", history: history(null, null), required: ["Synthetic unavailable", "價格未知", "沒有券前 raw observation", "沒有券前每日代表價", "沒有已確認券後每日代表價"], forbidden: ["href=\"https://"] },
  { name: "unknown-coupon", width: 1024, height: 900, mobile: false, series: "unknown-coupon", history: history(99, null), required: ["Synthetic unknown-coupon", "優惠券條件未知", "券前商品價", "NT$ 99", "沒有已確認券後每日代表價"], forbidden: ["已確認券後商品價</span><strong>NT$ 49", "href=\"https://"] },
  { name: "claim-required-mobile", width: 390, height: 844, mobile: true, series: "claim-required", history: history(99, null), required: ["Synthetic claim-required", "需先領券，尚未確認", "可能券後價 NT$ 49 不會作為主價", "券前商品價", "NT$ 99"], forbidden: ["已確認券後商品價</span><strong>NT$ 49", "href=\"https://"] },
  a11Cases[5],
  a11Cases[6],
  { ...a11Cases[7], history: history(100, 75) }
];
const cases = a12 ? a12Cases : a11Cases;

let previewStarted = false, chromeProcess, cdp, chromeStderr = "";
const results = [], network = [], wireProbes = [];
try {
  const start = runControl("start"); previewStarted = true;
  if (start.status !== "READY") throw new Error(`Preview did not start: ${JSON.stringify(start)}`);
  await waitForJson(`http://127.0.0.1:${port}/__cdh/health`);
  if (a12) for (const item of cases.filter((candidate) => candidate.history && candidate.series)) {
    const response = await fetch(`http://127.0.0.1:${port}/cdh-coupon-v4/api/v4/products/${encodeURIComponent(item.series)}`);
    const detail = await response.json();
    wireProbes.push({ case: item.name, series: item.series, status: response.status, data_version: detail.data_version, history: {
      "before_coupon:raw": { prices: detail.history.before_coupon.map((entry) => entry.price_twd), dates: detail.history.before_coupon.map((entry) => entry.observed_at.slice(0, 10)), samples: [] },
      "confirmed_after_coupon:raw": { prices: detail.history.confirmed_after_coupon.map((entry) => entry.price_twd), dates: detail.history.confirmed_after_coupon.map((entry) => entry.observed_at.slice(0, 10)), samples: [] },
      "before_coupon:daily": { prices: detail.history_quality.before_coupon.daily_representatives.map((entry) => entry.representative_price_twd), dates: detail.history_quality.before_coupon.daily_representatives.map((entry) => entry.taipei_date), samples: detail.history_quality.before_coupon.daily_representatives.map((entry) => entry.sample_count) },
      "confirmed_after_coupon:daily": { prices: detail.history_quality.confirmed_after_coupon.daily_representatives.map((entry) => entry.representative_price_twd), dates: detail.history_quality.confirmed_after_coupon.daily_representatives.map((entry) => entry.taipei_date), samples: detail.history_quality.confirmed_after_coupon.daily_representatives.map((entry) => entry.sample_count) }
    }});
  }
  const chromeProfile = path.join(runtime, "chrome-profile");
  chromeProcess = spawn(chrome, ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${chromeProfile}`, "about:blank"], { cwd: previewRoot, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  chromeProcess.stderr.on("data", (data) => { chromeStderr += data.toString(); });
  let tabs;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (chromeProcess.exitCode !== null) throw new Error(`Chrome exited before CDP became ready: ${chromeProcess.exitCode}: ${chromeStderr}`);
    try { const response = await fetch(`http://127.0.0.1:${debugPort}/json`); if (response.ok) { tabs = await response.json(); break; } } catch { /* CDP startup */ }
    await wait(100);
  }
  if (!tabs) throw new Error(`Chrome CDP did not become ready: ${chromeStderr}`);
  const tab = tabs.find((item) => item.type === "page");
  if (!tab?.webSocketDebuggerUrl) throw new Error("Chrome page target unavailable");
  cdp = cdpClient(tab.webSocketDebuggerUrl); await cdp.opened;
  await cdp.send("Page.enable"); await cdp.send("Network.enable");
  cdp.on("Network.responseReceived", ({ response }) => { if (response.url.includes("/cdh-coupon-v4/")) network.push({ url: response.url, status: response.status, mimeType: response.mimeType }); });
  for (const item of cases) {
    const url = new URL(`http://127.0.0.1:${port}/`); url.searchParams.set("mode", "synthetic"); url.searchParams.set("contract", "v4");
    if (item.series) url.searchParams.set("series", item.series);
    if (item.query) url.searchParams.set("q", item.query);
    let pausedHandler;
    if (item.invalidResponse) {
      await cdp.send("Fetch.enable", { patterns: [{ urlPattern: `http://127.0.0.1:${port}/cdh-coupon-v4/*`, requestStage: "Request" }] });
      pausedHandler = async ({ requestId }) => { await cdp.send("Fetch.fulfillRequest", { requestId, responseCode: 200, responseHeaders: [{ name: "Content-Type", value: "application/json" }], body: Buffer.from('{"invalid":true}').toString("base64") }); };
      cdp.on("Fetch.requestPaused", pausedHandler);
    }
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: item.width, height: item.height, deviceScaleFactor: 1, mobile: item.mobile });
    const loaded = cdp.once("Page.loadEventFired"); await cdp.send("Page.navigate", { url: url.href }); await loaded; await wait(800);
    if (item.keyboardSearch) {
      await cdp.send("Runtime.evaluate", { expression: 'document.querySelector("#coupon-api-search")?.focus()' });
      await cdp.send("Input.insertText", { text: item.keyboardSearch });
      await cdp.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 }); await wait(800);
    }
    const evaluation = await cdp.send("Runtime.evaluate", { expression: "({html:document.documentElement.outerHTML,text:document.body.innerText,href:location.href,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,external:[...document.querySelectorAll('a[href]')].filter(a=>new URL(a.href).origin!==location.origin).length,disabledCta:document.querySelector('.coupon-cta button')?.disabled===true,history:[...document.querySelectorAll('[data-history-basis][data-history-granularity]')].map(s=>{const style=getComputedStyle(s);return{basis:s.dataset.historyBasis,granularity:s.dataset.historyGranularity,visible:style.display!=='none'&&style.visibility!=='hidden'&&style.opacity!=='0'&&s.getClientRects().length>0,prices:[...s.querySelectorAll('[data-price-twd],[data-representative-price-twd]')].map(r=>Number(r.dataset.priceTwd??r.dataset.representativePriceTwd)),dates:[...s.querySelectorAll('[data-observed-at],[data-taipei-date]')].map(r=>(r.dataset.observedAt??r.dataset.taipeiDate).slice(0,10)),samples:[...s.querySelectorAll('[data-sample-count]')].map(r=>Number(r.dataset.sampleCount))}})})", returnByValue: true });
    const value = evaluation.result.value, haystack = `${value.html}\n${value.text}`;
    const missing = item.required.filter((text) => !haystack.includes(text));
    const forbidden = item.forbidden.filter((text) => haystack.includes(text));
    const historyMismatches = [];
    const wireDomMismatches = [];
    if (item.history) {
      const actual = Object.fromEntries(value.history.map((entry) => [`${entry.basis}:${entry.granularity}`, entry]));
      for (const [key, expected] of Object.entries(item.history)) {
        const observed = actual[key];
        if (!observed) historyMismatches.push(`${key}:missing`);
        else {
          if (!observed.visible) historyMismatches.push(`${key}:not-visible`);
          for (const property of ["prices", "dates", "samples"]) if (JSON.stringify(observed[property]) !== JSON.stringify(expected[property] ?? [])) historyMismatches.push(`${key}:${property}:${JSON.stringify(observed[property])}!=${JSON.stringify(expected[property] ?? [])}`);
        }
      }
      if (Object.keys(actual).length !== 4) historyMismatches.push(`history-section-count:${Object.keys(actual).length}`);
      const wire = wireProbes.find((probe) => probe.series === item.series);
      if (wire) for (const key of Object.keys(item.history)) {
        const observed = actual[key], upstream = wire.history[key];
        for (const property of ["prices", "dates", "samples"]) if (JSON.stringify(observed?.[property] ?? []) !== JSON.stringify(upstream[property] ?? [])) wireDomMismatches.push(`${key}:${property}:dom=${JSON.stringify(observed?.[property] ?? [])}:wire=${JSON.stringify(upstream[property] ?? [])}`);
      }
    }
    const screenshot = path.join(screenshots, `${version.toLowerCase()}-${item.name}.png`);
    const captured = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: a12 && Boolean(item.history) }); await writeFile(screenshot, Buffer.from(captured.data, "base64"));
    const pass = missing.length === 0 && forbidden.length === 0 && historyMismatches.length === 0 && wireDomMismatches.length === 0 && value.external === 0 && (!item.history || value.disabledCta === true) && value.scrollWidth <= value.width;
    results.push({ case: item.name, url: url.href, url_after: value.href, viewport: `${item.width}x${item.height}`, missing, forbidden, history_asserted: Boolean(item.history), history_mismatches: historyMismatches, wire_dom_mismatches: wireDomMismatches, history_dom: value.history, cta_disabled: value.disabledCta, outbound_link_count: value.external, no_horizontal_overflow: value.scrollWidth <= value.width, screenshot: path.relative(projectRoot, screenshot).replaceAll("\\", "/"), pass });
    if (item.invalidResponse) await cdp.send("Fetch.disable");
  }
} finally {
  if (cdp) cdp.close();
  if (chromeProcess) chromeProcess.kill();
  if (previewStarted) { try { runControl("stop"); } catch (error) { results.push({ case: "cleanup", pass: false, error: String(error) }); } }
}

const actualApiResponses = network.filter((item) => item.status === 200);
const summary = { task_id: a12 ? "CDH-A12-LOCAL-PRICE-DAILY-DOM-AND-SAFE-IMPORT-PREVIEW-001" : "CDH-A11-WINDOWS-LOCAL-WEB-PREVIEW-001", exact_a11_release_sha256: "40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd", exact_b11_sha256: "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a", browser: chrome, isolated_profile: path.join(runtime, "chrome-profile"), chrome_stderr: chromeStderr.trim(), loopback_only: true, cases: results, daily_dom_case_count: results.filter((item)=>item.history_asserted).length, wire_probes: wireProbes, actual_api_network_responses: actualApiResponses, all_pass: results.length === cases.length && results.every((item) => item.pass) && actualApiResponses.length >= 2 };
await writeFile(path.join(evidence, `BROWSER_E2E_${version}.json`), `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ all_pass: summary.all_pass, cases: results.length, actual_api_network_responses: actualApiResponses.length }));
process.exitCode = summary.all_pass ? 0 : 1;
