import { createHash } from "node:crypto";
import { execFileSync, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const previewRoot = path.resolve(here, "..");
const projectRoot = path.resolve(previewRoot, "../../..");
const control = path.join(previewRoot, "control.py");
const python = process.env.CDH_TEST_PYTHON ?? "python";
const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 4201;
const debugPort = await new Promise((resolve, reject) => {
  const probe = net.createServer(); probe.once("error", reject);
  probe.listen(0, "127.0.0.1", () => { const address = probe.address(); if (!address || typeof address === "string") return reject(new Error("Unable to allocate CDP port")); const selected = address.port; probe.close((error) => error ? reject(error) : resolve(selected)); });
});
const reportRoot = path.join(projectRoot, "reports", "A15_REV2");
const evidenceRoot = path.join(reportRoot, "evidence");
const screenshotRoot = path.join(reportRoot, "screenshots");
const runId = new Date().toISOString().replaceAll(":", "").replaceAll(".", "");
const runRoot = path.join(reportRoot, "browser_runtime", runId);
const state = path.join(runRoot, "state");
const privateData = path.join(runRoot, "private_data");
const database = path.join(privateData, "private_user_observations.sqlite3");
const exampleRoot = path.join(projectRoot, "input", "crossline", "A15", "R12", "B16_REV3", "CDH_B_R12_003_REVIEW", "services", "private_batch_import_b16", "examples");
const validCsv = path.join(exampleRoot, "valid_two_day.csv");
const invalidCsv = path.join(exampleRoot, "invalid_row.json");
await Promise.all([mkdir(evidenceRoot, { recursive: true }), mkdir(screenshotRoot, { recursive: true }), mkdir(runRoot, { recursive: true })]);

const controlArgs = (action) => [control, action, "--project-root", projectRoot, "--port", String(port), "--state-dir", state, "--runtime-root", path.join(evidenceRoot, "runtime"), "--log-dir", path.join(evidenceRoot, "server_logs"), "--private-data-root", privateData, "--timeout", "20"];
const runControl = (action) => JSON.parse(execFileSync(python, controlArgs(action), { cwd: previewRoot, windowsHide: true, encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" } }).trim().split(/\r?\n/).at(-1));
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sha256 = async (file) => createHash("sha256").update(await readFile(file)).digest("hex");
const rowCount = () => Number(execFileSync(python, ["-c", "import sqlite3,sys; c=sqlite3.connect('file:'+sys.argv[1].replace('\\\\','/')+'?mode=ro',uri=True); print(c.execute('select count(*) from observations').fetchone()[0]); c.close()", database], { windowsHide: true, encoding: "utf8" }).trim());

async function waitForJson(url) { for (let index = 0; index < 120; index += 1) { try { const response = await fetch(url); if (response.ok) return response.json(); } catch { /* startup */ } await wait(100); } throw new Error(`Endpoint not ready: ${url}`); }
function cdpClient(url) {
  const socket = new WebSocket(url), pending = new Map(), listeners = new Map(); let next = 1;
  socket.addEventListener("message", (event) => { const message = JSON.parse(event.data); if (message.id && pending.has(message.id)) { const call = pending.get(message.id); pending.delete(message.id); message.error ? call.reject(new Error(message.error.message)) : call.resolve(message.result); return; } for (const callback of listeners.get(message.method) ?? []) callback(message.params); });
  return { opened: new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); }), send(method, params = {}) { const id = next++; return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); }); }, once(method) { return new Promise((resolve) => { const callback = (params) => { listeners.set(method, (listeners.get(method) ?? []).filter((item) => item !== callback)); resolve(params); }; listeners.set(method, [...(listeners.get(method) ?? []), callback]); }); }, on(method, callback) { listeners.set(method, [...(listeners.get(method) ?? []), callback]); }, close() { socket.close(); } };
}
async function pollExpression(cdp, expression, label) { for (let index = 0; index < 120; index += 1) { const result = (await cdp.send("Runtime.evaluate", { expression, returnByValue: true })).result.value; if (result) return result; await wait(100); } throw new Error(`Timed out waiting for ${label}`); }
async function setFile(cdp, file) {
  const document = await cdp.send("DOM.getDocument", { depth: -1, pierce: true });
  const input = await cdp.send("DOM.querySelector", { nodeId: document.root.nodeId, selector: "#batch-import-file" });
  if (!input.nodeId) throw new Error("A15 file input not found");
  await cdp.send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [] });
  await cdp.send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [file] });
  await cdp.send("Runtime.evaluate", { expression: `document.querySelector('#batch-import-file').dispatchEvent(new Event('change',{bubbles:true}))` });
}
async function clickText(cdp, text) { await cdp.send("Runtime.evaluate", { expression: `(() => { const button=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()===${JSON.stringify(text)}); if(!button||button.disabled)return false; button.click(); return true; })()` }); }

let started = false, chromeProcess, cdp, chromeStderr = "";
const requests = new Map(), network = [];
try {
  const firstStart = runControl("start"); started = true;
  if (firstStart.status !== "READY" || firstStart.b16_r12_sha256 !== "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7") throw new Error(`First start failed: ${JSON.stringify(firstStart)}`);
  const firstHealth = await waitForJson(`http://127.0.0.1:${port}/__cdh/health`);
  if (firstHealth.b16_r12_sha256 !== firstStart.b16_r12_sha256 || firstHealth.b16_revision !== "REV3") throw new Error("Health B16 REV3 identity mismatch");

  chromeProcess = spawn(chrome, ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", "--remote-debugging-address=127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(runRoot, "chrome-profile")}`, "about:blank"], { cwd: previewRoot, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  chromeProcess.stderr.on("data", (data) => { chromeStderr += data.toString(); });
  let tabs; for (let index = 0; index < 120; index += 1) { try { const response = await fetch(`http://127.0.0.1:${debugPort}/json`); if (response.ok) { tabs = await response.json(); break; } } catch { /* CDP startup */ } await wait(100); }
  const tab = tabs?.find((item) => item.type === "page"); if (!tab?.webSocketDebuggerUrl) throw new Error(`Chrome CDP unavailable: ${chromeStderr}`);
  cdp = cdpClient(tab.webSocketDebuggerUrl); await cdp.opened; await cdp.send("Page.enable"); await cdp.send("DOM.enable"); await cdp.send("Network.enable");
  cdp.on("Network.requestWillBeSent", ({ requestId, request }) => { requests.set(requestId, { url: request.url, method: request.method }); });
  cdp.on("Network.responseReceived", ({ requestId, response }) => { const request = requests.get(requestId); if (request) network.push({ ...request, status: response.status }); });
  const loaded = cdp.once("Page.loadEventFired"); await cdp.send("Page.navigate", { url: `http://127.0.0.1:${port}/?mode=synthetic&contract=v4` }); await loaded;
  await pollExpression(cdp, `document.querySelector('#batch-import-file') !== null`, "A15 file input");

  await setFile(cdp, invalidCsv);
  await pollExpression(cdp, `document.querySelector('[aria-label="批次匯入本機預覽表格"]')?.innerText.includes('invalid_row.json') && [...document.querySelectorAll('button')].some(x=>x.textContent.trim()==='送往 B16 安全預覽'&&!x.disabled)`, "invalid local preview");
  await clickText(cdp, "送往 B16 安全預覽");
  await pollExpression(cdp, `document.querySelector('[aria-label="B16 伺服器批次預覽"]')?.innerText.includes('PREVIEW_REJECTED')`, "B16 422 rejection");
  const invalidDom = (await cdp.send("Runtime.evaluate", { expression: `(() => { const root=document.querySelector('[aria-label="B16 伺服器批次預覽"]'); return {text:root.innerText,confirm_present:[...root.querySelectorAll('button')].some(x=>x.textContent.includes('明確確認'))}; })()`, returnByValue: true })).result.value;
  if (existsSync(database)) throw new Error("Rejected preview created a database");

  await setFile(cdp, validCsv);
  await pollExpression(cdp, `document.querySelector('[aria-label="批次匯入本機預覽表格"]')?.innerText.includes('valid_two_day.csv') && document.querySelector('[aria-label="批次匯入本機預覽表格"]')?.innerText.includes('2 筆') && [...document.querySelectorAll('button')].some(x=>x.textContent.trim()==='送往 B16 安全預覽'&&!x.disabled)`, "valid local preview");
  await clickText(cdp, "送往 B16 安全預覽");
  await pollExpression(cdp, `document.querySelector('[aria-label="B16 伺服器批次預覽"]')?.innerText.includes('PREVIEW_READY_NO_DATABASE_WRITE')`, "B16 ready preview");
  if (existsSync(database)) throw new Error("Ready preview created a database");
  await cdp.send("Runtime.evaluate", { expression: `document.querySelector('[aria-label="B16 伺服器批次預覽"] input[type=checkbox]').click()` });
  await clickText(cdp, "明確確認並保存");
  await pollExpression(cdp, `document.querySelector('[aria-label="B16 批次保存結果"]')?.innerText.includes('新批次已保存')`, "HTTP 201 commit");
  const rowsAfterCreate = rowCount();

  await setFile(cdp, validCsv);
  await pollExpression(cdp, `document.querySelector('[aria-label="批次匯入本機預覽表格"]')?.innerText.includes('valid_two_day.csv') && document.querySelector('[aria-label="B16 伺服器批次預覽"]')===null && [...document.querySelectorAll('button')].some(x=>x.textContent.trim()==='送往 B16 安全預覽'&&!x.disabled)`, "replay local preview");
  await clickText(cdp, "送往 B16 安全預覽");
  await pollExpression(cdp, `document.querySelector('[aria-label="B16 伺服器批次預覽"]')?.innerText.includes('PREVIEW_READY_NO_DATABASE_WRITE')`, "replay B16 preview");
  await cdp.send("Runtime.evaluate", { expression: `document.querySelector('[aria-label="B16 伺服器批次預覽"] input[type=checkbox]').click()` });
  await clickText(cdp, "明確確認並保存");
  await pollExpression(cdp, `document.querySelector('[aria-label="B16 批次保存結果"]')?.innerText.includes('冪等重播，沒有新增資料')`, "HTTP 200 replay");
  const rowsAfterReplay = rowCount();
  const importScreenshot = path.join(screenshotRoot, "a15-b16-import-and-replay.png");
  await writeFile(importScreenshot, Buffer.from((await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true })).data, "base64"));

  const firstStop = runControl("stop"); started = false; if (firstStop.status !== "STOPPED") throw new Error("First stop failed");
  const databaseShaBeforeRead = await sha256(database), rowsBeforeRead = rowCount();
  const secondStart = runControl("start"); started = true; if (secondStart.status !== "READY") throw new Error("Second start failed");
  const secondHealth = await waitForJson(`http://127.0.0.1:${port}/__cdh/health`); if (firstHealth.instance_id === secondHealth.instance_id) throw new Error("Website did not restart");
  const loadedAgain = cdp.once("Page.loadEventFired"); await cdp.send("Page.reload", { ignoreCache: true }); await loadedAgain;
  await pollExpression(cdp, `document.querySelector('#private-history-query') !== null`, "private search after restart");
  await cdp.send("Runtime.evaluate", { expression: `(() => { const input=document.querySelector('#private-history-query'); const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; setter.call(input,'PROD-B16-CSV'); input.dispatchEvent(new Event('input',{bubbles:true})); [...document.querySelectorAll('button')].find(x=>x.textContent==='搜尋私人紀錄').click(); })()` });
  await pollExpression(cdp, `document.querySelectorAll('.private-history-browser .private-product-card').length === 1`, "private result after restart");
  await cdp.send("Runtime.evaluate", { expression: `document.querySelector('.private-history-browser .private-product-card').click()` });
  await pollExpression(cdp, `document.querySelector('[data-private-history-container=true] h3')?.textContent === 'Synthetic CSV product'`, "imported private detail");
  const dom = (await cdp.send("Runtime.evaluate", { expression: `(() => { const root=document.querySelector('[data-private-history-container=true]'); const values=(basis,granularity,field)=>[...root.querySelectorAll('[data-private-history-basis='+basis+'] [data-history-granularity='+granularity+'] .history-row')].map(x=>x.dataset[field]); return {before_raw:values('before_coupon','raw','priceTwd'),before_daily:values('before_coupon','daily','taipeiDate'),reported_raw:values('user_reported_after_coupon','raw','priceTwd'),confirmed_raw:values('confirmed_after_coupon','raw','priceTwd'),private_label:root.innerText.includes('PRIVATE_LOCAL_USER_ENTERED'),not_verified:root.innerText.includes('NOT PLATFORM VERIFIED'),confirmed_empty:root.querySelector('[data-private-history-basis=confirmed_after_coupon]')?.innerText.includes('沒有資料；不以零元或其他軌跡補值。')??false,cta_disabled:root.querySelector('button.cta')?.disabled===true,external_links:[...root.querySelectorAll('a[href]')].filter(a=>new URL(a.href).origin!==location.origin).length}; })()`, returnByValue: true })).result.value;
  const historyScreenshot = path.join(screenshotRoot, "a15-history-after-restart.png");
  await writeFile(historyScreenshot, Buffer.from((await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true })).data, "base64"));
  const databaseShaAfterRead = await sha256(database), rowsAfterRead = rowCount();
  const localOrigins = [`http://127.0.0.1:${port}/`, `http://localhost:${port}/`];
  const externalNetwork = network.filter((entry) => !localOrigins.some((origin) => entry.url.startsWith(origin)) && !entry.url.startsWith("data:") && !entry.url.startsWith("about:"));
  const b16Statuses = network.filter((entry) => entry.url.includes("/batch-")).map((entry) => ({ method: entry.method, path: new URL(entry.url).pathname, status: entry.status }));
  const allPass = !invalidDom.confirm_present && invalidDom.text.includes("逐筆驗證失敗") && rowsAfterCreate === 2 && rowsAfterReplay === 2 && rowsBeforeRead === 2 && rowsAfterRead === 2 && databaseShaBeforeRead === databaseShaAfterRead && dom.before_raw.join(",") === "1000,950" && dom.before_daily.join(",") === "2026-11-03,2026-11-04" && dom.reported_raw.join(",") === "900" && dom.confirmed_raw.length === 0 && dom.private_label && dom.not_verified && dom.confirmed_empty && dom.cta_disabled && dom.external_links === 0 && externalNetwork.length === 0 && b16Statuses.some((item) => item.status === 422) && b16Statuses.some((item) => item.status === 201) && b16Statuses.some((item) => item.status === 200 && item.path.endsWith("batch-confirm"));
  const result = { schema_version: "CDH-A15-REV2-BROWSER-E2E-1", task_id: "CDH-A15-BATCH-IMPORT-UI-001", revision: "REV2", created_at_utc: new Date().toISOString(), exact_dependencies: { a15_original_sha256: "5cc44dedd910ff9b2055cfc2772ad0c3d6db627ffc818794f81fd3d9b5552d4b", b16_rev3_sha256: firstStart.b16_r12_sha256 }, integration: "ACTUAL_A15_REV2_UI_TO_B16_REV3_LOCAL_API", chrome_exit_code: null, chrome_exit_signal: null, isolated_private_data_root: privateData, website_restart_count: 1, first_instance_id: firstHealth.instance_id, second_instance_id: secondHealth.instance_id, rejected_preview_database_created: false, rows_after_create: rowsAfterCreate, rows_after_replay: rowsAfterReplay, rows_before_read: rowsBeforeRead, rows_after_read: rowsAfterRead, database_sha256_before_read: databaseShaBeforeRead, database_sha256_after_read: databaseShaAfterRead, database_unchanged_by_read: databaseShaBeforeRead === databaseShaAfterRead, external_request_count: externalNetwork.length, formal_database_write_count: 0, registry_action_count: 0, firefox_action_count: 0, invalid_dom: invalidDom, dom, b16_http: b16Statuses, screenshots: [path.relative(projectRoot, importScreenshot).replaceAll("\\", "/"), path.relative(projectRoot, historyScreenshot).replaceAll("\\", "/")], all_pass: allPass };
  const chromeExit = new Promise((resolve) => chromeProcess.once("exit", (code, signal) => resolve([code, signal]))); await cdp.send("Browser.close"); cdp = undefined; const [exitCode, exitSignal] = await chromeExit; chromeProcess = undefined; result.chrome_exit_code = exitCode; result.chrome_exit_signal = exitSignal;
  const secondStop = runControl("stop"); started = false; if (secondStop.status !== "STOPPED") throw new Error("Second stop failed");
  await writeFile(path.join(evidenceRoot, "BROWSER_E2E_A15.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ all_pass: allPass, chrome_exit_code: exitCode, rows: rowsAfterRead, database_unchanged_by_read: result.database_unchanged_by_read, b16_http: b16Statuses, integration: result.integration }));
  if (!allPass) process.exitCode = 1;
} finally {
  if (cdp) cdp.close();
  if (chromeProcess) chromeProcess.kill();
  if (started) try { runControl("stop"); } catch { /* preserve evidence */ }
}
