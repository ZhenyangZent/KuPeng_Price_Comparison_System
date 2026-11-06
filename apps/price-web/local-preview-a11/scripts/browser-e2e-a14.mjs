import { createHash } from "node:crypto";
import { execFileSync, spawn } from "node:child_process";
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
const port = 4198;
const debugPort = await new Promise((resolve, reject) => { const probe = net.createServer(); probe.once("error", reject); probe.listen(0, "127.0.0.1", () => { const address = probe.address(); if (!address || typeof address === "string") { probe.close(); reject(new Error("Unable to allocate a loopback CDP port")); return; } const selected = address.port; probe.close((error) => error ? reject(error) : resolve(selected)); }); });
const reportRoot = path.join(projectRoot, "reports", "A14");
const evidenceRoot = path.join(reportRoot, "evidence");
const screenshotRoot = path.join(reportRoot, "screenshots");
const runId = new Date().toISOString().replaceAll(":", "").replaceAll(".", "");
const runRoot = path.join(reportRoot, "browser_runtime", runId);
const state = path.join(runRoot, "state");
const privateData = path.join(runRoot, "private_data");
const database = path.join(privateData, "private_user_observations.sqlite3");

await Promise.all([mkdir(evidenceRoot, { recursive: true }), mkdir(screenshotRoot, { recursive: true }), mkdir(runRoot, { recursive: true })]);

const controlArgs = (action) => [control, action, "--project-root", projectRoot, "--port", String(port), "--state-dir", state, "--runtime-root", path.join(reportRoot, "evidence", "runtime"), "--log-dir", path.join(reportRoot, "evidence", "server_logs"), "--private-data-root", privateData, "--timeout", "20"];
const runControl = (action) => JSON.parse(execFileSync(python, controlArgs(action), { cwd: previewRoot, windowsHide: true, encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1" } }).trim().split(/\r?\n/).at(-1));
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sha256 = async (file) => createHash("sha256").update(await readFile(file)).digest("hex");
const rowCount = () => Number(execFileSync(python, ["-c", "import sqlite3,sys; c=sqlite3.connect('file:'+sys.argv[1].replace('\\\\','/')+'?mode=ro',uri=True); print(c.execute('select count(*) from observations').fetchone()[0]); c.close()", database], { windowsHide: true, encoding: "utf8" }).trim());

async function waitForJson(url) {
  for (let index = 0; index < 120; index += 1) {
    try { const response = await fetch(url); if (response.ok) return response.json(); } catch { /* startup */ }
    await wait(100);
  }
  throw new Error(`Endpoint not ready: ${url}`);
}

async function postJson(url, body, csrf) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CDH-CSRF-Token": csrf }, body: JSON.stringify(body) });
  const payload = await response.json();
  if (!response.ok) throw new Error(`POST ${url} failed: ${response.status} ${JSON.stringify(payload)}`);
  return { status: response.status, payload };
}

function observation(submissionId, observedAt, before, coupon) {
  return {
    schema_version: "CDH-B15-MANUAL-OBSERVATION-1",
    submission_id: submissionId,
    title: "A14 重新開啟私人商品",
    identity: { platform: "COUPANG_TW", product_id: "P-A14-REOPEN", sku_id: "SKU-A14-REOPEN", seller_id: "SELLER-A14", condition: "NEW", package_signature: "EACH-1", currency: "TWD" },
    observed_at: observedAt,
    quantity: 1,
    before_coupon_price_twd: before,
    user_reported_coupon: coupon === null
      ? { status: "NONE", price_twd: null, eligibility: "UNKNOWN", evidence_level: "NONE", evidence_note: null, valid_from: null, valid_until: null }
      : { status: "USER_REPORTED", price_twd: coupon, eligibility: "UNKNOWN", evidence_level: "NONE", evidence_note: null, valid_from: null, valid_until: null },
    shipping: { status: "UNKNOWN", shipping_fee_twd: null, mandatory_fee_twd: null },
    source: { source_class: "USER_ENTERED", visibility: "PRIVATE_LOCAL", note: "A14 isolated restart journey" },
  };
}

async function saveObservation(base, csrf, body) {
  const preview = await postJson(`${base}/api/private-observations/v1/preview`, body, csrf);
  if (preview.payload.database_write_count !== 0 || preview.payload.will_save.confirmed_after_coupon_price_twd !== null) throw new Error("Unsafe B15 preview contract");
  return postJson(`${base}/api/private-observations/v1/confirm`, { preview_id: preview.payload.preview_id, confirm_token: preview.payload.confirm_token, explicit_confirm: true }, csrf);
}

function cdpClient(url) {
  const socket = new WebSocket(url), pending = new Map(), listeners = new Map(); let next = 1;
  socket.addEventListener("message", (event) => { const message = JSON.parse(event.data); if (message.id && pending.has(message.id)) { const call = pending.get(message.id); pending.delete(message.id); message.error ? call.reject(new Error(message.error.message)) : call.resolve(message.result); return; } for (const callback of listeners.get(message.method) ?? []) callback(message.params); });
  return {
    opened: new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); }),
    send(method, params = {}) { const id = next++; return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); }); },
    once(method) { return new Promise((resolve) => { const callback = (params) => { listeners.set(method, (listeners.get(method) ?? []).filter((item) => item !== callback)); resolve(params); }; listeners.set(method, [...(listeners.get(method) ?? []), callback]); }); },
    on(method, callback) { listeners.set(method, [...(listeners.get(method) ?? []), callback]); },
    close() { socket.close(); },
  };
}

async function pollExpression(cdp, expression, label) {
  for (let index = 0; index < 100; index += 1) {
    const result = (await cdp.send("Runtime.evaluate", { expression, returnByValue: true })).result.value;
    if (result) return result;
    await wait(100);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

let started = false, chromeProcess, cdp, chromeStderr = "";
const network = [], commits = [];
try {
  const firstStart = runControl("start"); started = true;
  if (firstStart.status !== "READY" || firstStart.b15_r11_rev2_sha256 !== "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe") throw new Error(`First start failed: ${JSON.stringify(firstStart)}`);
  const firstHealth = await waitForJson(`http://127.0.0.1:${port}/__cdh/health`);
  const base = `http://127.0.0.1:${port}/cdh-private-observations`;
  const session = await (await fetch(`${base}/api/private-observations/v1/session`)).json();
  commits.push(await saveObservation(base, session.csrf_token, observation("SUB-A14-0001", "2026-11-03T12:00:00+08:00", 1000, 900)));
  commits.push(await saveObservation(base, session.csrf_token, observation("SUB-A14-0002", "2026-11-04T12:00:00+08:00", 950, null)));
  const firstStop = runControl("stop"); started = false;
  if (firstStop.status !== "STOPPED") throw new Error(`First stop failed: ${JSON.stringify(firstStop)}`);
  const databaseShaBeforeRead = await sha256(database), rowsBeforeRead = rowCount();

  const secondStart = runControl("start"); started = true;
  if (secondStart.status !== "READY" || secondStart.b15_r11_rev2_sha256 !== firstStart.b15_r11_rev2_sha256) throw new Error(`Second start failed: ${JSON.stringify(secondStart)}`);
  const secondHealth = await waitForJson(`http://127.0.0.1:${port}/__cdh/health`);
  if (secondHealth.instance_id === firstHealth.instance_id) throw new Error("Website instance was not restarted");

  chromeProcess = spawn(chrome, ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", "--remote-debugging-address=127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(runRoot, "chrome-profile")}`, "about:blank"], { cwd: previewRoot, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  chromeProcess.stderr.on("data", (data) => { chromeStderr += data.toString(); });
  let tabs;
  for (let index = 0; index < 120; index += 1) { try { const response = await fetch(`http://127.0.0.1:${debugPort}/json`); if (response.ok) { tabs = await response.json(); break; } } catch { /* CDP startup */ } await wait(100); }
  const tab = tabs?.find((item) => item.type === "page");
  if (!tab?.webSocketDebuggerUrl) throw new Error(`Chrome CDP unavailable: ${chromeStderr}`);
  cdp = cdpClient(tab.webSocketDebuggerUrl); await cdp.opened; await cdp.send("Page.enable"); await cdp.send("Network.enable");
  cdp.on("Network.requestWillBeSent", ({ request }) => { if (request.url.includes("/cdh-private-observations/")) network.push({ url: request.url, method: request.method }); });
  const loaded = cdp.once("Page.loadEventFired"); await cdp.send("Page.navigate", { url: `http://127.0.0.1:${port}/?mode=synthetic&contract=v4` }); await loaded;
  await pollExpression(cdp, `document.querySelector('#private-history-query') !== null`, "A14 search input");
  await cdp.send("Runtime.evaluate", { expression: `(() => { const input=document.querySelector('#private-history-query'); const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; setter.call(input,'P-A14-REOPEN'); input.dispatchEvent(new Event('input',{bubbles:true})); input.dispatchEvent(new Event('change',{bubbles:true})); [...document.querySelectorAll('button')].find(x=>x.textContent==='搜尋私人紀錄').click(); })()` });
  await pollExpression(cdp, `document.querySelectorAll('.private-history-browser .private-product-card').length === 1`, "private search result");
  await cdp.send("Runtime.evaluate", { expression: `document.querySelector('.private-history-browser .private-product-card').click()` });
  await pollExpression(cdp, `document.querySelector('[data-private-history-container=true] h3')?.textContent === 'A14 重新開啟私人商品'`, "private history detail");
  const dom = (await cdp.send("Runtime.evaluate", { expression: `(() => { const root=document.querySelector('[data-private-history-container=true]'); const values=(basis,granularity,field)=>[...root.querySelectorAll('[data-private-history-basis='+basis+'] [data-history-granularity='+granularity+'] .history-row')].map(x=>x.dataset[field]); return {title:root.querySelector('h3')?.textContent??'',before_raw:values('before_coupon','raw','priceTwd'),before_daily:values('before_coupon','daily','taipeiDate'),confirmed_raw:values('confirmed_after_coupon','raw','priceTwd'),reported_raw:values('user_reported_after_coupon','raw','priceTwd'),reported_daily:values('user_reported_after_coupon','daily','taipeiDate'),private_result_count:document.querySelectorAll('.private-history-browser .private-product-card').length,private_label:root.innerText.includes('PRIVATE_LOCAL_USER_ENTERED'),not_verified:root.innerText.includes('NOT PLATFORM VERIFIED'),confirmed_empty:root.querySelector('[data-private-history-basis=confirmed_after_coupon]')?.innerText.includes('沒有資料；不以零元或其他軌跡補值。')??false,cta_disabled:root.querySelector('button.cta')?.disabled===true,synthetic_title_inside_private:root.innerText.includes('B11'),external_links:[...root.querySelectorAll('a[href]')].filter(a=>new URL(a.href).origin!==location.origin).length,width:innerWidth,scrollWidth:document.documentElement.scrollWidth}; })()`, returnByValue: true })).result.value;
  const screenshot = path.join(screenshotRoot, "a14-private-history-reopen.png");
  await writeFile(screenshot, Buffer.from((await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true })).data, "base64"));
  cdp.close(); cdp = undefined; chromeProcess.kill(); chromeProcess = undefined;
  const secondStop = runControl("stop"); started = false;
  if (secondStop.status !== "STOPPED") throw new Error(`Second stop failed: ${JSON.stringify(secondStop)}`);
  const databaseShaAfterRead = await sha256(database), rowsAfterRead = rowCount();
  const privatePostAfterRestart = network.filter((item) => item.method === "POST").length;
  const externalNetwork = network.filter((item) => !item.url.startsWith(`http://127.0.0.1:${port}/`) && !item.url.startsWith(`http://localhost:${port}/`));
  const allPass = databaseShaAfterRead === databaseShaBeforeRead && rowsBeforeRead === 2 && rowsAfterRead === 2 && privatePostAfterRestart === 0 && dom.before_raw.join(",") === "1000,950" && dom.before_daily.join(",") === "2026-11-03,2026-11-04" && dom.confirmed_raw.length === 0 && dom.reported_raw.join(",") === "900" && dom.reported_daily.join(",") === "2026-11-03" && dom.private_result_count === 1 && dom.private_label && dom.not_verified && dom.confirmed_empty && dom.cta_disabled && !dom.synthetic_title_inside_private && dom.external_links === 0 && externalNetwork.length === 0 && dom.scrollWidth <= dom.width;
  const result = { schema_version: "CDH-A14-BROWSER-E2E-1", task_id: "CDH-A14-PRIVATE-HISTORY-BROWSE-001", created_at_utc: new Date().toISOString(), exact_dependencies: { a13_rev3_sha256: "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274", b15_rev2_sha256: firstStart.b15_r11_rev2_sha256 }, integration: "ACTUAL_A14_UI_TO_B15_REV2_LOCAL_API", isolated_private_data_root: privateData, website_restart_count: 1, first_instance_id: firstHealth.instance_id, second_instance_id: secondHealth.instance_id, seed_commit_statuses: commits.map((entry) => entry.status), rows_before_read: rowsBeforeRead, rows_after_read: rowsAfterRead, database_sha256_before_read: databaseShaBeforeRead, database_sha256_after_read: databaseShaAfterRead, database_unchanged_by_read: databaseShaBeforeRead === databaseShaAfterRead, private_post_after_restart_count: privatePostAfterRestart, external_request_count: externalNetwork.length, formal_database_write_count: 0, registry_action_count: 0, firefox_action_count: 0, dom, network, screenshot: path.relative(projectRoot, screenshot).replaceAll("\\", "/"), all_pass: allPass };
  await writeFile(path.join(evidenceRoot, "BROWSER_E2E_A14.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ all_pass: allPass, rows: rowsAfterRead, database_unchanged_by_read: result.database_unchanged_by_read, private_post_after_restart_count: privatePostAfterRestart, integration: result.integration }));
  if (!allPass) process.exitCode = 1;
} finally {
  if (cdp) cdp.close();
  if (chromeProcess) chromeProcess.kill();
  if (started) try { runControl("stop"); } catch { /* retain evidence for manual inspection */ }
}
