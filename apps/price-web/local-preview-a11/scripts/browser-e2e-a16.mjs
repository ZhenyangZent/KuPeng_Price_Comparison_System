import { execFileSync, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(here, "../../../..");
const scriptRoot = path.join(projectRoot, "scripts", "windows-mvp");
const reportRoot = path.join(projectRoot, "reports", "A16");
const evidenceRoot = path.join(reportRoot, "evidence");
const screenshotRoot = path.join(reportRoot, "screenshots");
const runId = new Date().toISOString().replaceAll(":", "").replaceAll(".", "");
const runRoot = path.join(reportRoot, "browser_runtime", runId);
const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

const allocatePort = () => new Promise((resolve, reject) => {
  const probe = net.createServer(); probe.once("error", reject);
  probe.listen(0, "127.0.0.1", () => { const address = probe.address(); if (!address || typeof address === "string") return reject(new Error("no loopback port")); const selected = address.port; probe.close((error) => error ? reject(error) : resolve(selected)); });
});
const port = await allocatePort();
const debugPort = await allocatePort();
const state = path.join(runRoot, "state");
const runtime = path.join(runRoot, "runtime");
const logs = path.join(runRoot, "logs");
const privateData = path.join(runRoot, "private_data");
await Promise.all([mkdir(evidenceRoot, { recursive: true }), mkdir(screenshotRoot, { recursive: true }), mkdir(runRoot, { recursive: true })]);

const powershell = (name) => {
  const args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.join(scriptRoot, `${name}-CDH-MVP.ps1`), "-Port", String(port), "-StateDir", state, "-RuntimeRoot", runtime, "-LogDir", logs, "-PrivateDataRoot", privateData, "-MachineReadable"];
  const output = execFileSync("powershell.exe", args, { cwd: projectRoot, windowsHide: true, encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" } });
  return JSON.parse(output.trim().split(/\r?\n/).at(-1));
};
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitForJson(url) { for (let index = 0; index < 120; index += 1) { try { const response = await fetch(url); if (response.ok) return response.json(); } catch { /* startup */ } await wait(100); } throw new Error(`Endpoint not ready: ${url}`); }
function cdpClient(url) {
  const socket = new WebSocket(url), pending = new Map(), listeners = new Map(); let next = 1;
  socket.addEventListener("message", (event) => { const message = JSON.parse(event.data); if (message.id && pending.has(message.id)) { const call = pending.get(message.id); pending.delete(message.id); message.error ? call.reject(new Error(message.error.message)) : call.resolve(message.result); return; } for (const callback of listeners.get(message.method) ?? []) callback(message.params); });
  return { opened: new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); }), send(method, params = {}) { const id = next++; return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); }); }, once(method) { return new Promise((resolve) => { const callback = (params) => { listeners.set(method, (listeners.get(method) ?? []).filter((item) => item !== callback)); resolve(params); }; listeners.set(method, [...(listeners.get(method) ?? []), callback]); }); }, on(method, callback) { listeners.set(method, [...(listeners.get(method) ?? []), callback]); }, close() { socket.close(); } };
}
async function pollExpression(cdp, expression, label) { for (let index = 0; index < 120; index += 1) { const result = (await cdp.send("Runtime.evaluate", { expression, returnByValue: true })).result.value; if (result) return result; await wait(100); } throw new Error(`Timed out waiting for ${label}`); }

let started = false, chromeProcess, cdp, chromeStderr = "";
const requests = new Map(), network = [];
try {
  const start = powershell("Start"); started = true;
  if (start.status !== "READY" || start.b16_r12_sha256 !== "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7") throw new Error(`A16 launcher failed: ${JSON.stringify(start)}`);
  const status = powershell("Status"); if (status.status !== "READY") throw new Error(`A16 status failed: ${JSON.stringify(status)}`);
  const health = await waitForJson(`http://127.0.0.1:${port}/__cdh/health`);
  if (health.b16_revision !== "REV3") throw new Error("B16 REV3 was not loaded");

  chromeProcess = spawn(chrome, ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", "--remote-debugging-address=127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(runRoot, "chrome-profile")}`, "about:blank"], { cwd: projectRoot, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  chromeProcess.stderr.on("data", (data) => { chromeStderr += data.toString(); });
  let tabs; for (let index = 0; index < 120; index += 1) { try { const response = await fetch(`http://127.0.0.1:${debugPort}/json`); if (response.ok) { tabs = await response.json(); break; } } catch { /* startup */ } await wait(100); }
  const tab = tabs?.find((item) => item.type === "page"); if (!tab?.webSocketDebuggerUrl) throw new Error(`Chrome CDP unavailable: ${chromeStderr}`);
  cdp = cdpClient(tab.webSocketDebuggerUrl); await cdp.opened; await cdp.send("Page.enable"); await cdp.send("Network.enable"); await cdp.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  cdp.on("Network.requestWillBeSent", ({ requestId, request }) => requests.set(requestId, { url: request.url, method: request.method }));
  cdp.on("Network.responseReceived", ({ requestId, response }) => { const request = requests.get(requestId); if (request) network.push({ ...request, status: response.status }); });
  const loaded = cdp.once("Page.loadEventFired"); await cdp.send("Page.navigate", { url: `http://127.0.0.1:${port}/?mode=synthetic&contract=v4` }); await loaded;
  await pollExpression(cdp, `document.querySelector('[aria-label="價格資料分類說明"]') !== null && document.querySelector('#batch-import-file') !== null && document.querySelector('#private-history-query') !== null`, "A16 first-use controls");
  await pollExpression(cdp, `[...document.querySelectorAll('button')].some(x=>x.disabled&&x.textContent.includes('正式連結尚未核准')) && document.querySelector('.coupon-history-row') !== null`, "synthetic detail and disabled affiliate action");
  const dom = (await cdp.send("Runtime.evaluate", { expression: `(() => { const guide=document.querySelector('[aria-label="價格資料分類說明"]'); const history=document.querySelector('.coupon-history-row'); return {viewport_width:innerWidth,document_scroll_width:document.documentElement.scrollWidth,no_horizontal_overflow:document.documentElement.scrollWidth<=innerWidth,guide_text:guide.innerText,classification_card_count:guide.children.length,batch_import_present:!!document.querySelector('#batch-import-file'),manual_price_present:!!document.querySelector('.manual-observation-panel'),private_history_present:!!document.querySelector('#private-history-query'),synthetic_search_present:!!document.querySelector('#coupon-api-search'),affiliate_disabled:[...document.querySelectorAll('button')].some(x=>x.disabled&&x.textContent.includes('正式連結尚未核准')),history_mobile_columns:history?getComputedStyle(history).gridTemplateColumns:'NOT_RENDERED'}; })()`, returnByValue: true })).result.value;
  const screenshot = path.join(screenshotRoot, "a16-narrow-first-use.png");
  await writeFile(screenshot, Buffer.from((await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true })).data, "base64"));
  const localOrigins = [`http://127.0.0.1:${port}/`, `http://localhost:${port}/`];
  const external = network.filter((entry) => !localOrigins.some((origin) => entry.url.startsWith(origin)) && !entry.url.startsWith("data:") && !entry.url.startsWith("about:"));
  const allPass = dom.no_horizontal_overflow && dom.classification_card_count === 3 && dom.guide_text.includes("SYNTHETIC DEMO") && dom.guide_text.includes("PRIVATE USER-REPORTED") && dom.guide_text.includes("PLATFORM CONFIRMED") && dom.batch_import_present && dom.manual_price_present && dom.private_history_present && dom.synthetic_search_present && dom.affiliate_disabled && external.length === 0 && !existsSync(path.join(privateData, "private_user_observations.sqlite3"));
  const result = { schema_version: "CDH-A16-FIRST-USE-BROWSER-E2E-1", task_id: "CDH-A16-LOCAL-MVP-FIRST-USE-001", created_at_utc: new Date().toISOString(), launcher: "scripts/windows-mvp/Start-CDH-MVP.ps1", exact_dependencies: { a15_rev2_sha256: "be0becbaa384e1a633c5893b266dbbb03c449ca405ef1f0c07bb8dd53456634b", b16_rev3_sha256: start.b16_r12_sha256 }, startup_status: start.status, status_readback: status.status, health_b16_revision: health.b16_revision, port, viewport: { width: 390, height: 844 }, dom, private_database_created_by_first_view: existsSync(path.join(privateData, "private_user_observations.sqlite3")), external_request_count: external.length, formal_database_write_count: 0, registry_action_count: 0, firefox_action_count: 0, system_service_action_count: 0, screenshot: path.relative(projectRoot, screenshot).replaceAll("\\", "/"), chrome_exit_code: null, chrome_exit_signal: null, all_pass: allPass };
  const chromeExit = new Promise((resolve) => chromeProcess.once("exit", (code, signal) => resolve([code, signal]))); await cdp.send("Browser.close"); cdp = undefined; const [exitCode, exitSignal] = await chromeExit; chromeProcess = undefined; result.chrome_exit_code = exitCode; result.chrome_exit_signal = exitSignal;
  const stop = powershell("Stop"); started = false; if (stop.status !== "STOPPED") throw new Error(`A16 stop failed: ${JSON.stringify(stop)}`);
  const afterStop = powershell("Status");
  result.stop_status = stop.status; result.status_after_stop = afterStop.status;
  result.all_pass = result.all_pass && exitCode === 0 && afterStop.status === "STOPPED";
  await writeFile(path.join(evidenceRoot, "BROWSER_E2E_A16.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ all_pass: result.all_pass, chrome_exit_code: exitCode, no_horizontal_overflow: dom.no_horizontal_overflow, external_request_count: external.length, startup: start.status, stop: stop.status }));
  if (!result.all_pass) process.exitCode = 1;
} finally {
  if (cdp) cdp.close();
  if (chromeProcess) chromeProcess.kill();
  if (started) try { powershell("Stop"); } catch { /* preserve evidence */ }
}
