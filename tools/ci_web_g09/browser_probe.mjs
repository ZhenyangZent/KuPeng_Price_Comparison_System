import { spawn } from "node:child_process";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const args = Object.fromEntries(process.argv.slice(2).reduce((all, value, index, values) => index % 2 === 0 ? [...all, [value.replace(/^--/, ""), values[index + 1]]] : all, []));
const { chrome, base, output, "debug-port": debugPortText } = args;
if (![chrome, base, output, debugPortText].every(Boolean)) process.exit(64);
const debugPort = Number(debugPortText), wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const screenshots = path.join(output, "screenshots"), domRoot = path.join(output, "dom"), profile = path.join(output, "..", "runtime", "chrome-profile");
await Promise.all([mkdir(screenshots, { recursive: true }), mkdir(domRoot, { recursive: true }), rm(profile, { recursive: true, force: true })]);

async function json(url) { for (let i = 0; i < 100; i += 1) { try { const response = await fetch(url); if (response.ok) return response.json(); } catch {} await wait(100); } throw new Error(`endpoint unavailable: ${url}`); }
function client(url) {
  const socket = new WebSocket(url), pending = new Map(), listeners = new Map(); let id = 1;
  socket.addEventListener("message", (event) => { const message = JSON.parse(event.data); if (message.id && pending.has(message.id)) { const item = pending.get(message.id); pending.delete(message.id); message.error ? item.reject(new Error(message.error.message)) : item.resolve(message.result); return; } for (const fn of listeners.get(message.method) ?? []) fn(message.params); });
  return { opened: new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); }), send(method, params = {}) { const current = id++; return new Promise((resolve, reject) => { pending.set(current, { resolve, reject }); socket.send(JSON.stringify({ id: current, method, params })); }); }, on(method, fn) { listeners.set(method, [...(listeners.get(method) ?? []), fn]); }, close() { socket.close(); } };
}

const labels = { raw_before: "B10 券前商品價歷史", raw_after: "B10 已確認券後商品價歷史", daily_before: "B11 券前每日代表價", daily_after: "B11 已確認券後每日代表價" };
const chromeArgs = ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, "about:blank"];
const processChrome = spawn(chrome, chromeArgs, { shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] }); let chromeStderr = ""; processChrome.stderr.on("data", (value) => { chromeStderr += value.toString(); });
const network = [], requestMap = new Map(), bodyPromises = [], consoleEntries = [];
let confirmed, unavailable, browserVersion;
try {
  const tabs = await json(`http://127.0.0.1:${debugPort}/json`), tab = tabs.find((item) => item.type === "page"); if (!tab?.webSocketDebuggerUrl) throw new Error("Chrome page target unavailable");
  const cdp = client(tab.webSocketDebuggerUrl); await cdp.opened; await Promise.all([cdp.send("Page.enable"), cdp.send("Runtime.enable"), cdp.send("Network.enable"), cdp.send("Log.enable")]); browserVersion = await cdp.send("Browser.getVersion");
  cdp.on("Runtime.exceptionThrown", (event) => consoleEntries.push({ type: "exception", text: event.exceptionDetails?.text ?? "unknown" })); cdp.on("Log.entryAdded", (event) => consoleEntries.push({ type: event.entry.level, text: event.entry.text, url: event.entry.url }));
  cdp.on("Network.requestWillBeSent", (event) => requestMap.set(event.requestId, { startedDateTime: new Date().toISOString(), request: { method: event.request.method, url: event.request.url, headers: event.request.headers } }));
  cdp.on("Network.responseReceived", (event) => { const item = requestMap.get(event.requestId); if (item) item.response = { status: event.response.status, statusText: event.response.statusText, url: event.response.url, mimeType: event.response.mimeType, headers: event.response.headers }; });
  cdp.on("Network.loadingFinished", (event) => { const item = requestMap.get(event.requestId); if (!item) return; const promise = cdp.send("Network.getResponseBody", { requestId: event.requestId }).then((body) => { item.responseBody = body.base64Encoded ? "<BASE64>" : body.body; }).catch(() => {}).finally(() => network.push(item)); bodyPromises.push(promise); });

  async function inspect(name, url) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false }); await cdp.send("Page.navigate", { url });
    for (let i = 0; i < 100; i += 1) { await wait(100); const ready = (await cdp.send("Runtime.evaluate", { expression: `document.querySelectorAll('section[aria-label="B11 券前每日代表價"]').length===1&&document.querySelectorAll('section[aria-label="B11 已確認券後每日代表價"]').length===1`, returnByValue: true })).result.value; if (ready) break; }
    await wait(250);
    const expression = `(() => { const labels=${JSON.stringify(labels)}; const visible=(node)=>{const style=getComputedStyle(node),rect=node.getBoundingClientRect();return style.display!=="none"&&style.visibility!=="hidden"&&rect.width>0&&rect.height>0}; const sections={}; for(const [key,label] of Object.entries(labels)){const nodes=[...document.querySelectorAll('section[aria-label="'+label+'"]')];sections[key]={selector:'section[aria-label="'+label+'"]',count:nodes.length,visible:nodes.length===1&&visible(nodes[0]),heading:nodes[0]?.querySelector('h3')?.innerText??null,meta:nodes[0]?.querySelector('.section-heading > span')?.innerText??null,text:nodes[0]?.innerText??null,rows:[...(nodes[0]?.querySelectorAll('.history-row')??[])].map(row=>({text:row.innerText,time:row.querySelector('time')?.getAttribute('datetime')??null,visible:visible(row)}))}} const anchors=[...document.querySelectorAll('a[href]')].map(x=>x.href); const cta=[...document.querySelectorAll('.cta')].map(x=>({disabled:x.disabled,href:x.getAttribute('href')})); return {url:location.href,title:document.title,body_text:document.body.innerText,html:document.documentElement.outerHTML,sections,anchors,cta,width:innerWidth,scroll_width:document.documentElement.scrollWidth}; })()`;
    const value = (await cdp.send("Runtime.evaluate", { expression, returnByValue: true })).result.value;
    const full = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }); await writeFile(path.join(screenshots, `${name}-full.png`), Buffer.from(full.data, "base64"));
    await cdp.send("Runtime.evaluate", { expression: `document.querySelector('.daily-history-columns')?.scrollIntoView({block:'center'})` }); await wait(150); const daily = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false }); await writeFile(path.join(screenshots, `${name}-daily-visible.png`), Buffer.from(daily.data, "base64"));
    await cdp.send("Runtime.evaluate", { expression: `document.querySelector('.coupon-history-columns:not(.daily-history-columns)')?.scrollIntoView({block:'center'})` }); await wait(150); const raw = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false }); await writeFile(path.join(screenshots, `${name}-raw-visible.png`), Buffer.from(raw.data, "base64"));
    await writeFile(path.join(domRoot, `${name}.json`), JSON.stringify(value, null, 2)); return value;
  }

  confirmed = await inspect("confirmed", `${base}/?mode=synthetic&contract=v4&series=confirmed`);
  unavailable = await inspect("unavailable", `${base}/?mode=synthetic&contract=v4&series=unavailable`);
  await wait(300); await Promise.all(bodyPromises); cdp.close();
} finally { processChrome.kill(); await new Promise((resolve) => processChrome.once("exit", resolve)); await rm(profile, { recursive: true, force: true }); }

const apiEntries = network.filter((item) => item.request.url.includes("/cdh-coupon-v4/")); const externalRequests = network.filter((item) => { try { const url = new URL(item.request.url); return url.protocol.startsWith("http") && url.hostname !== "127.0.0.1"; } catch { return false; } });
const bodies = apiEntries.map((item) => { try { return JSON.parse(item.responseBody ?? "null"); } catch { return null; } }).filter(Boolean); const confirmedWire = bodies.find((body) => body?.product?.series_key === "confirmed"), unavailableWire = bodies.find((body) => body?.product?.series_key === "unavailable");
const c = confirmed.sections, u = unavailable.sections, row = (section) => section?.rows?.[0]?.text ?? "";
const sectionSelectorsExact = Object.values(c).every((section) => section.count === 1 && section.visible) && Object.values(u).every((section) => section.count === 1 && section.visible);
const assertions = {
  exact_daily_dom_selectors_visible: sectionSelectorsExact,
  raw_before_visible_99: c.raw_before.rows.length === 1 && row(c.raw_before).includes("NT$ 99") && c.raw_before.meta.includes("1 筆"),
  raw_after_visible_49: c.raw_after.rows.length === 1 && row(c.raw_after).includes("NT$ 49") && c.raw_after.meta.includes("1 筆"),
  daily_before_visible_99: c.daily_before.rows.length === 1 && row(c.daily_before).includes("2026-11-04") && row(c.daily_before).includes("NT$ 99") && row(c.daily_before).includes("1 個 raw 樣本") && c.daily_before.meta.includes("1 日"),
  daily_after_visible_49: c.daily_after.rows.length === 1 && row(c.daily_after).includes("2026-11-04") && row(c.daily_after).includes("NT$ 49") && row(c.daily_after).includes("1 個 raw 樣本") && c.daily_after.meta.includes("1 日"),
  four_groups_distinct: new Set(Object.values(c).map((section) => section.selector)).size === 4,
  dom_counts_match_wire: c.raw_before.rows.length === confirmedWire?.history?.before_coupon?.length && c.raw_after.rows.length === confirmedWire?.history?.confirmed_after_coupon?.length && c.daily_before.rows.length === confirmedWire?.history_quality?.before_coupon?.daily_representatives?.length && c.daily_after.rows.length === confirmedWire?.history_quality?.confirmed_after_coupon?.daily_representatives?.length,
  exact_identity_and_prices: confirmedWire?.product?.sku_id === undefined ? confirmedWire?.product?.series_identity?.sku_id === "SYN-SKU-CONFIRMED" && confirmedWire?.product?.before_coupon_price_twd === 99 && confirmedWire?.product?.display_price_twd === 49 : false,
  empty_history_visible_and_not_filled: Object.values(u).every((section) => section.rows.length === 0) && u.raw_before.meta.includes("0 筆") && u.raw_after.meta.includes("0 筆") && u.daily_before.meta.includes("0 日") && u.daily_after.meta.includes("0 日") && u.daily_after.text.includes("不以券前價補值") && unavailableWire?.history_quality?.before_coupon?.daily_representatives?.length === 0,
  actual_search_and_detail_network: apiEntries.some((item) => item.request.url.includes("/api/v4/products?")) && apiEntries.some((item) => item.request.url.endsWith("/api/v4/products/confirmed")),
  cta_disabled_and_no_outbound: [...confirmed.cta, ...unavailable.cta].every((item) => item.disabled === true && !item.href) && confirmed.anchors.every((url) => url.startsWith(base)) && unavailable.anchors.every((url) => url.startsWith(base)),
  no_horizontal_overflow: confirmed.scroll_width <= confirmed.width && unavailable.scroll_width <= unavailable.width,
  loopback_only: externalRequests.length === 0,
  no_console_exceptions: !consoleEntries.some((item) => item.type === "exception"),
};
const har = { log: { version: "1.2", creator: { name: "CDH G09 CDP", version: "1" }, entries: network } }; await writeFile(path.join(output, "network.har"), JSON.stringify(har, null, 2)); await writeFile(path.join(output, "browser_console.json"), JSON.stringify(consoleEntries, null, 2));
const summary = { schema: "CDH-G09-A11-B11-DAILY-DOM-1", chromium: browserVersion, chrome_path: chrome, base_url: base.replace(/:\d+$/, ":<EPHEMERAL>"), selectors: labels, network_entry_count: network.length, api_entry_count: apiEntries.length, external_requests: externalRequests, assertions, chrome_stderr: chromeStderr, exit_code: Object.values(assertions).every(Boolean) ? 0 : 1, passed: Object.values(assertions).every(Boolean) };
await writeFile(path.join(output, "browser_result.json"), JSON.stringify(summary, null, 2)); console.log(JSON.stringify({ passed: summary.passed, assertions })); process.exitCode = summary.exit_code;
