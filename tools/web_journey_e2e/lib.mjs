import { createHash } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import http from "node:http";
import path from "node:path";

export const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

export async function sha256File(file) {
  const hash = createHash("sha256");
  await new Promise((resolve, reject) => {
    const input = createReadStream(file);
    input.on("data", (chunk) => hash.update(chunk));
    input.on("error", reject);
    input.on("end", resolve);
  });
  return hash.digest("hex");
}

export function locateBrowser() {
  const candidates = [
    process.env.CDH_H01_BROWSER,
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
  ].filter(Boolean);
  return candidates.find((candidate) => existsSync(candidate)) ?? null;
}

const MIME = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"]
]);

export async function startStaticServer(root, port = 4173) {
  const resolvedRoot = path.resolve(root);
  const requests = [];
  const server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", `http://${request.headers.host ?? "127.0.0.1"}`);
      requests.push({ method: request.method, path: url.pathname });
      let relative = decodeURIComponent(url.pathname).replace(/^\/+/, "") || "index.html";
      if (relative.includes("\0") || relative.split(/[\\/]/).includes("..")) {
        response.writeHead(400).end("invalid path");
        return;
      }
      let file = path.resolve(resolvedRoot, relative);
      if (!file.startsWith(`${resolvedRoot}${path.sep}`) && file !== resolvedRoot) {
        response.writeHead(403).end("forbidden");
        return;
      }
      let info;
      try { info = await stat(file); } catch { info = null; }
      if (!info?.isFile()) file = path.join(resolvedRoot, "index.html");
      const payload = await readFile(file);
      response.writeHead(200, {
        "Content-Type": MIME.get(path.extname(file).toLowerCase()) ?? "application/octet-stream",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff"
      });
      response.end(payload);
    } catch (error) {
      response.writeHead(500).end(String(error));
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  const address = server.address();
  const actualPort = typeof address === "object" && address ? address.port : port;
  return {
    url: `http://127.0.0.1:${actualPort}`,
    requests,
    close: () => new Promise((resolve) => server.close(resolve))
  };
}

export async function waitForJson(url, attempts = 100) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return await response.json();
    } catch { /* local endpoint not ready */ }
    await wait(100);
  }
  throw new Error(`local JSON endpoint did not become ready: ${url}`);
}

export function createCdpClient(webSocketUrl) {
  const socket = new WebSocket(webSocketUrl);
  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();
  const subscriptions = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const operation = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) operation.reject(new Error(message.error.message));
      else operation.resolve(message.result);
      return;
    }
    for (const listener of subscriptions.get(message.method) ?? []) listener(message.params);
    const waiting = listeners.get(message.method) ?? [];
    if (waiting.length) {
      const resolve = waiting.shift();
      listeners.set(message.method, waiting);
      resolve(message.params);
    }
  });
  const opened = new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  return {
    opened,
    send(method, params = {}) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        socket.send(JSON.stringify({ id, method, params }));
      });
    },
    once(method) {
      return new Promise((resolve) => listeners.set(method, [...(listeners.get(method) ?? []), resolve]));
    },
    on(method, listener) {
      subscriptions.set(method, [...(subscriptions.get(method) ?? []), listener]);
      return () => subscriptions.set(method, (subscriptions.get(method) ?? []).filter((item) => item !== listener));
    },
    close() { socket.close(); }
  };
}

export async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text ?? "browser evaluation failed");
  return result.result.value;
}

export async function navigate(cdp, url, timeout = 8000) {
  const loaded = cdp.once("Page.loadEventFired");
  const navigation = await cdp.send("Page.navigate", { url });
  await Promise.race([loaded, wait(timeout)]);
  await wait(300);
  return navigation;
}

export async function waitForCondition(cdp, expression, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await evaluate(cdp, expression)) return;
    await wait(50);
  }
  throw new Error(`browser condition timed out: ${expression}`);
}

export async function setInput(cdp, selector, value) {
  const serializedSelector = JSON.stringify(selector);
  await evaluate(cdp, `(() => {
    const element = document.querySelector(${serializedSelector});
    if (!(element instanceof HTMLInputElement)) throw new Error('input not found');
    element.focus();
    return true;
  })()`);
  await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, modifiers: 2 });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 2 });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 2 });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17 });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 });
  await cdp.send("Input.insertText", { text: value });
}

export async function pressKey(cdp, key, code, modifiers = 0) {
  const params = { key, code, windowsVirtualKeyCode: key === "Enter" ? 13 : key === "Tab" ? 9 : 0, modifiers };
  await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", ...params, ...(key === "Enter" ? { text: "\r" } : {}) });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", ...params });
}

export async function verifyManifestFiles(manifestPath, packageRoot, prefix) {
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const selected = manifest.files.filter((entry) => entry.path.startsWith(prefix));
  const results = [];
  for (const entry of selected) {
    const file = path.join(packageRoot, ...entry.path.split("/"));
    let actualHash = null;
    let actualSize = null;
    try {
      actualHash = await sha256File(file);
      actualSize = (await stat(file)).size;
    } catch { /* reported as mismatch */ }
    results.push({
      path: entry.path,
      expected_sha256: entry.sha256,
      actual_sha256: actualHash,
      expected_size: entry.size,
      actual_size: actualSize,
      pass: actualHash === entry.sha256 && actualSize === entry.size
    });
  }
  return { count: results.length, pass: selected.length > 0 && results.every((entry) => entry.pass), results };
}

