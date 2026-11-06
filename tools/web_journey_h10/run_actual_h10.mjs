import { execFileSync, spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const toolRoot = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(toolRoot, "../..");
const runtime = path.join(root, "review", "H10", "runtime");
const project = path.join(runtime, "project");
const previewRoot = path.join(project, "apps", "price-web", "local-preview-a11");
const control = path.join(previewRoot, "control.py");
const previewServer = path.join(previewRoot, "preview_server.py");
const evidence = path.join(root, "review", "H10", "evidence");
const screenshots = path.join(evidence, "screenshots");
const domRoot = path.join(evidence, "dom");
const stateDir = path.join(runtime, "launcher-state");
const serverRuntime = path.join(runtime, "server");
const logs = path.join(runtime, "logs");
const privateData = path.join(project, "review", "H10", "private-data");
const database = path.join(privateData, "private_user_observations.sqlite3");
const python = "C:\\Users\\zheny\\AppData\\Local\\Programs\\Python\\Python313\\python.exe";
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 4230;
const expected = {
  a14: "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
  b15: "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
  a10: "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
  b11: "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
  b14: "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9",
  c11: "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa",
};

await Promise.all([mkdir(evidence, { recursive: true }), mkdir(screenshots, { recursive: true }), mkdir(domRoot, { recursive: true }), mkdir(runtime, { recursive: true })]);
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sha256 = async (file) => createHash("sha256").update(await readFile(file)).digest("hex");
const debugPort = await new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once("error", reject);
  probe.listen(0, "127.0.0.1", () => {
    const address = probe.address();
    if (!address || typeof address === "string") { probe.close(); reject(new Error("Unable to allocate CDP port")); return; }
    probe.close((error) => error ? reject(error) : resolve(address.port));
  });
});
const controlledReleases = {
  a10: path.join(project, "review", "releases", "CDH_A_R08_001_REVIEW.zip"),
  b11: path.join(project, "review", "releases", "CDH_B_R07_001_REVIEW.zip"),
  b14: path.join(project, "review", "releases", "CDH_B_R10_001_REVIEW.zip"),
  c11: path.join(project, "review", "releases", "CDH_C_R10_002_REVIEW.zip"),
  b15: path.join(project, "review", "releases", "CDH_B_R11_002_REVIEW.zip"),
};
const baselineBefore = Object.fromEntries(await Promise.all(Object.entries(controlledReleases).map(async ([key, value]) => [key, await sha256(value)])));

async function readyJson(url, attempts = 200) {
  for (let index = 0; index < attempts; index += 1) {
    try { const response = await fetch(url); if (response.ok) return { response, body: await response.json() }; } catch { /* startup */ }
    await wait(100);
  }
  throw new Error(`endpoint not ready: ${url}`);
}
async function waitForExit(child, timeout = 20000) {
  if (child.exitCode !== null) return child.exitCode;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("server process exit timeout")), timeout);
    child.once("exit", (code) => { clearTimeout(timer); resolve(code); });
  });
}
async function startManagedServer(label) {
  await Promise.all([mkdir(stateDir, { recursive: true }), mkdir(serverRuntime, { recursive: true }), mkdir(logs, { recursive: true })]);
  const token = randomBytes(48).toString("base64url");
  const tokenPath = path.join(stateDir, `${label}.token`);
  const instanceId = randomBytes(16).toString("hex");
  await writeFile(tokenPath, `${token}\n`, "utf8");
  const args = [previewServer, "--project-root", project, "--port", String(port), "--runtime-root", serverRuntime, "--token-file", tokenPath, "--instance-id", instanceId, "--private-data-root", privateData];
  const child = spawn(python, args, { cwd: previewRoot, windowsHide: true, stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, PYTHONUTF8: "1" } });
  let stdout = "", stderr = "";
  child.stdout.on("data", (data) => { stdout += data.toString(); });
  child.stderr.on("data", (data) => { stderr += data.toString(); });
  const health = (await readyJson(`http://127.0.0.1:${port}/__cdh/health`)).body;
  if (health.instance_id !== instanceId || health.b15_rev2_sha256 !== expected.b15) {
    child.kill();
    throw new Error(`managed server health identity mismatch: ${JSON.stringify({ health, stdout, stderr })}`);
  }
  const record = { action: "start", command: [python, ...args], result: { status: "READY", instance_id: instanceId, b15_r11_rev2_sha256: health.b15_rev2_sha256 }, stdout, stderr };
  return { child, token, tokenPath, instanceId, health, record, stdout: () => stdout, stderr: () => stderr };
}
async function stopManagedServer(server) {
  const response = await fetch(`http://127.0.0.1:${port}/__cdh/shutdown`, { method: "POST", headers: { "X-CDH-Control-Token": server.token } });
  const payload = await response.json();
  if (response.status !== 202 || payload.instance_id !== server.instanceId) throw new Error(`managed stop rejected: ${response.status} ${JSON.stringify(payload)}`);
  const exitCode = await waitForExit(server.child);
  return { action: "stop", command: ["POST", `http://127.0.0.1:${port}/__cdh/shutdown`], result: { status: "STOPPED", instance_id: server.instanceId, process_exit_code: exitCode }, stdout: server.stdout(), stderr: server.stderr() };
}
async function postJson(url, body, csrf, httpLog) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-CDH-CSRF-Token": csrf }, body: JSON.stringify(body) });
  const payload = await response.json();
  httpLog.push({ method: "POST", url, status: response.status, request: body, response: payload });
  if (!response.ok) throw new Error(`POST failed ${response.status}: ${JSON.stringify(payload)}`);
  return payload;
}
function observation(submissionId, observedAt, before, reported) {
  return {
    schema_version: "CDH-B15-MANUAL-OBSERVATION-1",
    submission_id: submissionId,
    title: "H10 私人重新開啟商品",
    identity: { platform: "COUPANG_TW", product_id: "P-H10-REOPEN", sku_id: "SKU-H10-REOPEN", seller_id: "SELLER-H10", condition: "NEW", package_signature: "EACH-1", currency: "TWD" },
    observed_at: observedAt,
    quantity: 1,
    before_coupon_price_twd: before,
    user_reported_coupon: reported === null
      ? { status: "NONE", price_twd: null, eligibility: "UNKNOWN", evidence_level: "NONE", evidence_note: null, valid_from: null, valid_until: null }
      : { status: "USER_REPORTED", price_twd: reported, eligibility: "UNKNOWN", evidence_level: "NONE", evidence_note: null, valid_from: null, valid_until: null },
    shipping: { status: "UNKNOWN", shipping_fee_twd: null, mandatory_fee_twd: null },
    source: { source_class: "USER_ENTERED", visibility: "PRIVATE_LOCAL", note: "H10 isolated restart journey" },
  };
}
async function saveObservation(base, csrf, body, httpLog) {
  const preview = await postJson(`${base}/api/private-observations/v1/preview`, body, csrf, httpLog);
  if (preview.database_write_count !== 0 || preview.will_save.confirmed_after_coupon_price_twd !== null) throw new Error("unsafe preview contract");
  const commit = await postJson(`${base}/api/private-observations/v1/confirm`, { preview_id: preview.preview_id, confirm_token: preview.confirm_token, explicit_confirm: true }, csrf, httpLog);
  return { preview, commit };
}
function rowCount() {
  const code = "import pathlib,sqlite3,sys; u=pathlib.Path(sys.argv[1]).resolve().as_uri()+'?mode=ro'; c=sqlite3.connect(u,uri=True); print(c.execute('select count(*) from observations').fetchone()[0]); c.close()";
  return Number(execFileSync(python, ["-c", code, database], { windowsHide: true, encoding: "utf8" }).trim());
}
function cdpClient(url) {
  const socket = new WebSocket(url), pending = new Map(), listeners = new Map(); let next = 1;
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) { const call = pending.get(message.id); pending.delete(message.id); message.error ? call.reject(new Error(message.error.message)) : call.resolve(message.result); return; }
    for (const callback of listeners.get(message.method) ?? []) callback(message.params);
  };
  return {
    opened: new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; }),
    send(method, params = {}) { const id = next++; return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); }); },
    on(method, callback) { listeners.set(method, [...(listeners.get(method) ?? []), callback]); },
    close() { socket.close(); },
  };
}

let client, chrome, started = false, activeServer;
const controls = [], seedHttp = [], network = [], consoleEvents = [], captures = [], searchResults = [];
const requestIndex = new Map();
async function evaluate(expression) {
  const response = await client.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text);
  return response.result.value;
}
async function waitFor(expression, label, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) { if (await evaluate(expression)) return; await wait(100); }
  throw new Error(`timeout waiting for ${label}`);
}
async function capture(name) {
  const state = await evaluate(`({url:location.href,text:document.body?.innerText??'',html:document.documentElement.outerHTML,width:innerWidth,scrollWidth:document.documentElement.scrollWidth})`);
  const image = await client.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await writeFile(path.join(screenshots, `${name}.png`), Buffer.from(image.data, "base64"));
  await writeFile(path.join(domRoot, `${name}.html`), state.html, "utf8");
  captures.push({ name, url: state.url, screenshot: `review/H10/evidence/screenshots/${name}.png`, dom: `review/H10/evidence/dom/${name}.html`, horizontal_overflow: state.scrollWidth > state.width });
}
async function searchAndOpen(query, kind, captureName) {
  await evaluate(`(() => { const form=document.querySelector('.private-history-search'); const input=form.querySelector('#private-history-query'); const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; setter.call(input,${JSON.stringify(query)}); input.dispatchEvent(new Event('input',{bubbles:true})); input.dispatchEvent(new Event('change',{bubbles:true})); form.requestSubmit(); })()`);
  await waitFor(`document.querySelectorAll('.private-history-browser .private-product-card').length===1 && document.querySelector('.private-history-browser .result-state')?.innerText.includes('找到 1 個私人商品身分')`, `${kind} search result`);
  await evaluate(`document.querySelector('.private-history-browser .private-product-card').click()`);
  await waitFor(`document.querySelector('[data-private-history-container=true] h3')?.textContent==='H10 私人重新開啟商品'`, `${kind} detail`);
  const value = await evaluate(`(() => {
    const root=document.querySelector('[data-private-history-container=true]');
    const track=(basis)=>root.querySelector('[data-private-history-basis='+basis+']');
    const raw=(basis)=>[...track(basis).querySelectorAll('[data-history-granularity=raw] .history-row')].map(x=>({price:Number(x.dataset.priceTwd),date:x.querySelector('time')?.getAttribute('datetime')??''}));
    const daily=(basis)=>[...track(basis).querySelectorAll('[data-history-granularity=daily] .history-row')].map(x=>({date:x.dataset.taipeiDate,samples:Number(x.dataset.sampleCount),price_text:x.querySelector('strong')?.textContent??''}));
    const privateSection=document.querySelector('.private-history-browser');
    const syntheticSection=document.querySelector('.coupon-workspace');
    return {
      query:${JSON.stringify(query)}, kind:${JSON.stringify(kind)},
      result_count:privateSection.querySelectorAll('.private-product-card').length,
      card_text:privateSection.querySelector('.private-product-card')?.innerText??'',
      title:root.querySelector('h3')?.textContent??'',
      before_raw:raw('before_coupon'), before_daily:daily('before_coupon'),
      confirmed_raw:raw('confirmed_after_coupon'), confirmed_daily:daily('confirmed_after_coupon'),
      reported_raw:raw('user_reported_after_coupon'), reported_daily:daily('user_reported_after_coupon'),
      confirmed_empty_text:track('confirmed_after_coupon').innerText.includes('沒有資料；不以零元或其他軌跡補值。'),
      private_label:root.innerText.includes('PRIVATE_LOCAL_USER_ENTERED'),
      not_platform_verified:root.innerText.includes('NOT PLATFORM VERIFIED'),
      cta_disabled:root.querySelector('button.cta')?.disabled===true,
      private_container_exact:root.getAttribute('data-private-history-container')==='true',
      synthetic_section_present:!!syntheticSection,
      synthetic_outside_private:!!syntheticSection&&!privateSection.contains(syntheticSection),
      b11_banner_outside_private:document.querySelector('.safety-banner')?.innerText.includes('B11 WSGI')===true&&!privateSection.innerText.includes('B11 WSGI'),
      private_contains_synthetic_identity:privateSection.innerText.includes('SYN-PRODUCT')||privateSection.innerText.includes('SYN-SKU'),
      external_links:[...root.querySelectorAll('a[href]')].filter(a=>new URL(a.href).origin!==location.origin).length
    };
  })()`);
  searchResults.push(value);
  await capture(captureName);
  return value;
}

let result;
try {
  if (existsSync(database)) throw new Error("H10 isolated database already exists before single product journey");
  const start1 = await startManagedServer("first"); activeServer = start1; controls.push(start1.record); started = true;
  if (start1.record.result.status !== "READY" || start1.record.result.b15_r11_rev2_sha256 !== expected.b15) throw new Error("first managed start did not bind B15 REV2");
  const health1 = start1.health;
  const base = `http://127.0.0.1:${port}/cdh-private-observations`;
  const sessionResponse = await fetch(`${base}/api/private-observations/v1/session`);
  const session = await sessionResponse.json();
  seedHttp.push({ method: "GET", url: `${base}/api/private-observations/v1/session`, status: sessionResponse.status, response: { schema_version: session.schema_version, csrf_token_present: typeof session.csrf_token === "string" && session.csrf_token.length > 0 } });
  const seed1 = await saveObservation(base, session.csrf_token, observation("H10-SEED-0001", "2026-11-03T12:00:00+08:00", 1000, 900), seedHttp);
  const seed2 = await saveObservation(base, session.csrf_token, observation("H10-SEED-0002", "2026-11-04T12:00:00+08:00", 950, null), seedHttp);
  const stop1 = await stopManagedServer(activeServer); controls.push(stop1); activeServer = undefined; started = false;
  if (stop1.result.status !== "STOPPED") throw new Error("first launcher stop failed");
  const databaseShaBeforeRead = await sha256(database), rowsBeforeRead = rowCount();

  const start2 = await startManagedServer("second"); activeServer = start2; controls.push(start2.record); started = true;
  if (start2.record.result.status !== "READY" || start2.record.result.b15_r11_rev2_sha256 !== expected.b15) throw new Error("second managed start did not bind B15 REV2");
  const health2 = start2.health;
  if (health1.instance_id === health2.instance_id) throw new Error("website instance did not restart");

  chrome = spawn(chromePath, ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", "--remote-debugging-address=127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${path.join(runtime, "chrome-profile")}`, "about:blank"], { cwd: project, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let chromeError = ""; chrome.stderr.on("data", (data) => { chromeError += data.toString(); });
  const tabs = (await readyJson(`http://127.0.0.1:${debugPort}/json`)).body;
  const tab = tabs.find((item) => item.type === "page");
  if (!tab?.webSocketDebuggerUrl) throw new Error(`Chrome CDP unavailable: ${chromeError}`);
  client = cdpClient(tab.webSocketDebuggerUrl); await client.opened;
  await Promise.all([client.send("Page.enable"), client.send("Network.enable"), client.send("Runtime.enable"), client.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false })]);
  client.on("Network.requestWillBeSent", ({ requestId, request }) => { const item = { request_id: requestId, url: request.url, method: request.method, status: null }; requestIndex.set(requestId, item); network.push(item); });
  client.on("Network.responseReceived", ({ requestId, response }) => { const item = requestIndex.get(requestId); if (item) item.status = response.status; });
  client.on("Runtime.consoleAPICalled", (event) => consoleEvents.push({ type: event.type, text: event.args.map((item) => item.value ?? item.description ?? "").join(" ") }));
  client.on("Runtime.exceptionThrown", (event) => consoleEvents.push({ type: "exception", text: event.exceptionDetails.text }));
  await client.send("Page.navigate", { url: `http://127.0.0.1:${port}/?mode=synthetic&contract=v4&h10=1` });
  await waitFor(`document.readyState==='complete'&&!!document.querySelector('#private-history-query')`, "A14 private search UI");
  await capture("01-restarted-private-search-ready");
  await searchAndOpen("H10 私人重新開啟商品", "title", "02-search-by-title");
  await searchAndOpen("P-H10-REOPEN", "product_id", "03-search-by-product-id");
  await searchAndOpen("SKU-H10-REOPEN", "sku", "04-search-by-sku");
  const browserPostAfterRestart = network.filter((item) => item.method === "POST").length;
  const external = network.filter((item) => {
    if (!item.url.startsWith("http:") && !item.url.startsWith("https:")) return false;
    const url = new URL(item.url); return !["127.0.0.1", "localhost"].includes(url.hostname);
  });
  const stop2 = await stopManagedServer(activeServer); controls.push(stop2); activeServer = undefined; started = false;
  if (stop2.result.status !== "STOPPED") throw new Error("second launcher stop failed");
  const databaseShaAfterRead = await sha256(database), rowsAfterRead = rowCount();
  const baselineAfter = Object.fromEntries(await Promise.all(Object.entries(controlledReleases).map(async ([key, value]) => [key, await sha256(value)])));
  const detailed = searchResults.at(-1);
  const sameDetail = searchResults.every((item) => JSON.stringify({ ...item, query: "", kind: "" }) === JSON.stringify({ ...detailed, query: "", kind: "" }));
  const gates = {
    exact_inputs: baselineBefore.a10 === expected.a10 && baselineBefore.b11 === expected.b11 && baselineBefore.b14 === expected.b14 && baselineBefore.c11 === expected.c11 && baselineBefore.b15 === expected.b15,
    launcher_restart: health1.instance_id !== health2.instance_id && controls.map((item) => item.result.status).join(",") === "READY,STOPPED,READY,STOPPED",
    two_seed_commits: seed1.commit.idempotent_replay === false && seed2.commit.idempotent_replay === false && rowsBeforeRead === 2,
    searches_by_three_fields: searchResults.length === 3 && searchResults.map((item) => item.kind).join(",") === "title,product_id,sku" && searchResults.every((item) => item.result_count === 1),
    same_detail_from_three_queries: sameDetail,
    exact_private_container: searchResults.every((item) => item.private_container_exact),
    before_raw: JSON.stringify(detailed.before_raw.map((item) => item.price)) === "[1000,950]",
    before_daily: JSON.stringify(detailed.before_daily.map((item) => [item.date, item.samples, item.price_text])) === JSON.stringify([["2026-11-03", 1, "NT$1,000"], ["2026-11-04", 1, "NT$950"]]),
    confirmed_empty: detailed.confirmed_raw.length === 0 && detailed.confirmed_daily.length === 0 && detailed.confirmed_empty_text,
    reported_raw: JSON.stringify(detailed.reported_raw.map((item) => item.price)) === "[900]",
    reported_daily: JSON.stringify(detailed.reported_daily.map((item) => [item.date, item.samples, item.price_text])) === JSON.stringify([["2026-11-03", 1, "NT$900"]]),
    read_only_after_restart: browserPostAfterRestart === 0 && rowsAfterRead === rowsBeforeRead && databaseShaAfterRead === databaseShaBeforeRead,
    private_synthetic_separation: searchResults.every((item) => item.synthetic_section_present && item.synthetic_outside_private && item.b11_banner_outside_private && !item.private_contains_synthetic_identity),
    reported_not_confirmed: detailed.reported_raw.length === 1 && detailed.confirmed_raw.length === 0 && detailed.not_platform_verified,
    cta_disabled: searchResults.every((item) => item.cta_disabled && item.external_links === 0),
    no_external_requests: external.length === 0,
    no_console_exceptions: consoleEvents.filter((item) => item.type === "exception").length === 0,
    no_horizontal_overflow: captures.every((item) => !item.horizontal_overflow),
    baseline_immutable: JSON.stringify(baselineBefore) === JSON.stringify(baselineAfter),
  };
  result = {
    schema_version: "CDH-H10-ACTUAL-BROWSER-E2E-1",
    task_id: "CDH-H10-PRIVATE-HISTORY-REOPEN-E2E-001",
    created_at_utc: new Date().toISOString(),
    status: Object.values(gates).every(Boolean) ? "PASS" : "FAIL",
    browser_test_exit_code: Object.values(gates).every(Boolean) ? 0 : 1,
    exact_dependencies: { a14_sha256: expected.a14, b15_rev2_sha256: expected.b15 },
    integration: "ACTUAL_A14_UI_TO_B15_REV2_LOCAL_API",
    isolated_private_data_root: path.relative(root, privateData).replaceAll("\\", "/"),
    formal_database_write_count: 0,
    website_restart_count: 1,
    first_instance_id: health1.instance_id,
    second_instance_id: health2.instance_id,
    controls,
    seed_http: seedHttp,
    rows_before_read: rowsBeforeRead,
    rows_after_read: rowsAfterRead,
    database_sha256_before_read: databaseShaBeforeRead,
    database_sha256_after_read: databaseShaAfterRead,
    database_unchanged_by_read: databaseShaBeforeRead === databaseShaAfterRead,
    browser_post_after_restart_count: browserPostAfterRestart,
    search_results: searchResults,
    captures,
    network,
    external_request_count: external.length,
    console_events: consoleEvents,
    baseline_before: baselineBefore,
    baseline_after: baselineAfter,
    gates,
  };
  await writeFile(path.join(evidence, "ACTUAL_H10_BROWSER_HTTP.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ status: result.status, gates, rows: rowsAfterRead, browser_post_after_restart_count: browserPostAfterRestart, captures: captures.length }));
  process.exitCode = result.browser_test_exit_code;
} catch (error) {
  result = { schema_version: "CDH-H10-ACTUAL-BROWSER-E2E-1", task_id: "CDH-H10-PRIVATE-HISTORY-REOPEN-E2E-001", created_at_utc: new Date().toISOString(), status: "FAIL", browser_test_exit_code: 1, error: error.stack ?? String(error), controls, seed_http: seedHttp, search_results: searchResults, captures, network, console_events: consoleEvents };
  await writeFile(path.join(evidence, "ACTUAL_H10_BROWSER_HTTP.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.error(error.stack ?? String(error));
  process.exitCode = 1;
} finally {
  if (client) client.close();
  if (chrome && chrome.exitCode === null) chrome.kill();
  if (started && activeServer) try { controls.push(await stopManagedServer(activeServer)); } catch { if (activeServer.child.exitCode === null) activeServer.child.kill(); }
}
