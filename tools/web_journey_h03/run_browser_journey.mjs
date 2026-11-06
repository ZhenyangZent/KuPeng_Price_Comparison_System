import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const toolRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(toolRoot, "../..");
const frontend = process.argv.includes("--frontend=A08") ? "A08" : "A07";
const backend = process.argv.includes("--backend=B09") ? "B09" : "B08";
const pair = `${frontend}_${backend}`;
const runtime = path.join(projectRoot, "review", "H03", "runtime");
const evidence = path.join(projectRoot, "review", "H03", "evidence");
const screenshots = path.join(evidence, "screenshots");
const viteBin = path.join(projectRoot, "apps", "price-web", "frontend", "node_modules", "vite", "bin", "vite.js");
const viteConfig = path.join(toolRoot, "h03.vite.config.mjs");
const reportRoot = path.join(runtime, `integration-report-${pair}`);
const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const vitePort = 4174;
const reportPort = 8766;
const debugPort = 9326;

await Promise.all([mkdir(runtime, { recursive: true }), mkdir(evidence, { recursive: true }), mkdir(screenshots, { recursive: true })]);
const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function waitForHttp(url) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try { if ((await fetch(url)).ok) return; } catch { /* local process not ready */ }
    await wait(100);
  }
  throw new Error(`Local endpoint did not become ready: ${url}`);
}
async function waitForJson(url) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try { const response = await fetch(url); if (response.ok) return response.json(); } catch { /* local process not ready */ }
    await wait(100);
  }
  throw new Error(`Local JSON endpoint did not become ready: ${url}`);
}
function spawnLocal(command, args, extraEnv = {}) {
  const child = spawn(command, args, { cwd: projectRoot, env: { ...process.env, ...extraEnv }, shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  const logs = { stdout: "", stderr: "" };
  child.stdout.on("data", (data) => { logs.stdout += data.toString(); });
  child.stderr.on("data", (data) => { logs.stderr += data.toString(); });
  return { child, logs };
}
function cdpClient(webSocketUrl) {
  const socket = new WebSocket(webSocketUrl);
  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message)); else resolve(message.result);
      return;
    }
    for (const listener of listeners.get(message.method) ?? []) listener(message.params);
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
    on(method, callback) { listeners.set(method, [...(listeners.get(method) ?? []), callback]); },
    close() { socket.close(); }
  };
}

const vite = spawnLocal(process.execPath, [viteBin, "serve", "--config", viteConfig, "--host", "127.0.0.1", "--port", String(vitePort), "--strictPort"], { H03_FRONTEND: frontend });
const reportServer = spawnLocal(process.execPath, [path.join(toolRoot, "static_server.mjs"), reportRoot, String(reportPort)]);
const chromeProfile = path.join(runtime, `chrome-h03-profile-${process.pid}`);
const chromeProcess = spawnLocal(chrome, [
  "--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync",
  "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito",
  "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", "--remote-debugging-address=127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${chromeProfile}`, "about:blank"
]);

const requests = new Map();
const consoleEvents = [];
const results = [];
let cdp;
try {
  await Promise.all([waitForHttp(`http://127.0.0.1:${vitePort}/`), waitForHttp(`http://127.0.0.1:${reportPort}/`)]);
  const tabs = await waitForJson(`http://127.0.0.1:${debugPort}/json`);
  const tab = tabs.find((item) => item.type === "page");
  if (!tab?.webSocketDebuggerUrl) throw new Error("Chrome page target was not available");
  cdp = cdpClient(tab.webSocketDebuggerUrl);
  await cdp.opened;
  await Promise.all([cdp.send("Page.enable"), cdp.send("Runtime.enable"), cdp.send("Network.enable")]);
  cdp.on("Network.requestWillBeSent", (event) => requests.set(event.requestId, { request_id: event.requestId, url: event.request.url, method: event.request.method, type: event.type, timestamp: event.timestamp }));
  cdp.on("Network.responseReceived", (event) => Object.assign(requests.get(event.requestId) ?? {}, { status: event.response.status, mime_type: event.response.mimeType, remote_ip: event.response.remoteIPAddress }));
  cdp.on("Runtime.consoleAPICalled", (event) => consoleEvents.push({ type: event.type, text: event.args.map((arg) => arg.value ?? arg.description ?? "").join(" ") }));
  cdp.on("Runtime.exceptionThrown", (event) => consoleEvents.push({ type: "exception", text: event.exceptionDetails.text }));

  async function navigate(item) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: item.width, height: item.height, deviceScaleFactor: 1, mobile: item.mobile });
    await cdp.send("Page.navigate", { url: item.url });
    await wait(item.wait ?? 900);
    const actionEvidence = item.action ? await item.action() : null;
    const evaluation = await cdp.send("Runtime.evaluate", {
      expression: `({html:document.documentElement.outerHTML,text:document.body.innerText,innerWidth:innerWidth,scrollWidth:document.documentElement.scrollWidth,url:location.href,disabledAffiliate:[...document.querySelectorAll('button.cta:disabled')].length,outboundAffiliate:[...document.querySelectorAll('a.cta[href]')].length,alerts:[...document.querySelectorAll('[role=alert]')].map(x=>x.innerText),active:document.activeElement?.outerHTML??''})`,
      returnByValue: true
    });
    const state = evaluation.result.value;
    const missing = item.required.filter((text) => !state.text.includes(text));
    const forbidden = item.forbidden.filter((text) => state.text.includes(text));
    const shot = path.join(screenshots, `${item.name}.png`);
    const captured = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(shot, Buffer.from(captured.data, "base64"));
    await writeFile(path.join(evidence, `${item.name}.dom.html`), state.html, "utf8");
    const pass = missing.length === 0 && forbidden.length === 0 && state.scrollWidth <= state.innerWidth && (item.requireDisabledAffiliate ? state.disabledAffiliate > 0 && state.outboundAffiliate === 0 : true) && (item.extraPass ? item.extraPass(state, actionEvidence) : true);
    results.push({ case: item.name, url: state.url, viewport: `${item.width}x${item.height}`, required_text_missing: missing, forbidden_text_present: forbidden, no_horizontal_overflow: state.scrollWidth <= state.innerWidth, disabled_affiliate_button_count: state.disabledAffiliate, outbound_affiliate_anchor_count: state.outboundAffiliate, alerts: state.alerts, action_evidence: actionEvidence, active_element: state.active, screenshot: path.relative(projectRoot, shot).replaceAll("\\", "/"), pass });
  }

  await navigate({
    name: `${pair.toLowerCase()}-synthetic-zero-desktop`, width: 1440, height: 1000, mobile: false,
    url: `http://127.0.0.1:${vitePort}/?mode=synthetic&product=syn-earbuds-white`,
    required: ["SYNTHETIC FIXTURE ONLY", "NT$0 是記錄價格", "UNKNOWN", "RAW OBSERVATIONS", "尚未取得可驗證的專屬連結"], forbidden: ["LOCAL LOOPBACK · READ ONLY"], requireDisabledAffiliate: true,
    action: async () => {
      await cdp.send("Runtime.evaluate", { expression: `(()=>{const i=document.querySelector('#product-search');i.focus();i.select();return true})()` });
      for (const character of "SYN-EARBUD-WHT") await cdp.send("Input.dispatchKeyEvent", { type: "char", text: character, unmodifiedText: character });
      const typed = await cdp.send("Runtime.evaluate", { expression: `document.querySelector('#product-search')?.value??null`, returnByValue: true });
      await cdp.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
      await cdp.send("Input.dispatchKeyEvent", { type: "char", key: "Enter", code: "Enter", text: "\r", unmodifiedText: "\r", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
      await wait(350);
      const searched = await cdp.send("Runtime.evaluate", { expression: `({url:location.href,title:document.querySelector('.detail-header h2')?.textContent??null,result:document.querySelector('.result-state')?.textContent??null})`, returnByValue: true });
      const retry = await cdp.send("Runtime.evaluate", { expression: `(()=>{const b=Array.from(document.querySelectorAll('button')).find(x=>x.textContent==='重新擷取');if(!b)return false;b.click();return true})()`, returnByValue: true });
      await wait(250);
      await cdp.send("Runtime.evaluate", { expression: `document.querySelector('#product-search')?.focus()` });
      await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab" });
      await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab" });
      const focused = await cdp.send("Runtime.evaluate", { expression: `({tag:document.activeElement?.tagName??null,text:document.activeElement?.textContent?.trim()??null})`, returnByValue: true });
      return { typed_query: typed.result.value, search_keyboard_enter: searched.result.value, retry_button_clicked: retry.result.value, keyboard_tab_active: focused.result.value };
    },
    extraPass: (_state, action) => action?.typed_query === "SYN-EARBUD-WHT" && action?.search_keyboard_enter?.url?.includes("q=SYN-EARBUD-WHT") && action?.search_keyboard_enter?.title?.includes("無線耳機") && action?.retry_button_clicked === true && action?.keyboard_tab_active?.tag === "BUTTON" && action?.keyboard_tab_active?.text === "搜尋紀錄"
  });
  await navigate({
    name: `${pair.toLowerCase()}-synthetic-empty-mobile`, width: 390, height: 844, mobile: true,
    url: `http://127.0.0.1:${vitePort}/?mode=synthetic&product=syn-empty`,
    required: frontend === "A08" ? ["SYNTHETIC FIXTURE ONLY", "價格不可用", "尚無價格樣本；空值不會補成 NT$0", "尚未取得可驗證的專屬連結"] : ["SYNTHETIC FIXTURE ONLY", "價格未知", "尚無價格樣本；空值不會補成 NT$0", "尚未取得可驗證的專屬連結"], forbidden: ["NT$0 是記錄價格"], requireDisabledAffiliate: true
  });
  if (frontend === "A08") await navigate({
    name: `${pair.toLowerCase()}-synthetic-stale-desktop`, width: 1280, height: 900, mobile: false,
    url: `http://127.0.0.1:${vitePort}/?mode=synthetic&product=syn-cable`,
    required: ["SYNTHETIC FIXTURE ONLY", "SYNTHETIC｜USB-C 充電線", "STALE · 可重新擷取", "過期觀測", "NT$ 159", "RAW OBSERVATIONS", "尚未取得可驗證的專屬連結"],
    forbidden: ["PRICE UNAVAILABLE", "此商品沒有適用、可比的價格", "前往已核准的同一商品"], requireDisabledAffiliate: true
  });
  await navigate({
    name: `${pair.toLowerCase()}-integration-desktop`, width: 1440, height: 1050, mobile: false,
    url: `http://127.0.0.1:${reportPort}/`,
    required: frontend === "A08" && backend === "B09" ? ["A08 × B09 契約整合驗證", "9 PASS", "0 FAIL", "價格不可用（UNAVAILABLE）", "PRODUCT INTEGRATION: PASS"] : ["A07 × B08 契約整合重現", "6 PASS", "3 FAIL", "價格不可用（UNAVAILABLE）", "觀測期間低點與逐筆歷史不一致", "PRODUCT INTEGRATION: FAIL"], forbidden: frontend === "A08" && backend === "B09" ? ["PRODUCT INTEGRATION: FAIL", "DEFECT REPRODUCED"] : ["PRODUCT INTEGRATION: PASS"], requireDisabledAffiliate: false
  });
  await navigate({
    name: `${pair.toLowerCase()}-integration-mobile`, width: 390, height: 844, mobile: true,
    url: `http://127.0.0.1:${reportPort}/`,
    required: frontend === "A08" && backend === "B09" ? ["A08 × B09 契約整合驗證", "9 PASS", "PRODUCT INTEGRATION: PASS"] : ["A07 × B08 契約整合重現", "3 FAIL", "DEFECT REPRODUCED"], forbidden: frontend === "A08" && backend === "B09" ? ["PRODUCT INTEGRATION: FAIL", "DEFECT REPRODUCED"] : ["PRODUCT INTEGRATION: PASS"], requireDisabledAffiliate: false
  });
} catch (error) {
  const diagnostic = { error: error instanceof Error ? error.stack : String(error), vite: vite.logs, report_server: reportServer.logs, chrome: chromeProcess.logs };
  await writeFile(path.join(evidence, `BROWSER_STARTUP_DIAGNOSTIC_${pair}.json`), `${JSON.stringify(diagnostic, null, 2)}\n`, "utf8");
  throw new Error(`${error instanceof Error ? error.message : error}\nVITE STDERR: ${vite.logs.stderr}\nVITE STDOUT: ${vite.logs.stdout}`);
} finally {
  if (cdp) cdp.close();
  chromeProcess.child.kill();
  vite.child.kill();
  reportServer.child.kill();
}

const networkEntries = [...requests.values()].sort((a, b) => a.timestamp - b.timestamp);
const external = networkEntries.filter((entry) => {
  try { return new URL(entry.url).hostname !== "127.0.0.1" && !entry.url.startsWith("data:"); } catch { return true; }
});
const har = {
  log: { version: "1.2", creator: { name: "CDH-H03-CDP", version: "1" }, entries: networkEntries },
  scope: "LOCALHOST_ONLY_HEADLESS_CHROME",
  external_request_count: external.length,
  external_requests: external
};
await writeFile(path.join(evidence, `NETWORK_HAR_${pair}.json`), `${JSON.stringify(har, null, 2)}\n`, "utf8");
const summary = {
  task_id: "CDH-H03-A07-B08-INTEGRATION-JOURNEY-001",
  authority: "AUTHORIZED_SYNTHETIC_OFFLINE_ONLY",
  browser: chrome,
  frontend,
  backend,
  exact_frontend_source: `review/H03/baselines/${frontend}/CDH_${frontend}_001_REVIEW/apps/price-web/frontend`,
  integration_report_source: `review/H03/runtime/${pair}_CONTRACT_RESULTS.json`,
  results,
  network: { request_count: networkEntries.length, external_request_count: external.length },
  console_events: consoleEvents,
  process_logs: { vite: vite.logs, report_server: reportServer.logs, chrome_stderr: chromeProcess.logs.stderr },
  all_journeys_pass: results.length === (frontend === "A08" ? 5 : 4) && results.every((item) => item.pass) && external.length === 0 && !consoleEvents.some((item) => item.type === "exception")
};
await writeFile(path.join(evidence, `BROWSER_JOURNEY_${pair}.json`), `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ all_journeys_pass: summary.all_journeys_pass, cases: results.map((item) => ({ case: item.case, pass: item.pass })), external_requests: external.length }));
process.exitCode = summary.all_journeys_pass ? 0 : 1;
