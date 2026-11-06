import { spawn } from "node:child_process";
import http from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const toolRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(toolRoot, "../..");
const evidenceRoot = path.join(projectRoot, "review", "H06", "evidence");
const screenshotsRoot = path.join(evidenceRoot, "screenshots");
const runtimeRoot = path.join(projectRoot, "review", "H06", "runtime");
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const frontendPort = 4183;
const b11Port = 8776;
const chromePort = 9329;
await Promise.all([mkdir(evidenceRoot, { recursive: true }), mkdir(screenshotsRoot, { recursive: true }), mkdir(runtimeRoot, { recursive: true })]);

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function launch(command, args) {
  const child = spawn(command, args, { cwd: projectRoot, shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  const logs = { stdout: "", stderr: "" };
  child.stdout.on("data", (data) => { logs.stdout += data; });
  child.stderr.on("data", (data) => { logs.stderr += data; });
  return { child, logs };
}
async function ready(url, attempts = 160) {
  for (let i = 0; i < attempts; i += 1) {
    try { const response = await fetch(url); if (response.status < 500) return response; } catch { /* loopback not ready */ }
    await wait(100);
  }
  throw new Error(`loopback endpoint not ready: ${url}`);
}
async function stop(proc) {
  if (!proc || proc.exitCode !== null) return;
  proc.kill();
  await Promise.race([new Promise((resolve) => proc.once("close", resolve)), wait(2000)]);
}
function rawRequest(pathname, headers = {}) {
  return new Promise((resolve, reject) => {
    const request = http.request({ hostname: "127.0.0.1", port: b11Port, path: pathname, method: "GET", headers }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks).toString("utf8") }));
    });
    request.on("error", reject);
    request.end();
  });
}
function cdpClient(webSocketUrl) {
  const socket = new WebSocket(webSocketUrl);
  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const item = pending.get(message.id); pending.delete(message.id);
      message.error ? item.reject(new Error(message.error.message)) : item.resolve(message.result);
    } else for (const listener of listeners.get(message.method) ?? []) listener(message.params);
  };
  return {
    opened: new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; }),
    send(method, params = {}) { const id = nextId++; return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); }); },
    on(method, listener) { listeners.set(method, [...(listeners.get(method) ?? []), listener]); },
    close() { socket.close(); },
  };
}

let b11;
async function startB11(fixture) {
  b11 = launch("python", [path.join(toolRoot, "b11_exact_server.py"), "--fixture", fixture, "--port", String(b11Port), "--runtime-root", runtimeRoot]);
  await ready(`http://127.0.0.1:${b11Port}/api/v4/products?q=&page=1&limit=20`);
  return b11;
}
async function restartB11(fixture) {
  await stop(b11?.child);
  await wait(300);
  return startB11(fixture);
}

const proxy = launch(process.execPath, [path.join(toolRoot, "a10_exact_proxy_server.mjs"), String(frontendPort), String(b11Port)]);
const chromeProfile = path.join(runtimeRoot, `chrome-${process.pid}`);
const chrome = launch(chromePath, ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", `--remote-debugging-address=127.0.0.1`, `--remote-debugging-port=${chromePort}`, `--user-data-dir=${chromeProfile}`, "about:blank"]);

let client;
const network = new Map();
const consoleEvents = [];
const journeys = [];
const b11Runs = [];

async function evaluate(expression) {
  const result = await client.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}
async function waitForText(text, timeoutMs = 12000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(`document.body?.innerText.includes(${JSON.stringify(text)}) ?? false`)) return;
    await wait(100);
  }
  throw new Error(`text not found: ${text}`);
}
async function navigate(url) {
  await client.send("Page.navigate", { url });
}
async function capture(name, expected, forbidden = [], options = {}) {
  const selector = options.scopeSelector ?? null;
  const expectedDisabledCta = options.expectedDisabledCta ?? 1;
  const state = await evaluate(`(()=>{const scope=${selector ? `document.querySelector(${JSON.stringify(selector)})` : "document.body"};return {text:document.body.innerText,scopeText:scope?.innerText??'',html:document.documentElement.outerHTML,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,disabledCta:scope?.querySelectorAll('button.cta:disabled').length??0,outbound:scope?.querySelectorAll('a.cta[href]').length??0,activeId:document.activeElement?.id??''}})()`);
  const screenshot = await client.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  const screenshotRel = `review/H06/evidence/screenshots/${name}.png`;
  await writeFile(path.join(screenshotsRoot, `${name}.png`), Buffer.from(screenshot.data, "base64"));
  await writeFile(path.join(evidenceRoot, `${name}.dom.html`), state.html, "utf8");
  const missing = expected.filter((item) => !state.scopeText.includes(item));
  const forbiddenPresent = forbidden.filter((item) => state.scopeText.includes(item));
  const item = { name, url: await evaluate("location.href"), viewport: `${state.width}x${await evaluate("innerHeight")}`, scope_selector: selector, expected_missing: missing, forbidden_present: forbiddenPresent, expected_disabled_cta_count: expectedDisabledCta, disabled_cta_count: state.disabledCta, outbound_anchor_count: state.outbound, active_element_id: state.activeId, horizontal_overflow: state.scrollWidth > state.width, screenshot: screenshotRel, pass: missing.length === 0 && forbiddenPresent.length === 0 && state.disabledCta === expectedDisabledCta && state.outbound === 0 && state.scrollWidth <= state.width };
  journeys.push(item);
  return item;
}

try {
  await ready(`http://127.0.0.1:${frontendPort}/`);
  await startB11("active");

  const directSearchResponse = await fetch(`http://127.0.0.1:${b11Port}/api/v4/products?q=&page=1&limit=20`);
  const directSearch = await directSearchResponse.json();
  const details = {};
  for (const key of ["confirmed", "expired-coupon", "zero", "unavailable", "quantity-two", "wrong-sku"]) {
    const response = await fetch(`http://127.0.0.1:${b11Port}/api/v4/products/${key}`);
    details[key] = { status: response.status, body: await response.json() };
  }
  const missing = await rawRequest("/api/v4/products/not-found");
  const hostileHost = await rawRequest("/api/v4/products", { Host: "evil.example" });
  const hostileOrigin = await rawRequest("/api/v4/products", { Origin: "http://evil.example:9999" });
  const b11Http = { search: { status: directSearchResponse.status, body: directSearch }, details, missing: { status: missing.status, body: JSON.parse(missing.body) }, hostile_host: { status: hostileHost.status }, hostile_origin: { status: hostileOrigin.status } };
  await writeFile(path.join(evidenceRoot, "B11_ACTUAL_HTTP.json"), `${JSON.stringify(b11Http, null, 2)}\n`, "utf8");

  const tabs = await (await ready(`http://127.0.0.1:${chromePort}/json`)).json();
  const tab = tabs.find((item) => item.type === "page");
  client = cdpClient(tab.webSocketDebuggerUrl);
  await client.opened;
  await Promise.all([client.send("Page.enable"), client.send("Runtime.enable"), client.send("Network.enable")]);
  client.on("Network.requestWillBeSent", (event) => network.set(event.requestId, { url: event.request.url, method: event.request.method, type: event.type, initiator: event.initiator?.type }));
  client.on("Network.responseReceived", (event) => Object.assign(network.get(event.requestId) ?? {}, { status: event.response.status, response_headers: event.response.headers }));
  client.on("Runtime.consoleAPICalled", (event) => consoleEvents.push({ type: event.type, text: event.args.map((item) => item.value ?? item.description ?? "").join(" ") }));
  client.on("Runtime.exceptionThrown", (event) => consoleEvents.push({ type: "exception", text: event.exceptionDetails.text }));

  await client.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await navigate(`http://127.0.0.1:${frontendPort}/?mode=synthetic&contract=v4&series=confirmed`);
  await waitForText("Synthetic confirmed");
  await waitForText("已確認券後商品價歷史");
  await capture("a10-b11-confirmed-desktop", ["B10 WSGI · SYNTHETIC API", "Synthetic confirmed", "NT$ 49", "券前商品價歷史", "已確認券後商品價歷史", "SYN-SKU-CONFIRMED", "正式連結尚未核准"]);

  await evaluate(`document.querySelector('#coupon-api-search').focus(); document.querySelector('#coupon-api-search').select()`);
  for (const [key, code] of [["z", "KeyZ"], ["e", "KeyE"], ["r", "KeyR"], ["o", "KeyO"]]) {
    await client.send("Input.dispatchKeyEvent", { type: "keyDown", key, code, text: key, unmodifiedText: key, windowsVirtualKeyCode: key.toUpperCase().charCodeAt(0) });
    await client.send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: key.toUpperCase().charCodeAt(0) });
  }
  await client.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
  await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
  if (!(await evaluate(`document.activeElement?.textContent?.includes('查詢 V4 API') ?? false`))) throw new Error("keyboard Tab did not focus the V4 search button");
  await client.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await client.send("Input.dispatchKeyEvent", { type: "char", key: "Enter", code: "Enter", text: "\r", unmodifiedText: "\r", windowsVirtualKeyCode: 13 });
  await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await waitForText("已確認券後商品價為 NT$0，但不是零成本到手");
  if (!(await evaluate(`new URLSearchParams(location.search).get('q') === 'zero' && new URLSearchParams(location.search).get('series') === 'zero'`))) throw new Error("keyboard search did not select zero series");
  await capture("a10-b11-keyboard-search-zero", ["Synthetic zero", "NT$ 0", "不是零成本到手", "required_total_twd 維持 null"], ["免費到手"]);

  await client.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await navigate(`http://127.0.0.1:${frontendPort}/?mode=synthetic&contract=v4&series=unavailable`);
  await waitForText("Synthetic unavailable");
  await capture("a10-b11-unavailable-mobile", ["Synthetic unavailable", "價格未知", "SOURCE_PERMISSION_ACTIVE", "券前與已確認券後歷史皆無樣本", "未知值不會補成 NT$0"], ["NT$ 0"], { scopeSelector: ".coupon-detail" });

  await navigate(`http://127.0.0.1:${frontendPort}/?mode=synthetic&contract=v4&series=expired-coupon`);
  await waitForText("Synthetic expired-coupon");
  await capture("a10-b11-expired-mobile", ["Synthetic expired-coupon", "優惠券已過期", "NT$ 99", "沒有已確認券後 raw observation"], ["已確認券後商品價為 NT$49"], { scopeSelector: ".coupon-detail" });

  await fetch(`http://127.0.0.1:${frontendPort}/__h06_control?mode=delay`);
  await navigate(`http://127.0.0.1:${frontendPort}/?mode=synthetic&contract=v4&series=confirmed&fault=timeout`);
  await waitForText("本機 V4 API 逾時", 9000);
  await capture("a10-b11-timeout-mobile", ["V4 Search 失敗，未載入示範資料", "本機 V4 API 逾時", "重試 API"], [], { expectedDisabledCta: 0 });
  await fetch(`http://127.0.0.1:${frontendPort}/__h06_control?mode=normal`);
  await evaluate(`Array.from(document.querySelectorAll('button')).find((item)=>item.textContent.includes('重試 API'))?.click()`);
  await waitForText("Synthetic confirmed");
  await capture("a10-b11-timeout-recovery-mobile", ["Synthetic confirmed", "NT$ 49", "已確認券後商品價歷史"], ["V4 Search 失敗"]);

  const activeRun = b11;
  b11Runs.push({ fixture: "active", stdout: activeRun.logs.stdout.trim(), stderr: activeRun.logs.stderr.trim() });
  await restartB11("revoked-source");
  await client.send("Emulation.setDeviceMetricsOverride", { width: 1024, height: 900, deviceScaleFactor: 1, mobile: false });
  await navigate(`http://127.0.0.1:${frontendPort}/?mode=synthetic&contract=v4&series=source-state`);
  await waitForText("Synthetic source-state");
  await capture("a10-b11-revoked-source-desktop", ["Synthetic source-state", "來源權限失效", "價格未知", "REVOKED"], ["NT$ 0"], { scopeSelector: ".coupon-detail" });
  b11Runs.push({ fixture: "revoked-source", stdout: b11.logs.stdout.trim(), stderr: b11.logs.stderr.trim() });

  const entries = [...network.values()];
  const browserSearchRequests = entries.filter((item) => item.url.includes("/cdh-coupon-v4/api/v4/products?") || item.url.endsWith("/cdh-coupon-v4/api/v4/products"));
  const browserDetailRequests = entries.filter((item) => /\/cdh-coupon-v4\/api\/v4\/products\/[^?]+/.test(item.url));
  const external = entries.filter((item) => { try { const url = new URL(item.url); return ["http:", "https:"].includes(url.protocol) && url.hostname !== "127.0.0.1"; } catch { return false; } });
  const result = {
    task_id: "CDH-H06-A10-B11-ACTUAL-BROWSER-001",
    a10: { release: "review/releases/CDH_A_R07_001_REVIEW.zip", sha256: "eb4b449972f1bb6bccd9457e8ee88a2b3c69f2a2001b17fc5adfceb23c6a7e08", central_ack_state: "NOT_ACKNOWLEDGED_IN_R08_AUTHORITY", source: "manifest-verified release dist" },
    b11: { release: "review/releases/CDH_B_R07_001_REVIEW.zip", sha256: "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a", source: "separately extracted exact WSGI and hash-verified fixture copies" },
    browser_search_request_count: browserSearchRequests.length,
    browser_detail_request_count: browserDetailRequests.length,
    external_request_count: external.length,
    journeys,
    b11_runs: b11Runs,
    console_events: consoleEvents,
    evidence_result: journeys.every((item) => item.pass) && browserSearchRequests.length > 0 && browserDetailRequests.length > 0 && external.length === 0 ? "PASS_PROVISIONAL_EVIDENCE" : "FAIL",
    final_integration_gate: "PROVISIONAL_PASS_AWAITING_CENTRAL_A10_SHA_ACK",
  };
  await writeFile(path.join(evidenceRoot, "ACTUAL_A10_B11_BROWSER.json"), `${JSON.stringify(result, null, 2)}\n`, "utf8");
  await writeFile(path.join(evidenceRoot, "NETWORK_HAR.json"), `${JSON.stringify({ scope: "A10_4183_TO_B11_8776_LOOPBACK_ONLY", entries, external_request_count: external.length }, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ evidence_result: result.evidence_result, final_integration_gate: result.final_integration_gate, journeys: journeys.length, search_requests: browserSearchRequests.length, detail_requests: browserDetailRequests.length, external_requests: external.length }));
  process.exitCode = result.evidence_result === "PASS_PROVISIONAL_EVIDENCE" ? 0 : 1;
} catch (error) {
  let page = null;
  try {
    page = client ? await evaluate(`({url:location.href,text:document.body?.innerText ?? '',html:document.documentElement?.outerHTML ?? ''})`) : null;
    if (client) {
      const screenshot = await client.send("Page.captureScreenshot", { format: "png" });
      await writeFile(path.join(screenshotsRoot, "run-failure.png"), Buffer.from(screenshot.data, "base64"));
      if (page?.html) await writeFile(path.join(evidenceRoot, "run-failure.dom.html"), page.html, "utf8");
    }
  } catch { /* retain the original failure */ }
  await writeFile(path.join(evidenceRoot, "RUN_FAILURE.json"), `${JSON.stringify({ error: error.stack ?? String(error), page, console_events: consoleEvents, proxy_stdout: proxy.logs.stdout, proxy_stderr: proxy.logs.stderr, b11_stdout: b11?.logs.stdout ?? "", b11_stderr: b11?.logs.stderr ?? "", chrome_stdout: chrome.logs.stdout, chrome_stderr: chrome.logs.stderr, network: [...network.values()] }, null, 2)}\n`, "utf8");
  throw error;
} finally {
  if (client) client.close();
  await stop(chrome.child);
  await stop(proxy.child);
  await stop(b11?.child);
}
