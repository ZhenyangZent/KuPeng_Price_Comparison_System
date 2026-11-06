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

const chromeArgs = ["--headless=new", "--disable-gpu", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-default-browser-check", "--incognito", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, "about:blank"];
const processChrome = spawn(chrome, chromeArgs, { shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] }); let chromeStderr = ""; processChrome.stderr.on("data", (value) => { chromeStderr += value.toString(); });
const network = [], requestMap = new Map(), bodyPromises = [], consoleEntries = [], results = []; let retryClickRecovered = false;
try {
  const tabs = await json(`http://127.0.0.1:${debugPort}/json`), tab = tabs.find((item) => item.type === "page"); if (!tab?.webSocketDebuggerUrl) throw new Error("Chrome page target unavailable");
  const cdp = client(tab.webSocketDebuggerUrl); await cdp.opened; await Promise.all([cdp.send("Page.enable"), cdp.send("Runtime.enable"), cdp.send("Network.enable"), cdp.send("Log.enable")]);
  cdp.on("Runtime.exceptionThrown", (event) => consoleEntries.push({ type: "exception", text: event.exceptionDetails?.text ?? "unknown" })); cdp.on("Log.entryAdded", (event) => consoleEntries.push({ type: event.entry.level, text: event.entry.text, url: event.entry.url }));
  cdp.on("Network.requestWillBeSent", (event) => requestMap.set(event.requestId, { startedDateTime: new Date().toISOString(), request: { method: event.request.method, url: event.request.url, headers: event.request.headers } }));
  cdp.on("Network.responseReceived", (event) => { const item = requestMap.get(event.requestId); if (item) item.response = { status: event.response.status, statusText: event.response.statusText, url: event.response.url, mimeType: event.response.mimeType, headers: event.response.headers }; });
  cdp.on("Network.loadingFinished", (event) => { const item = requestMap.get(event.requestId); if (!item) return; const promise = cdp.send("Network.getResponseBody", { requestId: event.requestId }).then((body) => { item.responseBody = body.base64Encoded ? "<BASE64>" : body.body; }).catch(() => {}).finally(() => network.push(item)); bodyPromises.push(promise); });

  async function snapshot(name, url, required, forbidden = [], width = 1200, height = 1000) {
    await cdp.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 500 }); await cdp.send("Page.navigate", { url });
    let value;
    for (let i = 0; i < 80; i += 1) { await wait(100); value = (await cdp.send("Runtime.evaluate", { expression: `({text:document.body?.innerText??"",html:document.documentElement.outerHTML,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,href:location.href,outbound:[...document.querySelectorAll('a[href]')].map(a=>a.href),cta:[...document.querySelectorAll('.cta')].map(x=>({disabled:x.disabled,href:x.getAttribute('href')}))})`, returnByValue: true })).result.value; if (required.every((text) => value.text.includes(text))) break; }
    const missing = required.filter((text) => !value.text.includes(text)), forbiddenPresent = forbidden.filter((text) => value.text.includes(text)); const external = value.outbound.filter((urlValue) => !urlValue.startsWith(base)); const ctaSafe = value.cta.every((item) => item.disabled === true && !item.href);
    const shot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }); const screenshot = path.join(screenshots, `${name}.png`); await writeFile(screenshot, Buffer.from(shot.data, "base64"));
    const result = { name, url, final_url: value.href, required, missing, forbidden_present: forbiddenPresent, external_anchors: external, cta_safe: ctaSafe, no_horizontal_overflow: value.scrollWidth <= value.width, screenshot: path.relative(output, screenshot).replaceAll("\\", "/"), pass: missing.length === 0 && forbiddenPresent.length === 0 && external.length === 0 && ctaSafe && value.scrollWidth <= value.width };
    await writeFile(path.join(domRoot, `${name}.json`), JSON.stringify({ ...result, text: value.text, html: value.html }, null, 2)); results.push(result); return result;
  }

  await snapshot("confirmed-desktop", `${base}/?mode=synthetic&contract=v4&series=confirmed`, ["Synthetic confirmed", "已確認券後商品價", "NT$ 49", "券前商品價歷史", "已確認券後商品價歷史", "SYN-SKU-CONFIRMED", "券前 1 筆／已確認券後 1 筆", "正式連結尚未核准"]);
  await snapshot("expired-coupon", `${base}/?mode=synthetic&contract=v4&series=expired-coupon`, ["Synthetic expired-coupon", "優惠券已過期", "券前商品價", "NT$ 99", "已確認券後商品價歷史"]);
  await snapshot("zero-mobile", `${base}/?mode=synthetic&contract=v4&series=zero`, ["Synthetic zero", "NT$ 0", "不是零成本到手", "required_total_twd 維持 null"], ["免費到手"], 390, 844);
  await snapshot("unavailable", `${base}/?mode=synthetic&contract=v4&series=unavailable`, ["Synthetic unavailable", "價格未知", "UNKNOWN"]);
  await snapshot("quantity-two", `${base}/?mode=synthetic&contract=v4&series=quantity-two`, ["Synthetic quantity-two", "NT$ 75", "最低數量", "最低商品額", "NT$ 150", "ORDER_TOTAL"]);
  await snapshot("empty-search", `${base}/?mode=synthetic&contract=v4&q=no-such-product`, ["V4 snapshot 有商品，但查無符合結果", "請選擇 V4 商品序列"]);

  await fetch(`${base}/__g08_fail_next`, { method: "POST" }); await snapshot("retry-error", `${base}/?mode=synthetic&contract=v4&series=confirmed`, ["V4 Search 失敗", "G08_INJECTED_RETRY", "重試 API"]);
  await cdp.send("Runtime.evaluate", { expression: `[...document.querySelectorAll('button')].find(x=>x.textContent.includes('重試 API'))?.click()` });
  let recovered = ""; for (let i = 0; i < 80; i += 1) { await wait(100); recovered = (await cdp.send("Runtime.evaluate", { expression: `document.body.innerText`, returnByValue: true })).result.value; if (recovered.includes("Synthetic confirmed")) break; } retryClickRecovered = recovered.includes("Synthetic confirmed");
  await snapshot("retry-recovered", `${base}/?mode=synthetic&contract=v4&series=confirmed`, ["Synthetic confirmed", "已確認券後商品價", "NT$ 49"]);
  await Promise.all(bodyPromises); cdp.close();
} finally { processChrome.kill(); await new Promise((resolve) => processChrome.once("exit", resolve)); await rm(profile, { recursive: true, force: true }); }

const apiEntries = network.filter((item) => item.request.url.includes("/cdh-coupon-v4/")); const externalRequests = network.filter((item) => { try { const url = new URL(item.request.url); return url.protocol.startsWith("http") && url.hostname !== "127.0.0.1"; } catch { return false; } });
const responseBodies = apiEntries.map((item) => { try { return JSON.parse(item.responseBody ?? "null"); } catch { return null; } }).filter(Boolean); const confirmedDetail = responseBodies.find((body) => body?.product?.series_key === "confirmed"), unavailableDetail = responseBodies.find((body) => body?.product?.series_key === "unavailable"), zeroDetail = responseBodies.find((body) => body?.product?.series_key === "zero");
const assertions = { all_dom_cases_pass: results.every((item) => item.pass), retry_click_recovered: retryClickRecovered, real_browser_search_requests: apiEntries.some((item) => item.request.url.includes("/api/v4/products?")), real_browser_detail_requests: apiEntries.some((item) => item.request.url.includes("/api/v4/products/confirmed")), coupon_49_before_99: confirmedDetail?.product?.display_price_twd === 49 && confirmedDetail?.product?.before_coupon_price_twd === 99, zero_is_not_null: zeroDetail?.product?.display_price_twd === 0 && unavailableDetail?.product?.display_price_twd === null, dual_raw_history: confirmedDetail?.history?.before_coupon?.length >= 1 && confirmedDetail?.history?.confirmed_after_coupon?.length >= 1, daily_representatives_in_network: confirmedDetail?.history_quality?.before_coupon?.daily_representatives?.length >= 1 && confirmedDetail?.history_quality?.confirmed_after_coupon?.daily_representatives?.length >= 1, loopback_only: externalRequests.length === 0, no_console_exceptions: !consoleEntries.some((item) => item.type === "exception"), screenshots_complete: results.every((item) => item.screenshot) };
const har = { log: { version: "1.2", creator: { name: "CDH G08 CDP", version: "1" }, entries: network } }; await writeFile(path.join(output, "network.har"), JSON.stringify(har, null, 2)); await writeFile(path.join(output, "browser_console.json"), JSON.stringify(consoleEntries, null, 2));
const summary = { schema: "CDH-G08-A10R08-B11-BROWSER-1", chrome, base_url: base.replace(/:\d+$/, ":<EPHEMERAL>"), cases: results, network_entry_count: network.length, api_entry_count: apiEntries.length, external_requests: externalRequests, assertions, chrome_stderr: chromeStderr, exit_code: Object.values(assertions).every(Boolean) ? 0 : 1, passed: Object.values(assertions).every(Boolean) };
await writeFile(path.join(output, "browser_result.json"), JSON.stringify(summary, null, 2)); console.log(JSON.stringify({ passed: summary.passed, assertions, cases: results.map(({ name, pass }) => ({ name, pass })) })); process.exitCode = summary.exit_code;
