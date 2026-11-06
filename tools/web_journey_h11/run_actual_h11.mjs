import { createHash } from "node:crypto";
import { execFileSync, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const tools = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(tools, "../..");
const h11 = path.join(root, "review", "H11");
const finalMode = process.env.CDH_H11_FINAL === "1";
const attempt = finalMode ? path.join(root, "review", "H11_FINAL") : path.join(h11, "attempt2");
const runtime = path.join(attempt, "runtime");
const project = path.join(runtime, "project");
const previewRoot = path.join(project, "apps", "price-web", "local-preview-a11");
const control = path.join(previewRoot, "control.py");
const evidence = path.join(attempt, "evidence");
const screenshots = path.join(evidence, "screenshots");
const domRoot = path.join(evidence, "dom");
const state = path.join(runtime, "state");
const serverRuntime = path.join(runtime, "server");
const logs = path.join(runtime, "logs");
const privateData = path.join(project, "review", "H11", "private-data");
const database = path.join(privateData, "private_user_observations.sqlite3");
const examples = path.join(runtime, "examples", "services", "private_batch_import_b16", "examples");
const validCsv = path.join(examples, "valid_two_day.csv");
const validJson = path.join(examples, "valid_two_day.json");
const invalidJson = path.join(examples, "invalid_row.json");
const python = "C:\\Users\\zheny\\AppData\\Local\\Programs\\Python\\Python313\\python.exe";
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 12332;
const expected = {
  a15: finalMode ? "be0becbaa384e1a633c5893b266dbbb03c449ca405ef1f0c07bb8dd53456634b" : "5cc44dedd910ff9b2055cfc2772ad0c3d6db627ffc818794f81fd3d9b5552d4b",
  b16: finalMode ? "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7" : "6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6",
};
await Promise.all([mkdir(evidence, { recursive: true }), mkdir(screenshots, { recursive: true }), mkdir(domRoot, { recursive: true }), mkdir(state, { recursive: true }), mkdir(serverRuntime, { recursive: true }), mkdir(logs, { recursive: true })]);

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sha256 = async (file) => createHash("sha256").update(await readFile(file)).digest("hex");
const rowCount = () => Number(execFileSync(python, ["-c", "import pathlib,sqlite3,sys; u=pathlib.Path(sys.argv[1]).resolve().as_uri()+'?mode=ro'; c=sqlite3.connect(u,uri=True); print(c.execute('select count(*) from observations').fetchone()[0]); c.close()", database], { windowsHide: true, encoding: "utf8" }).trim());
const controlArgs = (action) => [control, action, "--project-root", project, "--port", String(port), "--state-dir", state, "--runtime-root", serverRuntime, "--log-dir", logs, "--private-data-root", privateData, "--timeout", "20"];
const runControl = (action) => JSON.parse(execFileSync(python, controlArgs(action), { cwd: previewRoot, windowsHide: true, encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" } }).trim().split(/\r?\n/).at(-1));
const debugPort = await new Promise((resolve, reject) => { const probe = net.createServer(); probe.once("error", reject); probe.listen(0, "127.0.0.1", () => { const address = probe.address(); if (!address || typeof address === "string") return reject(new Error("Unable to allocate CDP port")); probe.close((error) => error ? reject(error) : resolve(address.port)); }); });

async function waitForJson(url) { for (let index = 0; index < 200; index += 1) { try { const response = await fetch(url); if (response.ok) return response.json(); } catch { /* startup */ } await wait(100); } throw new Error(`Endpoint not ready: ${url}`); }
function cdpClient(url) {
  const socket = new WebSocket(url), pending = new Map(), listeners = new Map(); let next = 1;
  socket.addEventListener("message", (event) => { const message = JSON.parse(event.data); if (message.id && pending.has(message.id)) { const call = pending.get(message.id); pending.delete(message.id); message.error ? call.reject(new Error(message.error.message)) : call.resolve(message.result); return; } for (const callback of listeners.get(message.method) ?? []) callback(message.params); });
  return { opened: new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); }), send(method, params = {}) { const id = next++; return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); }); }, once(method) { return new Promise((resolve) => { const callback = (params) => { listeners.set(method, (listeners.get(method) ?? []).filter((item) => item !== callback)); resolve(params); }; listeners.set(method, [...(listeners.get(method) ?? []), callback]); }); }, on(method, callback) { listeners.set(method, [...(listeners.get(method) ?? []), callback]); }, close() { socket.close(); } };
}
async function evaluate(expression) { const response = await client.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text); return response.result.value; }
async function poll(expression, label, limit = 160) { for (let index = 0; index < limit; index += 1) { if (await evaluate(expression)) return; await wait(100); } throw new Error(`Timed out waiting for ${label}`); }
async function setFile(file) { const document = await client.send("DOM.getDocument", { depth: -1, pierce: true }); const input = await client.send("DOM.querySelector", { nodeId: document.root.nodeId, selector: "#batch-import-file" }); if (!input.nodeId) throw new Error("A15 file input missing"); await client.send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [] }); await client.send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [file] }); await evaluate(`document.querySelector('#batch-import-file').dispatchEvent(new Event('change',{bubbles:true}))`); }
async function clickText(text) { const clicked = await evaluate(`(() => { const button=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()===${JSON.stringify(text)}); if(!button||button.disabled)return false; button.click(); return true; })()`); if (!clicked) throw new Error(`button unavailable: ${text}`); }
async function capture(name) { const page = await evaluate(`({url:location.href,html:document.documentElement.outerHTML,width:innerWidth,scrollWidth:document.documentElement.scrollWidth})`); const shot = await client.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }); const screenshot = path.join(screenshots, `${name}.png`), dom = path.join(domRoot, `${name}.html`); await writeFile(screenshot, Buffer.from(shot.data, "base64")); await writeFile(dom, page.html, "utf8"); captures.push({ name, url: page.url, screenshot: path.relative(root, screenshot).replaceAll("\\", "/"), dom: path.relative(root, dom).replaceAll("\\", "/"), horizontal_overflow: page.scrollWidth > page.width }); }
async function selectAndLocalPreview(file, filename, count) { await setFile(file); await poll(`document.querySelector('[aria-label="批次匯入本機預覽表格"]')?.innerText.includes(${JSON.stringify(filename)}) && document.querySelector('[aria-label="批次匯入本機預覽表格"]')?.innerText.includes(${JSON.stringify(`${count} 筆`)}) && [...document.querySelectorAll('button')].some(x=>x.textContent.trim()==='送往 B16 安全預覽'&&!x.disabled)`, `${filename} local preview`); }
async function serverPreviewReady() { await clickText("送往 B16 安全預覽"); await poll(`document.querySelector('[aria-label="B16 伺服器批次預覽"]')?.innerText.includes('PREVIEW_READY_NO_DATABASE_WRITE')`, "B16 ready preview"); return evaluate(`(() => { const root=document.querySelector('[aria-label="B16 伺服器批次預覽"]'); return {text:root.innerText,rows:root.querySelectorAll('tbody tr').length,database_write_zero:root.innerText.includes('database_write_count = 0'),confirmed_values:[...root.querySelectorAll('tbody tr')].map(x=>x.children[6]?.textContent??'')}; })()`); }
async function explicitConfirm(expectedText) { await evaluate(`document.querySelector('[aria-label="B16 伺服器批次預覽"] input[type=checkbox]').click()`); await clickText("明確確認並保存"); await poll(`document.querySelector('[aria-label="B16 批次保存結果"]')?.innerText.includes(${JSON.stringify(expectedText)})`, expectedText); return evaluate(`document.querySelector('[aria-label="B16 批次保存結果"]').innerText`); }
async function searchAndOpen(query, title, name) { await evaluate(`(() => { const input=document.querySelector('#private-history-query'),setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; setter.call(input,${JSON.stringify(query)}); input.dispatchEvent(new Event('input',{bubbles:true})); input.dispatchEvent(new Event('change',{bubbles:true})); document.querySelector('.private-history-search').requestSubmit(); })()`); await poll(`!document.querySelector('[data-private-history-container=true] h3')&&document.querySelectorAll('.private-history-browser .private-product-card').length===1&&document.querySelector('.private-history-browser .private-product-card')?.innerText.includes(${JSON.stringify(query)})`, `${query} exact search result`); await evaluate(`document.querySelector('.private-history-browser .private-product-card').click()`); await poll(`document.querySelector('[data-private-history-container=true] h3')?.textContent===${JSON.stringify(title)}`, `${query} detail`); const detail = await evaluate(`(() => { const root=document.querySelector('[data-private-history-container=true]'),track=b=>root.querySelector('[data-private-history-basis='+b+']'),raw=b=>[...track(b).querySelectorAll('[data-history-granularity=raw] .history-row')].map(x=>({price:Number(x.dataset.priceTwd),date:x.querySelector('time')?.getAttribute('datetime')??''})),daily=b=>[...track(b).querySelectorAll('[data-history-granularity=daily] .history-row')].map(x=>({date:x.dataset.taipeiDate,samples:Number(x.dataset.sampleCount),price:Number(x.dataset.priceTwd??x.querySelector('.history-row')?.dataset.priceTwd)})); return {title:root.querySelector('h3')?.textContent,before_raw:raw('before_coupon'),before_daily:daily('before_coupon'),reported_raw:raw('user_reported_after_coupon'),reported_daily:daily('user_reported_after_coupon'),confirmed_raw:raw('confirmed_after_coupon'),confirmed_daily:daily('confirmed_after_coupon'),confirmed_empty:track('confirmed_after_coupon').innerText.includes('沒有資料；不以零元或其他軌跡補值。'),private_label:root.innerText.includes('PRIVATE_LOCAL_USER_ENTERED'),not_verified:root.innerText.includes('NOT PLATFORM VERIFIED'),cta_disabled:root.querySelector('button.cta')?.disabled===true,external_links:[...root.querySelectorAll('a[href]')].filter(a=>new URL(a.href).origin!==location.origin).length}; })()`); await capture(name); return detail; }

let started = false, chrome, client, result;
const requests = new Map(), network = [], consoleEvents = [], captures = [];
try {
  if (existsSync(database)) throw new Error("H11 database already exists before single authorized journey");
  const start1 = runControl("start"); started = true;
  if (start1.status !== "READY" || start1.b16_r12_sha256 !== expected.b16) throw new Error(`B16 REV2 identity mismatch: ${JSON.stringify(start1)}`);
  const health1 = await waitForJson(`http://127.0.0.1:${port}/__cdh/health`);
  if (health1.b16_r12_sha256 !== expected.b16 || health1.b16_api_schema !== "CDH-B16-PRIVATE-BATCH-API-1" || (finalMode && health1.b16_revision !== "REV3")) throw new Error("health API identity mismatch");
  chrome = spawn(chromePath, ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", "--remote-debugging-address=127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(runtime, "chrome-profile")}`, "about:blank"], { cwd: project, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let chromeError = ""; chrome.stderr.on("data", (data) => { chromeError += data.toString(); });
  const tabs = await waitForJson(`http://127.0.0.1:${debugPort}/json`), tab = tabs.find((item) => item.type === "page"); if (!tab?.webSocketDebuggerUrl) throw new Error(`Chrome CDP unavailable: ${chromeError}`);
  client = cdpClient(tab.webSocketDebuggerUrl); await client.opened; await Promise.all([client.send("Page.enable"), client.send("DOM.enable"), client.send("Network.enable"), client.send("Runtime.enable"), client.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false })]);
  client.on("Network.requestWillBeSent", ({ requestId, request }) => { requests.set(requestId, { url: request.url, method: request.method }); });
  client.on("Network.responseReceived", ({ requestId, response }) => { const request = requests.get(requestId); if (request) network.push({ ...request, status: response.status }); });
  client.on("Runtime.consoleAPICalled", (event) => consoleEvents.push({ type: event.type, text: event.args.map((item) => item.value ?? item.description ?? "").join(" ") }));
  client.on("Runtime.exceptionThrown", (event) => consoleEvents.push({ type: "exception", text: event.exceptionDetails.text }));
  const load = client.once("Page.loadEventFired"); await client.send("Page.navigate", { url: `http://127.0.0.1:${port}/?mode=synthetic&contract=v4&h11=1` }); await load; await poll(`document.querySelector('#batch-import-file')!==null`, "A15 UI"); await capture("01-a15-ready");

  await selectAndLocalPreview(invalidJson, "invalid_row.json", 1); await capture("02-invalid-local-preview"); await clickText("送往 B16 安全預覽"); await poll(`document.querySelector('[aria-label="B16 伺服器批次預覽"]')?.innerText.includes('PREVIEW_REJECTED')`, "invalid rejection"); const invalidDom = await evaluate(`(() => { const root=document.querySelector('[aria-label="B16 伺服器批次預覽"]'); return {text:root.innerText,confirm_present:[...root.querySelectorAll('button')].some(x=>x.textContent.includes('明確確認'))}; })()`); await capture("03-invalid-server-rejected"); const invalidNoDatabase = !existsSync(database);

  await selectAndLocalPreview(validCsv, "valid_two_day.csv", 2); const csvPreview = await serverPreviewReady(); const csvPreviewNoDatabase = !existsSync(database); await capture("04-csv-server-preview-zero-write"); const csvCommit = await explicitConfirm("新批次已保存"); const rowsAfterCsv = rowCount(); await capture("05-csv-saved");

  await selectAndLocalPreview(validJson, "valid_two_day.json", 2); const rowsBeforeJsonPreview = rowCount(), hashBeforeJsonPreview = await sha256(database); const jsonPreview = await serverPreviewReady(); const jsonPreviewNoWrite = rowCount() === rowsBeforeJsonPreview && await sha256(database) === hashBeforeJsonPreview; await capture("06-json-server-preview-zero-write"); const jsonCommit = await explicitConfirm("新批次已保存"); const rowsAfterJson = rowCount(); await capture("07-json-saved");

  await selectAndLocalPreview(validJson, "valid_two_day.json", 2); const replayPreview = await serverPreviewReady(); const rowsBeforeReplayConfirm = rowCount(); await capture("08-duplicate-preview"); const replayCommit = await explicitConfirm("冪等重播，沒有新增資料"); const rowsAfterReplay = rowCount(); await capture("09-duplicate-no-new-row");

  runControl("stop"); started = false; const dbHashBeforeRead = await sha256(database), rowsBeforeRead = rowCount(), restartMarker = network.length;
  const start2 = runControl("start"); started = true; const health2 = await waitForJson(`http://127.0.0.1:${port}/__cdh/health`); if (health2.instance_id === health1.instance_id || health2.b16_r12_sha256 !== expected.b16) throw new Error("restart identity mismatch");
  const reload = client.once("Page.loadEventFired"); await client.send("Page.reload", { ignoreCache: true }); await reload; await poll(`document.querySelector('#private-history-query')!==null`, "history search after restart"); await capture("10-restart-ready");
  const csvDetail = await searchAndOpen("PROD-B16-CSV", "Synthetic CSV product", "11-csv-history"); const jsonDetail = await searchAndOpen("PROD-B16-EXAMPLE", "Synthetic batch example product", "12-json-history");
  const afterRestart = network.slice(restartMarker), postAfterRestart = afterRestart.filter((item) => item.method === "POST").length; const dbHashAfterRead = await sha256(database), rowsAfterRead = rowCount();
  const external = network.filter((item) => { if (!item.url.startsWith("http:") && !item.url.startsWith("https:")) return false; return !["127.0.0.1", "localhost"].includes(new URL(item.url).hostname); });
  const batchHttp = network.filter((item) => item.url.includes("/batch-")).map((item) => ({ method: item.method, path: new URL(item.url).pathname, status: item.status }));
  const detailGate = (detail) => JSON.stringify(detail.before_raw.map((x) => x.price)) === "[1000,950]" && JSON.stringify(detail.reported_raw.map((x) => x.price)) === "[900]" && detail.confirmed_raw.length === 0 && detail.confirmed_daily.length === 0 && detail.confirmed_empty && detail.private_label && detail.not_verified && detail.cta_disabled && detail.external_links === 0;
  const gates = {
    exact_inputs_and_api_compatible: start1.b16_r12_sha256 === expected.b16 && health1.b16_api_schema === "CDH-B16-PRIVATE-BATCH-API-1",
    invalid_422_no_write: invalidDom.text.includes("逐筆驗證失敗") && !invalidDom.confirm_present && invalidNoDatabase && batchHttp.some((item) => item.status === 422),
    csv_preview_no_write: csvPreview.database_write_zero && csvPreviewNoDatabase && csvPreview.rows === 2,
    csv_confirm_201_two_rows: csvCommit.includes("HTTP 201") && rowsAfterCsv === 2,
    json_preview_no_write: jsonPreview.database_write_zero && jsonPreviewNoWrite && jsonPreview.rows === 2,
    json_confirm_201_four_rows: jsonCommit.includes("HTTP 201") && rowsAfterJson === 4,
    duplicate_confirm_200_no_new_rows: replayPreview.database_write_zero && replayCommit.includes("HTTP 200") && rowsBeforeReplayConfirm === 4 && rowsAfterReplay === 4,
    restart_distinct_instance: health1.instance_id !== health2.instance_id,
    csv_history_exact: detailGate(csvDetail),
    json_history_exact: detailGate(jsonDetail),
    daily_dates_and_samples: [csvDetail, jsonDetail].every((detail) => JSON.stringify(detail.before_daily.map((x) => [x.date, x.samples])) === JSON.stringify([["2026-11-03", 1], ["2026-11-04", 1]]) && JSON.stringify(detail.reported_daily.map((x) => [x.date, x.samples])) === JSON.stringify([["2026-11-03", 1]])),
    read_only_after_restart: postAfterRestart === 0 && rowsBeforeRead === rowsAfterRead && dbHashBeforeRead === dbHashAfterRead,
    no_external_requests: external.length === 0,
    no_console_exceptions: consoleEvents.filter((item) => item.type === "exception").length === 0,
    no_horizontal_overflow: captures.every((item) => !item.horizontal_overflow),
  };
  const chromeExitPromise = new Promise((resolve) => chrome.once("exit", (code, signal) => resolve([code, signal]))); await client.send("Browser.close"); client = undefined; const [chromeExitCode, chromeExitSignal] = await chromeExitPromise; chrome = undefined;
  const stop2 = runControl("stop"); started = false;
  result = { schema_version: finalMode ? "CDH-H11-FINAL-OFFICIAL-LAUNCHER-E2E-1" : "CDH-H11-ACTUAL-BROWSER-E2E-1", task_id: "H11", revision: finalMode ? "FINAL_OFFICIAL_LAUNCHER" : "BASE", created_at_utc: new Date().toISOString(), status: Object.values(gates).every(Boolean) && chromeExitCode === 0 ? "PASS" : "FAIL", browser_test_exit_code: Object.values(gates).every(Boolean) && chromeExitCode === 0 ? 0 : 1, chrome_process_exit_code: chromeExitCode, chrome_process_exit_signal: chromeExitSignal, exact_dependencies: { a15_sha256: expected.a15, b16_sha256: expected.b16 }, integration: finalMode ? "EXACT_A15_REV2_OFFICIAL_LAUNCHER_TO_B16_REV3" : "EXACT_A15_DIST_AND_API_CLIENT_TO_B16_REV2_H_LOADER", h_test_loader_used: !finalMode, health: { b16_r12_sha256: health1.b16_r12_sha256, b16_revision: health1.b16_revision, b16_api_schema: health1.b16_api_schema }, website_restart_count: 1, first_instance_id: health1.instance_id, second_instance_id: health2.instance_id, formal_database_write_count: 0, isolated_database: path.relative(root, database).replaceAll("\\", "/"), invalid_dom: invalidDom, csv_preview: csvPreview, json_preview: jsonPreview, replay_preview: replayPreview, csv_commit: csvCommit, json_commit: jsonCommit, replay_commit: replayCommit, rows_after_csv: rowsAfterCsv, rows_after_json: rowsAfterJson, rows_after_replay: rowsAfterReplay, rows_before_read: rowsBeforeRead, rows_after_read: rowsAfterRead, database_sha256_before_read: dbHashBeforeRead, database_sha256_after_read: dbHashAfterRead, browser_post_after_restart_count: postAfterRestart, csv_detail: csvDetail, json_detail: jsonDetail, batch_http: batchHttp, network, external_request_count: external.length, console_events: consoleEvents, captures, gates, stop_result: stop2 };
  await writeFile(path.join(evidence, "ACTUAL_H11_BROWSER_HTTP.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ status: result.status, gates, rows: rowsAfterRead, browser_post_after_restart_count: postAfterRestart, captures: captures.length, chrome_process_exit_code: chromeExitCode, batch_http: batchHttp })); process.exitCode = result.browser_test_exit_code;
} catch (error) {
  result = { schema_version: "CDH-H11-ACTUAL-BROWSER-E2E-1", task_id: "H11", created_at_utc: new Date().toISOString(), status: "FAIL", browser_test_exit_code: 1, error: error.stack ?? String(error), network, console_events: consoleEvents, captures };
  await writeFile(path.join(evidence, "ACTUAL_H11_BROWSER_HTTP.json"), `${JSON.stringify(result, null, 2)}\n`); console.error(error.stack ?? String(error)); process.exitCode = 1;
} finally {
  if (client) client.close(); if (chrome && chrome.exitCode === null) chrome.kill(); if (started) try { runControl("stop"); } catch { /* preserve evidence */ }
}
