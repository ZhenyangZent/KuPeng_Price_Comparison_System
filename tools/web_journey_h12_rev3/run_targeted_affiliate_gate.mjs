import { createHash } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const tools = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(tools, "../..");
const attempt = path.join(root, "review", "H12_REV3");
const runtime = path.join(attempt, "runtime");
const project = path.join(runtime, "project");
const evidence = path.join(attempt, "evidence");
const screenshots = path.join(evidence, "screenshots");
const domRoot = path.join(evidence, "dom");
const state = path.join(project, "data", "local_mvp", "state");
const database = path.join(project, "data", "private_user_observations_b15", "private_user_observations.sqlite3");
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 12340;
const expected = {
  a16: "8eba2b5059c92fcd71897ee345527c78741ebe6c3230c45eab87dd4921b339e4",
  b16: "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
  h12Rev2: "df490f54ff4315e2c4171248464040e02ce2eef58265d1e5c3f88e4854294b80",
};
await Promise.all([mkdir(evidence, { recursive: true }), mkdir(screenshots, { recursive: true }), mkdir(domRoot, { recursive: true }), mkdir(state, { recursive: true })]);

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sha256 = async (file) => createHash("sha256").update(await readFile(file)).digest("hex");
const launcherReceipts = [];
const runControl = (action) => {
  const cmd = path.join(project, `${action[0].toUpperCase()}${action.slice(1)}-CDH-MVP.cmd`);
  const line = `call ${path.basename(cmd)} -Port ${port} -MachineReadable`;
  const executed = spawnSync("cmd.exe", ["/d", "/c", line], {
    cwd: project,
    windowsHide: true,
    encoding: "utf8",
    env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" },
    timeout: 30000,
  });
  const output = `${executed.stdout ?? ""}\n${executed.stderr ?? ""}`;
  const jsonLine = output.split(/\r?\n/).map((value) => value.trim()).reverse().find((value) => value.startsWith("{") && value.endsWith("}"));
  const payload = jsonLine ? JSON.parse(jsonLine) : { status: "FAILED", error: output.trim() };
  launcherReceipts.push({ action, entry: path.basename(cmd), exit_code: executed.status, signal: executed.signal, payload, stdout: executed.stdout ?? "", stderr: executed.stderr ?? "" });
  if (executed.error || executed.status !== 0) throw new Error(`${action} launcher failed: ${executed.error?.message ?? output}`);
  return payload;
};
const debugPort = await new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once("error", reject);
  probe.listen(0, "127.0.0.1", () => {
    const address = probe.address();
    if (!address || typeof address === "string") return reject(new Error("unable to allocate CDP port"));
    probe.close((error) => error ? reject(error) : resolve(address.port));
  });
});

async function waitForJson(url) {
  for (let index = 0; index < 200; index += 1) {
    try { const response = await fetch(url); if (response.ok) return response.json(); } catch { /* startup */ }
    await wait(100);
  }
  throw new Error(`endpoint not ready: ${url}`);
}
function cdpClient(url) {
  const socket = new WebSocket(url), pending = new Map(), listeners = new Map(); let next = 1;
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const call = pending.get(message.id); pending.delete(message.id);
      message.error ? call.reject(new Error(message.error.message)) : call.resolve(message.result); return;
    }
    for (const callback of listeners.get(message.method) ?? []) callback(message.params);
  });
  return {
    opened: new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); }),
    send(method, params = {}) { const id = next++; return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); }); },
    once(method) { return new Promise((resolve) => { const callback = (params) => { listeners.set(method, (listeners.get(method) ?? []).filter((item) => item !== callback)); resolve(params); }; listeners.set(method, [...(listeners.get(method) ?? []), callback]); }); },
    on(method, callback) { listeners.set(method, [...(listeners.get(method) ?? []), callback]); },
    close() { socket.close(); },
  };
}
async function evaluate(client, expression) {
  const response = await client.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text);
  return response.result.value;
}

let started = false, chrome, client;
const requests = new Map(), network = [], consoleEvents = [], loadSamples = [];
let result;
try {
  if (existsSync(database)) throw new Error("targeted REV3 workspace unexpectedly contains a private database");
  const h12Rev2Path = path.join(root, "review", "releases", "CDH_H_R12_004_REVIEW.zip");
  if (await sha256(h12Rev2Path) !== expected.h12Rev2) throw new Error("H12 REV2 evidence ZIP identity mismatch");
  const start = runControl("start"); started = true;
  if (start.status !== "READY" || start.b16_r12_sha256 !== expected.b16) throw new Error(`formal launcher identity mismatch: ${JSON.stringify(start)}`);
  const status = runControl("status");
  if (status.status !== "READY") throw new Error(`formal status failed: ${JSON.stringify(status)}`);
  const health = await waitForJson(`http://127.0.0.1:${port}/__cdh/health`);
  if (health.b16_r12_sha256 !== expected.b16 || health.b16_revision !== "REV3") throw new Error("B16 REV3 health identity mismatch");

  chrome = spawn(chromePath, [
    "--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito",
    "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", "--remote-debugging-address=127.0.0.1", `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${path.join(runtime, "chrome-profile")}`, "about:blank",
  ], { cwd: project, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let chromeError = ""; chrome.stderr.on("data", (data) => { chromeError += data.toString(); });
  const tabs = await waitForJson(`http://127.0.0.1:${debugPort}/json`), tab = tabs.find((item) => item.type === "page");
  if (!tab?.webSocketDebuggerUrl) throw new Error(`Chrome CDP unavailable: ${chromeError}`);
  client = cdpClient(tab.webSocketDebuggerUrl); await client.opened;
  await Promise.all([client.send("Page.enable"), client.send("Network.enable"), client.send("Runtime.enable"), client.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })]);
  client.on("Network.requestWillBeSent", ({ requestId, request }) => { requests.set(requestId, { url: request.url, method: request.method }); });
  client.on("Network.responseReceived", ({ requestId, response }) => { const request = requests.get(requestId); if (request) network.push({ ...request, status: response.status }); });
  client.on("Runtime.consoleAPICalled", (event) => consoleEvents.push({ type: event.type, text: event.args.map((item) => item.value ?? item.description ?? "").join(" ") }));
  client.on("Runtime.exceptionThrown", (event) => consoleEvents.push({ type: "exception", text: event.exceptionDetails.text }));

  const loaded = client.once("Page.loadEventFired");
  await client.send("Page.navigate", { url: `http://127.0.0.1:${port}/?mode=synthetic&contract=v4&h12rev3=1` });
  const deadline = Date.now() + 20000;
  let finalState = null;
  while (Date.now() < deadline) {
    const sample = await evaluate(client, `(() => {
      const guide=document.querySelector('[aria-label="價格資料分類說明"]');
      const card=document.querySelector('.affiliate-card.coupon-cta');
      const cta=card?.querySelector('button.cta')??null;
      const external=[...document.querySelectorAll('a[href]')].filter(a=>{try{return !['127.0.0.1','localhost'].includes(new URL(a.href).hostname)}catch{return true}});
      const affiliateAnchors=card?[...card.querySelectorAll('a[href]')]:[];
      return {
        at:performance.now(),
        classification_cards:guide?.children.length??0,
        classification_text:guide?.innerText??'',
        batch_ready:!!document.querySelector('#batch-import-file'),
        manual_ready:!!document.querySelector('.manual-observation-panel'),
        private_history_ready:!!document.querySelector('#private-history-query'),
        affiliate_card_count:document.querySelectorAll('.affiliate-card.coupon-cta').length,
        cta_count:document.querySelectorAll('.affiliate-card.coupon-cta button.cta').length,
        cta_disabled:cta?cta.disabled:null,
        cta_text:cta?.textContent.trim()??null,
        enabled_affiliate_button_count:document.querySelectorAll('.affiliate-card.coupon-cta button:not([disabled])').length,
        affiliate_anchor_count:affiliateAnchors.length,
        external_anchor_count:external.length,
      };
    })()`);
    loadSamples.push(sample);
    const productListReady = network.some((item) => item.status === 200 && item.url.includes('/api/v4/products?'));
    const productDetailReady = network.some((item) => item.status === 200 && item.url.includes('/api/v4/products/already-included'));
    const classificationReady = sample.classification_cards === 3 && sample.classification_text.includes("SYNTHETIC DEMO") && sample.classification_text.includes("PRIVATE USER-REPORTED") && sample.classification_text.includes("PLATFORM CONFIRMED");
    if (classificationReady && sample.batch_ready && sample.manual_ready && sample.private_history_ready && productListReady && productDetailReady && sample.cta_count > 0) { finalState = sample; break; }
    await wait(25);
  }
  await loaded;
  if (!finalState) throw new Error("timed out waiting for classification, required APIs, and an explicit affiliate CTA");
  const actionableDuringLoad = loadSamples.filter((item) => item.enabled_affiliate_button_count > 0 || item.affiliate_anchor_count > 0 || item.external_anchor_count > 0);
  const finalDom = await evaluate(client, `document.documentElement.outerHTML`);
  const screenshot = await client.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await writeFile(path.join(domRoot, "01-affiliate-gate-ready.html"), finalDom, "utf8");
  await writeFile(path.join(screenshots, "01-affiliate-gate-ready.png"), Buffer.from(screenshot.data, "base64"));
  const externalRequests = network.filter((item) => (item.url.startsWith("http:") || item.url.startsWith("https:")) && !["127.0.0.1", "localhost"].includes(new URL(item.url).hostname));
  const gates = {
    exact_a16_b16_identity: start.b16_r12_sha256 === expected.b16 && health.b16_r12_sha256 === expected.b16,
    formal_root_cmd_ready: start.status === "READY" && status.status === "READY" && launcherReceipts.every((item) => item.exit_code === 0 && item.stderr === ""),
    classification_and_required_api_ready: finalState.classification_cards === 3 && network.some((item) => item.status === 200 && item.url.includes('/api/v4/products?')) && network.some((item) => item.status === 200 && item.url.includes('/api/v4/products/already-included')),
    no_actionable_affiliate_during_load: actionableDuringLoad.length === 0,
    explicit_affiliate_button_present: finalState.affiliate_card_count > 0 && finalState.cta_count > 0,
    explicit_affiliate_button_disabled: finalState.cta_disabled === true && finalState.enabled_affiliate_button_count === 0,
    no_trusted_or_external_affiliate_link: finalState.affiliate_anchor_count === 0 && finalState.external_anchor_count === 0 && externalRequests.length === 0,
    no_private_database_created: !existsSync(database),
    no_console_exception: consoleEvents.filter((item) => item.type === "exception").length === 0,
  };
  const chromeExit = new Promise((resolve) => chrome.once("exit", (code, signal) => resolve([code, signal])));
  await client.send("Browser.close"); client = undefined;
  const [chromeExitCode, chromeExitSignal] = await chromeExit; chrome = undefined;
  const stop = runControl("stop"); started = false;
  const stopped = runControl("status");
  const passed = Object.values(gates).every(Boolean) && chromeExitCode === 0 && stop.status === "STOPPED" && stopped.status === "STOPPED";
  result = {
    schema_version: "CDH-H12-REV3-TARGETED-AFFILIATE-GATE-1",
    task_id: "CDH-H12-LOCAL-MVP-FIRST-USE-001",
    revision: "REV3",
    created_at_utc: new Date().toISOString(),
    status: passed ? "PASS" : "FAIL",
    scope: "TARGETED_FIRST_USE_CONTROLS_AND_CLASSIFICATION_ONLY",
    single_run_full_17_gate_claimed: false,
    prior_h12_rev2_product_gate_pass_count: 16,
    prior_h12_rev2_product_gate_count: 17,
    prior_h12_rev2_browser_test_exit_code: 1,
    targeted_gate_pass_count: Object.values(gates).filter(Boolean).length,
    targeted_gate_count: Object.keys(gates).length,
    targeted_browser_test_exit_code: passed ? 0 : 1,
    chrome_process_exit_code: chromeExitCode,
    chrome_process_exit_signal: chromeExitSignal,
    exact_dependencies: { a16_rev2_sha256: expected.a16, b16_rev3_sha256: expected.b16, h12_rev2_sha256: expected.h12Rev2 },
    health: { b16_r12_sha256: health.b16_r12_sha256, b16_revision: health.b16_revision, b16_api_schema: health.b16_api_schema },
    root_cmd_launcher_used: true,
    h_test_loader_used: false,
    final_state: finalState,
    load_sample_count: loadSamples.length,
    load_samples: loadSamples,
    actionable_during_load_count: actionableDuringLoad.length,
    network,
    external_request_count: externalRequests.length,
    console_events: consoleEvents,
    private_database_created: existsSync(database),
    gates,
    launcher_receipts: launcherReceipts,
    final_stop: stop,
    final_status: stopped,
    evidence: { dom: "evidence/dom/01-affiliate-gate-ready.html", screenshot: "evidence/screenshots/01-affiliate-gate-ready.png" },
  };
  await writeFile(path.join(evidence, "TARGETED_AFFILIATE_GATE.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ status: result.status, gates, samples: loadSamples.length, actionable_during_load_count: actionableDuringLoad.length, chrome_process_exit_code: chromeExitCode }));
  process.exitCode = result.targeted_browser_test_exit_code;
} catch (error) {
  result = {
    schema_version: "CDH-H12-REV3-TARGETED-AFFILIATE-GATE-1",
    task_id: "CDH-H12-LOCAL-MVP-FIRST-USE-001",
    revision: "REV3",
    created_at_utc: new Date().toISOString(),
    status: "FAIL",
    scope: "TARGETED_FIRST_USE_CONTROLS_AND_CLASSIFICATION_ONLY",
    single_run_full_17_gate_claimed: false,
    targeted_browser_test_exit_code: 1,
    error: error.stack ?? String(error),
    launcher_receipts: launcherReceipts,
    network,
    console_events: consoleEvents,
    load_samples: loadSamples,
  };
  await writeFile(path.join(evidence, "TARGETED_AFFILIATE_GATE.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.error(error.stack ?? String(error));
  process.exitCode = 1;
} finally {
  if (client) client.close();
  if (chrome && chrome.exitCode === null) chrome.kill();
  if (started) try { runControl("stop"); } catch { /* preserve failure evidence */ }
}
