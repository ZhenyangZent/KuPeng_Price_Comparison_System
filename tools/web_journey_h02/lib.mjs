import { createHash } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";

export const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function sha256File(file) {
  const hash = createHash("sha256");
  await new Promise((resolve, reject) => {
    const stream = createReadStream(file);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("error", reject);
    stream.on("end", resolve);
  });
  return hash.digest("hex");
}

export function locateBrowser() {
  return [
    process.env.CDH_H02_BROWSER,
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
  ].filter(Boolean).find((file) => existsSync(file)) ?? null;
}

export async function waitForJson(url, attempts = 120) {
  for (let index = 0; index < attempts; index += 1) {
    try { const response = await fetch(url); if (response.ok) return await response.json(); } catch { /* local service pending */ }
    await wait(100);
  }
  throw new Error(`local endpoint unavailable: ${url}`);
}

export function cdpClient(url) {
  const socket = new WebSocket(url);
  let id = 1;
  const pending = new Map();
  const once = new Map();
  const on = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const item = pending.get(message.id); pending.delete(message.id);
      if (message.error) item.reject(new Error(message.error.message)); else item.resolve(message.result);
      return;
    }
    for (const listener of on.get(message.method) ?? []) listener(message.params);
    const queue = once.get(message.method) ?? [];
    if (queue.length) { const listener = queue.shift(); once.set(message.method, queue); listener(message.params); }
  });
  const opened = new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  return {
    opened,
    send(method, params = {}) {
      const requestId = id++;
      return new Promise((resolve, reject) => { pending.set(requestId, { resolve, reject }); socket.send(JSON.stringify({ id: requestId, method, params })); });
    },
    once(method) { return new Promise((resolve) => once.set(method, [...(once.get(method) ?? []), resolve])); },
    on(method, listener) { on.set(method, [...(on.get(method) ?? []), listener]); },
    close() { socket.close(); }
  };
}

export async function evaluate(cdp, expression) {
  const value = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (value.exceptionDetails) throw new Error(value.exceptionDetails.text ?? "browser evaluation failed");
  return value.result.value;
}

export async function navigate(cdp, url) {
  const loaded = cdp.once("Page.loadEventFired");
  const result = await cdp.send("Page.navigate", { url });
  await Promise.race([loaded, wait(8000)]);
  await wait(250);
  return result;
}

export async function waitFor(cdp, expression, timeout = 6000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await evaluate(cdp, expression)) return;
    await wait(60);
  }
  throw new Error(`condition timed out: ${expression}`);
}

export async function setInput(cdp, selector, value) {
  await evaluate(cdp, `document.querySelector(${JSON.stringify(selector)}).focus()`);
  const events = [
    ["keyDown", "Control", "ControlLeft", 17, 2], ["keyDown", "a", "KeyA", 65, 2],
    ["keyUp", "a", "KeyA", 65, 2], ["keyUp", "Control", "ControlLeft", 17, 0],
    ["keyDown", "Backspace", "Backspace", 8, 0], ["keyUp", "Backspace", "Backspace", 8, 0]
  ];
  for (const [type, key, code, windowsVirtualKeyCode, modifiers] of events) await cdp.send("Input.dispatchKeyEvent", { type, key, code, windowsVirtualKeyCode, modifiers });
  await cdp.send("Input.insertText", { text: value });
}

export async function pressEnter(cdp) {
  await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
}

export async function capture(cdp, evidenceRoot, name) {
  const dom = await evaluate(cdp, "document.documentElement.outerHTML");
  const image = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await mkdir(`${evidenceRoot}/dom`, { recursive: true });
  await mkdir(`${evidenceRoot}/screenshots`, { recursive: true });
  await writeFile(`${evidenceRoot}/dom/${name}.html`, dom, "utf8");
  await writeFile(`${evidenceRoot}/screenshots/${name}.png`, Buffer.from(image.data, "base64"));
  return { dom: `evidence/dom/${name}.html`, screenshot: `evidence/screenshots/${name}.png` };
}

export function externalHttpRequests(urls) {
  return urls.filter((url) => {
    if (!/^https?:/i.test(url)) return false;
    const host = new URL(url).hostname;
    return host !== "127.0.0.1" && host !== "localhost";
  });
}

export function toHar(requests) {
  return {
    log: {
      version: "1.2",
      creator: { name: "CDH-H02-CDP", version: "1" },
      entries: requests.map((item) => ({
        startedDateTime: item.startedDateTime,
        time: 0,
        request: { method: item.method, url: item.url, httpVersion: "HTTP/1.1", headers: [], queryString: [], cookies: [], headersSize: -1, bodySize: -1 },
        response: { status: item.status ?? 0, statusText: item.statusText ?? "", httpVersion: "HTTP/1.1", headers: [], cookies: [], content: { size: -1, mimeType: item.mimeType ?? "" }, redirectURL: "", headersSize: -1, bodySize: -1 },
        cache: {}, timings: { send: 0, wait: 0, receive: 0 }
      }))
    }
  };
}

