import { createHash } from "node:crypto";
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const tools = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(tools, "../..");
const h13 = path.join(root, "review", "H13");
const runtime = path.join(h13, "runtime");
const project = path.join(runtime, "project");
const bundle = path.join(project, "apps", "price-web", "local-trial-a17");
const evidence = path.join(h13, "evidence");
const screenshots = path.join(evidence, "screenshots");
const domRoot = path.join(evidence, "dom");
const database = path.join(project, "data", "A17_private_history", "private_user_observations.sqlite3");
const examples = path.join(bundle, "vendor", "b16", "private_batch_import_b16", "examples");
const validCsv = path.join(examples, "valid_two_day.csv");
const validJson = path.join(examples, "valid_two_day.json");
const python = "C:\\Users\\zheny\\AppData\\Local\\Programs\\Python\\Python313\\python.exe";
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 12341;
const expected = {
  a17: "5de6b85e72767e8135b7ff0e6e3acb534965d5f636f61eea918cb082b02a8237",
  runtimeManifest: "b75814678c51490cfcb00e60b80f46e7c22e40af95118796bae1f856a6f1a176",
  b11: "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
  b15: "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
  b16: "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
};
await Promise.all([mkdir(evidence, { recursive: true }), mkdir(screenshots, { recursive: true }), mkdir(domRoot, { recursive: true })]);

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sha256 = async (file) => createHash("sha256").update(await readFile(file)).digest("hex");
const rowCount = () => Number(execFileSync(python, ["-c", "import pathlib,sqlite3,sys;u=pathlib.Path(sys.argv[1]).resolve().as_uri()+'?mode=ro';c=sqlite3.connect(u,uri=True);print(c.execute('select count(*) from observations').fetchone()[0]);c.close()", database], { windowsHide: true, encoding: "utf8" }).trim());
const launcherReceipts = [];
const runControl = (action) => {
  const cmd = path.join(project, `${action[0].toUpperCase()}${action.slice(1)}-CDH-Trial.cmd`);
  const executed = spawnSync("cmd.exe", ["/d", "/c", `call ${path.basename(cmd)} -Port ${port} -MachineReadable`], {
    cwd: project, windowsHide: true, encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" }, timeout: 45000,
  });
  const output = `${executed.stdout ?? ""}\n${executed.stderr ?? ""}`;
  const line = output.split(/\r?\n/).map((value) => value.trim()).reverse().find((value) => value.startsWith("{") && value.endsWith("}"));
  const payload = line ? JSON.parse(line) : { status: "FAILED", error: output.trim() };
  launcherReceipts.push({ action, entry: path.basename(cmd), exit_code: executed.status, signal: executed.signal, payload, stdout: executed.stdout ?? "", stderr: executed.stderr ?? "" });
  if (executed.error || executed.status !== 0) throw new Error(`${action} launcher failed: ${executed.error?.message ?? output}`);
  return payload;
};
const debugPort = await new Promise((resolve, reject) => {
  const probe = net.createServer(); probe.once("error", reject);
  probe.listen(0, "127.0.0.1", () => { const address = probe.address(); if (!address || typeof address === "string") return reject(new Error("unable to allocate CDP port")); probe.close((error) => error ? reject(error) : resolve(address.port)); });
});
async function waitForJson(url) { for (let index = 0; index < 200; index += 1) { try { const response = await fetch(url); if (response.ok) return response.json(); } catch { /* startup */ } await wait(100); } throw new Error(`endpoint not ready: ${url}`); }
function cdpClient(url) {
  const socket = new WebSocket(url), pending = new Map(), listeners = new Map(); let next = 1;
  socket.addEventListener("message", (event) => { const message = JSON.parse(event.data); if (message.id && pending.has(message.id)) { const call = pending.get(message.id); pending.delete(message.id); message.error ? call.reject(new Error(message.error.message)) : call.resolve(message.result); return; } for (const callback of listeners.get(message.method) ?? []) callback(message.params); });
  return {
    opened: new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); }),
    send(method, params = {}) { const id = next++; return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); }); },
    once(method) { return new Promise((resolve) => { const callback = (params) => { listeners.set(method, (listeners.get(method) ?? []).filter((item) => item !== callback)); resolve(params); }; listeners.set(method, [...(listeners.get(method) ?? []), callback]); }); },
    on(method, callback) { listeners.set(method, [...(listeners.get(method) ?? []), callback]); }, close() { socket.close(); },
  };
}
let client;
async function evaluate(expression) { const response = await client.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text); return response.result.value; }
async function poll(expression, label, limit = 180) { for (let index = 0; index < limit; index += 1) { if (await evaluate(expression)) return; await wait(100); } throw new Error(`timed out waiting for ${label}`); }
async function setFile(file) { const document = await client.send("DOM.getDocument", { depth: -1, pierce: true }); const input = await client.send("DOM.querySelector", { nodeId: document.root.nodeId, selector: "#batch-import-file" }); if (!input.nodeId) throw new Error("batch input missing"); await client.send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [] }); await client.send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [file] }); await evaluate(`document.querySelector('#batch-import-file').dispatchEvent(new Event('change',{bubbles:true}))`); }
async function clickText(text, scope = "document") { const clicked = await evaluate(`(() => { const root=${scope};const button=[...root.querySelectorAll('button')].find(x=>x.textContent.trim()===${JSON.stringify(text)});if(!button||button.disabled)return false;button.click();return true;})()`); if (!clicked) throw new Error(`button unavailable: ${text}`); }
const captures = [];
async function capture(name) { const page = await evaluate(`({url:location.href,html:document.documentElement.outerHTML,width:innerWidth,scrollWidth:document.documentElement.scrollWidth})`); const shot = await client.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }); const screenshot = path.join(screenshots, `${name}.png`), dom = path.join(domRoot, `${name}.html`); await writeFile(screenshot, Buffer.from(shot.data, "base64")); await writeFile(dom, page.html, "utf8"); captures.push({ name, url: page.url, viewport_width: page.width, document_scroll_width: page.scrollWidth, horizontal_overflow: page.scrollWidth > page.width, screenshot: path.relative(root, screenshot).replaceAll("\\", "/"), dom: path.relative(root, dom).replaceAll("\\", "/") }); }
async function searchSynthetic() { await evaluate(`(()=>{const i=document.querySelector('#coupon-api-search'),s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(i,'already-included');i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));i.closest('form').requestSubmit();})()`); await poll(`document.querySelectorAll('.results-panel .product-card').length===1&&document.querySelector('.coupon-detail h2')?.textContent==='Synthetic already-included'`, "synthetic product search"); return evaluate(`({result:document.querySelector('.results-panel .product-card')?.innerText,detail:document.querySelector('.coupon-detail')?.innerText,affiliate_disabled:document.querySelector('.affiliate-card button.cta')?.disabled===true})`); }
async function openManualForm() { const form = await evaluate(`document.querySelector('.manual-observation-form')!==null`); if (!form) await clickText("開始輸入"); await poll(`document.querySelector('.manual-observation-form')!==null`, "manual form"); }
async function manualPreview(values) { await evaluate(`(()=>{const set=(label,value)=>{const n=[...document.querySelectorAll('.manual-observation-form label')].find(x=>x.textContent.startsWith(label))?.querySelector('input,select');if(!n)throw new Error('missing '+label);const p=n instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(p,'value').set.call(n,String(value));n.dispatchEvent(new Event('input',{bubbles:true}));n.dispatchEvent(new Event('change',{bubbles:true}));};set('商品名稱',${JSON.stringify(values.title)});set('商品 ID',${JSON.stringify(values.product)});set('SKU／變體 ID',${JSON.stringify(values.sku)});set('賣家 ID',${JSON.stringify(values.seller)});set('規格簽章',${JSON.stringify(values.package)});set('觀測時間（含時區）',${JSON.stringify(values.observed)});set('數量',1);set('券前價格（TWD）',1200);set('使用者自報券後價',1000);set('來源說明',${JSON.stringify(values.source)});document.querySelector('.manual-observation-form').requestSubmit();})()`); await poll(`document.querySelector('.manual-preview')?.innerText.includes('確認即將保存的資料')??false`, "manual preview"); return evaluate(`({text:document.querySelector('.manual-preview').innerText,write_count:[...document.querySelectorAll('.manual-preview span')].find(x=>x.textContent.includes('寫入次數'))?.textContent,confirmed:[...document.querySelectorAll('.manual-preview dt')].find(x=>x.textContent==='已確認券後價')?.nextElementSibling?.textContent})`); }
async function manualConfirm() { await evaluate(`document.querySelector('.manual-preview .explicit-confirm input').click();document.querySelector('.manual-preview .confirm-save').click()`); await poll(`document.querySelector('.manual-save-result')?.innerText.includes('已保存')??false`, "manual confirmation"); return evaluate(`document.querySelector('.manual-save-result').innerText`); }
async function selectAndPreview(file, filename) { await setFile(file); await poll(`document.querySelector('[aria-label="批次匯入本機預覽表格"]')?.innerText.includes(${JSON.stringify(filename)})&&[...document.querySelectorAll('.batch-preview button')].some(x=>x.textContent.trim()==='送往 B16 安全預覽'&&!x.disabled)`, `${filename} local preview`); await clickText("送往 B16 安全預覽", "document.querySelector('.batch-preview')"); await poll(`document.querySelector('[aria-label="B16 伺服器批次預覽"]')?.innerText.includes('PREVIEW_READY_NO_DATABASE_WRITE')`, `${filename} server preview`); return evaluate(`({text:document.querySelector('[aria-label="B16 伺服器批次預覽"]').innerText,rows:document.querySelectorAll('[aria-label="B16 伺服器批次預覽"] tbody tr').length})`); }
async function batchConfirm(expectedText) { await evaluate(`document.querySelector('[aria-label="B16 伺服器批次預覽"] .explicit-confirm input').click()`); await clickText("明確確認並保存", "document.querySelector('[aria-label=\"B16 伺服器批次預覽\"]')"); await poll(`document.querySelector('[aria-label="B16 批次保存結果"]')?.innerText.includes(${JSON.stringify(expectedText)})`, expectedText); return evaluate(`document.querySelector('[aria-label="B16 批次保存結果"]').innerText`); }
async function searchAndOpen(query, title, name) { await evaluate(`(()=>{const i=document.querySelector('#private-history-query'),s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(i,${JSON.stringify(query)});i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('.private-history-search').requestSubmit();})()`); await poll(`document.querySelectorAll('.private-history-browser .private-product-card').length===1`, `${query} result`); await evaluate(`document.querySelector('.private-history-browser .private-product-card').click()`); await poll(`document.querySelector('[data-private-history-container=true] h3')?.textContent===${JSON.stringify(title)}`, `${query} detail`); const detail = await evaluate(`(()=>{const r=document.querySelector('[data-private-history-container=true]'),track=b=>r.querySelector('[data-private-history-basis='+b+']'),raw=b=>[...track(b).querySelectorAll('[data-history-granularity=raw] .history-row')].map(x=>({price:Number(x.dataset.priceTwd),date:x.querySelector('time')?.getAttribute('datetime')??''})),daily=b=>[...track(b).querySelectorAll('[data-history-granularity=daily] .history-row')].map(x=>({date:x.dataset.taipeiDate,samples:Number(x.dataset.sampleCount),price:Number(x.dataset.priceTwd??x.dataset.representativePriceTwd)}));return{title:r.querySelector('h3')?.textContent,before_raw:raw('before_coupon'),reported_raw:raw('user_reported_after_coupon'),confirmed_raw:raw('confirmed_after_coupon'),before_daily:daily('before_coupon'),reported_daily:daily('user_reported_after_coupon'),confirmed_daily:daily('confirmed_after_coupon'),confirmed_empty:track('confirmed_after_coupon').innerText.includes('沒有資料；不以零元或其他軌跡補值。'),not_verified:r.innerText.includes('NOT PLATFORM VERIFIED'),private_label:r.innerText.includes('PRIVATE_LOCAL_USER_ENTERED'),cta_disabled:r.querySelector('button.cta')?.disabled===true,external_links:[...r.querySelectorAll('a[href]')].filter(a=>new URL(a.href).origin!==location.origin).length};})()`); await capture(name); return detail; }

let started = false, chrome, result;
const requests = new Map(), network = [], consoleEvents = [];
const manual = { title: "Synthetic H13 trial product", product: "PROD-H13-TRIAL", sku: "SKU-H13-TRIAL", seller: "SELLER-H13", package: "EACH-1", observed: "2026-11-06T12:00:00+08:00", source: "H13 isolated A17 trial entry" };
try {
  if (existsSync(database)) throw new Error("H13 private database already exists before trial journey");
  const start1 = runControl("start"); started = true;
  const status1 = runControl("status");
  const health1 = await waitForJson(`http://127.0.0.1:${port}/__cdh/health`);
  if (start1.status !== "READY" || status1.status !== "READY" || health1.runtime_bundle_manifest_sha256 !== expected.runtimeManifest || health1.b11_sha256 !== expected.b11 || health1.b15_rev2_sha256 !== expected.b15 || health1.b16_r12_sha256 !== expected.b16 || health1.b16_revision !== "REV3") throw new Error("A17 runtime identity mismatch");
  chrome = spawn(chromePath, ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", "--remote-debugging-address=127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(runtime, "chrome-profile")}`, "about:blank"], { cwd: project, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let chromeError = ""; chrome.stderr.on("data", (data) => { chromeError += data.toString(); });
  const tabs = await waitForJson(`http://127.0.0.1:${debugPort}/json`), tab = tabs.find((item) => item.type === "page"); if (!tab?.webSocketDebuggerUrl) throw new Error(`Chrome unavailable: ${chromeError}`);
  client = cdpClient(tab.webSocketDebuggerUrl); await client.opened; await Promise.all([client.send("Page.enable"), client.send("DOM.enable"), client.send("Network.enable"), client.send("Runtime.enable"), client.send("Emulation.setDeviceMetricsOverride", { width: 1365, height: 1000, deviceScaleFactor: 1, mobile: false })]);
  client.on("Network.requestWillBeSent", ({ requestId, request }) => requests.set(requestId, { url: request.url, method: request.method }));
  client.on("Network.responseReceived", ({ requestId, response }) => { const request = requests.get(requestId); if (request) network.push({ ...request, status: response.status }); });
  client.on("Runtime.exceptionThrown", (event) => consoleEvents.push({ type: "exception", text: event.exceptionDetails.text }));
  const load = client.once("Page.loadEventFired"); await client.send("Page.navigate", { url: `http://127.0.0.1:${port}/?mode=synthetic&contract=v4&h13=1` }); await load; await poll(`document.querySelector('#batch-import-file')!==null&&document.querySelector('#private-history-query')!==null`, "A17 trial UI");
  const syntheticSearch = await searchSynthetic(); await capture("01-synthetic-search");

  await openManualForm(); const manualRowsBefore = existsSync(database) ? rowCount() : 0; const manualPreviewResult = await manualPreview(manual); const manualPreviewNoWrite = (existsSync(database) ? rowCount() : 0) === manualRowsBefore; await capture("02-manual-preview"); const manualCommit = await manualConfirm(); const rowsAfterManual = rowCount();
  const hashBeforeCsvPreview = await sha256(database), rowsBeforeCsvPreview = rowCount(); const csvPreview = await selectAndPreview(validCsv, "valid_two_day.csv"); const csvPreviewNoWrite = rowCount() === rowsBeforeCsvPreview && await sha256(database) === hashBeforeCsvPreview; const csvCommit = await batchConfirm("新批次已保存"); const rowsAfterCsv = rowCount();
  const hashBeforeJsonPreview = await sha256(database), rowsBeforeJsonPreview = rowCount(); const jsonPreview = await selectAndPreview(validJson, "valid_two_day.json"); const jsonPreviewNoWrite = rowCount() === rowsBeforeJsonPreview && await sha256(database) === hashBeforeJsonPreview; const jsonCommit = await batchConfirm("新批次已保存"); const rowsAfterJson = rowCount(); await capture("03-imports-complete");

  runControl("stop"); started = false; const stopped1 = runControl("status"); const hashBeforeRead = await sha256(database), rowsBeforeRead = rowCount(), restartNetworkIndex = network.length;
  const start2 = runControl("start"); started = true; const status2 = runControl("status"); const health2 = await waitForJson(`http://127.0.0.1:${port}/__cdh/health`); if (health2.instance_id === health1.instance_id || health2.runtime_bundle_manifest_sha256 !== expected.runtimeManifest) throw new Error("A17 restart identity mismatch");
  const reload = client.once("Page.loadEventFired"); await client.send("Page.reload", { ignoreCache: true }); await reload; await poll(`document.querySelector('#private-history-query')!==null`, "private history after restart"); await capture("04-restart-ready");
  const manualDetail = await searchAndOpen(manual.product, manual.title, "05-manual-history"); const csvDetail = await searchAndOpen("PROD-B16-CSV", "Synthetic CSV product", "06-csv-history"); const jsonDetail = await searchAndOpen("PROD-B16-EXAMPLE", "Synthetic batch example product", "07-json-history");
  const afterRestart = network.slice(restartNetworkIndex), postAfterRestart = afterRestart.filter((item) => item.method === "POST").length; const hashAfterRead = await sha256(database), rowsAfterRead = rowCount();
  const external = network.filter((item) => (item.url.startsWith("http:") || item.url.startsWith("https:")) && !["127.0.0.1", "localhost"].includes(new URL(item.url).hostname));
  const batchDetailGate = (detail) => JSON.stringify(detail.before_raw.map((x) => x.price)) === "[1000,950]" && JSON.stringify(detail.reported_raw.map((x) => x.price)) === "[900]" && detail.confirmed_raw.length === 0 && detail.confirmed_daily.length === 0 && detail.confirmed_empty && detail.not_verified && detail.private_label && detail.cta_disabled && detail.external_links === 0;
  const manualDetailGate = JSON.stringify(manualDetail.before_raw.map((x) => x.price)) === "[1200]" && JSON.stringify(manualDetail.reported_raw.map((x) => x.price)) === "[1000]" && manualDetail.confirmed_raw.length === 0 && manualDetail.confirmed_empty && manualDetail.not_verified && manualDetail.private_label && manualDetail.cta_disabled;
  const gates = {
    formal_trial_cmd_start_status: launcherReceipts.slice(0, 2).map((x) => x.entry).join(",") === "Start-CDH-Trial.cmd,Status-CDH-Trial.cmd" && launcherReceipts.every((x) => x.exit_code === 0 && x.stderr === ""),
    exact_runtime_versions: health1.runtime_bundle_manifest_sha256 === expected.runtimeManifest && health1.b11_sha256 === expected.b11 && health1.b15_rev2_sha256 === expected.b15 && health1.b16_r12_sha256 === expected.b16,
    synthetic_search: syntheticSearch.detail.includes("Synthetic already-included") && syntheticSearch.affiliate_disabled,
    manual_preview_confirm: manualPreviewNoWrite && manualPreviewResult.write_count?.includes("0") && manualPreviewResult.confirmed === "UNKNOWN" && manualCommit.includes("已保存") && rowsAfterManual === 1,
    csv_preview_confirm: csvPreviewNoWrite && csvPreview.rows === 2 && csvCommit.includes("HTTP 201") && rowsAfterCsv === 3,
    json_preview_confirm: jsonPreviewNoWrite && jsonPreview.rows === 2 && jsonCommit.includes("HTTP 201") && rowsAfterJson === 5,
    documented_stop_restart: stopped1.status === "STOPPED" && start2.status === "READY" && status2.status === "READY" && health1.instance_id !== health2.instance_id,
    manual_history_classification: manualDetailGate,
    batch_history_classification: batchDetailGate(csvDetail) && batchDetailGate(jsonDetail),
    daily_history_dates_samples: [csvDetail, jsonDetail].every((detail) => JSON.stringify(detail.before_daily.map((x) => [x.date, x.samples])) === JSON.stringify([["2026-11-03", 1], ["2026-11-04", 1]]) && JSON.stringify(detail.reported_daily.map((x) => [x.date, x.samples])) === JSON.stringify([["2026-11-03", 1]])),
    read_only_after_restart: postAfterRestart === 0 && rowsBeforeRead === rowsAfterRead && rowsAfterRead === 5 && hashBeforeRead === hashAfterRead,
    private_data_location: database.includes(path.join("data", "A17_private_history")),
    no_external_requests: external.length === 0,
    no_console_exceptions: consoleEvents.length === 0,
  };
  const chromeExit = new Promise((resolve) => chrome.once("exit", (code, signal) => resolve([code, signal]))); await client.send("Browser.close"); client = undefined; const [chromeExitCode, chromeExitSignal] = await chromeExit; chrome = undefined;
  const stop2 = runControl("stop"); started = false; const stopped2 = runControl("status");
  const passed = Object.values(gates).every(Boolean) && chromeExitCode === 0 && stop2.status === "STOPPED" && stopped2.status === "STOPPED";
  result = {
    schema_version: "CDH-H13-A17-LOCAL-TRIAL-E2E-1", task_id: "CDH-H13-LOCAL-TRIAL-FIRST-USE-001", created_at_utc: new Date().toISOString(), status: passed ? "PASS" : "FAIL",
    browser_test_exit_code: passed ? 0 : 1, chrome_process_exit_code: chromeExitCode, chrome_process_exit_signal: chromeExitSignal,
    exact_dependencies: expected, integration: "A17_INTEGRATED_RUNTIME_ROOT_CMD_FIRST_USE", root_cmd_launcher_used: true, h_test_loader_used: false,
    health: { runtime_bundle_manifest_sha256: health1.runtime_bundle_manifest_sha256, b11_sha256: health1.b11_sha256, b15_rev2_sha256: health1.b15_rev2_sha256, b16_r12_sha256: health1.b16_r12_sha256, b16_revision: health1.b16_revision },
    website_restart_count: 1, formal_database_write_count: 0, isolated_database: path.relative(root, database).replaceAll("\\", "/"),
    launcher_receipts: launcherReceipts, synthetic_search: syntheticSearch, manual_preview: manualPreviewResult, manual_commit: manualCommit, csv_preview: csvPreview, csv_commit: csvCommit, json_preview: jsonPreview, json_commit: jsonCommit,
    rows_after_manual: rowsAfterManual, rows_after_csv: rowsAfterCsv, rows_after_json: rowsAfterJson, rows_before_read: rowsBeforeRead, rows_after_read: rowsAfterRead,
    database_sha256_before_read: hashBeforeRead, database_sha256_after_read: hashAfterRead, browser_post_after_restart_count: postAfterRestart,
    manual_detail: manualDetail, csv_detail: csvDetail, json_detail: jsonDetail, network, external_request_count: external.length, console_events: consoleEvents, captures, gates, final_stop: stop2, final_status: stopped2,
  };
  await writeFile(path.join(evidence, "ACTUAL_H13_BROWSER_HTTP.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ status: result.status, gates, rows: rowsAfterRead, chrome_process_exit_code: chromeExitCode, external_request_count: external.length, captures: captures.length })); process.exitCode = result.browser_test_exit_code;
} catch (error) {
  result = { schema_version: "CDH-H13-A17-LOCAL-TRIAL-E2E-1", task_id: "CDH-H13-LOCAL-TRIAL-FIRST-USE-001", created_at_utc: new Date().toISOString(), status: "FAIL", browser_test_exit_code: 1, error: error.stack ?? String(error), launcher_receipts: launcherReceipts, network, console_events: consoleEvents, captures };
  await writeFile(path.join(evidence, "ACTUAL_H13_BROWSER_HTTP.json"), `${JSON.stringify(result, null, 2)}\n`); console.error(error.stack ?? String(error)); process.exitCode = 1;
} finally {
  if (client) client.close(); if (chrome && chrome.exitCode === null) chrome.kill(); if (started) try { runControl("stop"); } catch { /* preserve */ }
}
