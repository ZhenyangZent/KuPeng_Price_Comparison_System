import assert from "node:assert/strict";
import test from "node:test";

import { NativePortController } from "../../experiments/B01/extension/bridge_logic.mjs";

class ListenerSet {
  constructor() {
    this.listeners = [];
  }
  addListener(listener) {
    this.listeners.push(listener);
  }
  emit(value) {
    for (const listener of this.listeners) listener(value);
  }
}

class MockPort {
  constructor({ emitDisconnectOnClose = true } = {}) {
    this.onMessage = new ListenerSet();
    this.onDisconnect = new ListenerSet();
    this.messages = [];
    this.disconnectCount = 0;
    this.emitDisconnectOnClose = emitDisconnectOnClose;
  }
  postMessage(message) {
    this.messages.push(message);
  }
  disconnect() {
    this.disconnectCount += 1;
    if (this.emitDisconnectOnClose) this.onDisconnect.emit();
  }
}

function fixture({ timeout = 8, emitDisconnectOnClose = true } = {}) {
  const ports = [];
  let sequence = 0;
  const controller = new NativePortController({
    connectNative: () => {
      const port = new MockPort({ emitDisconnectOnClose });
      ports.push(port);
      return port;
    },
    randomUUID: () => `request-${++sequence}`,
    responseTimeoutMs: timeout,
  });
  return { controller, ports };
}

function validResponse(action, messageId) {
  const payloads = {
    PING: { reply: "PONG", host_version: "0.1.0", protocol_version: "1.0" },
    STATUS: { status: "READY", host_version: "0.1.0", accepted_count: 0 },
  };
  return {
    protocol_version: "1.0",
    message_id: messageId,
    ok: true,
    type: `${action}_RESULT`,
    payload: payloads[action],
    duplicate: false,
  };
}

test("timeout disconnects the stuck port and clears pending", async () => {
  const { controller, ports } = fixture();
  await assert.rejects(controller.request("PING", {}), /NATIVE_RESPONSE_TIMEOUT/);
  assert.equal(ports[0].disconnectCount, 1);
  assert.equal(controller.pendingCount, 0);
  assert.equal(controller.hasActivePort, false);
});

test("request after timeout connects a fresh port", async () => {
  const { controller, ports } = fixture();
  await assert.rejects(controller.request("PING", {}), /NATIVE_RESPONSE_TIMEOUT/);
  const response = controller.request("PING", {});
  assert.equal(ports.length, 2);
  const messageId = ports[1].messages[0].message_id;
  ports[1].onMessage.emit(validResponse("PING", messageId));
  assert.equal((await response).ok, true);
});

test("late reply from old generation cannot satisfy a new request", async () => {
  const { controller, ports } = fixture({ emitDisconnectOnClose: false });
  const firstIdPromise = controller.request("PING", {});
  const firstId = ports[0].messages[0].message_id;
  await assert.rejects(firstIdPromise, /NATIVE_RESPONSE_TIMEOUT/);
  const second = controller.request("STATUS", {});
  const secondId = ports[1].messages[0].message_id;
  ports[0].onMessage.emit({ message_id: secondId, ok: false, stale: true });
  assert.equal(controller.pendingCount, 1);
  ports[1].onMessage.emit(validResponse("STATUS", secondId));
  assert.equal((await second).ok, true);
  ports[0].onMessage.emit({ message_id: firstId, ok: true });
  assert.equal(controller.pendingCount, 0);
});

test("one timeout terminates all concurrent promises on that generation", async () => {
  const { controller } = fixture();
  const first = controller.request("PING", {});
  const second = controller.request("STATUS", {});
  const results = await Promise.allSettled([first, second]);
  assert.deepEqual(results.map((result) => result.status), ["rejected", "rejected"]);
  assert.match(results[0].reason.message, /NATIVE_RESPONSE_TIMEOUT/);
  assert.match(results[1].reason.message, /NATIVE_PORT_RESET_AFTER_TIMEOUT/);
  assert.equal(controller.pendingCount, 0);
});

test("consecutive timeouts use and close distinct ports", async () => {
  const { controller, ports } = fixture();
  await assert.rejects(controller.request("PING", {}), /NATIVE_RESPONSE_TIMEOUT/);
  await assert.rejects(controller.request("PING", {}), /NATIVE_RESPONSE_TIMEOUT/);
  assert.equal(ports.length, 2);
  assert.deepEqual(ports.map((port) => port.disconnectCount), [1, 1]);
});

test("late disconnect from old port cannot invalidate replacement", async () => {
  const { controller, ports } = fixture({ emitDisconnectOnClose: false });
  await assert.rejects(controller.request("PING", {}), /NATIVE_RESPONSE_TIMEOUT/);
  const current = controller.request("PING", {});
  ports[0].onDisconnect.emit();
  assert.equal(controller.hasActivePort, true);
  const currentId = ports[1].messages[0].message_id;
  ports[1].onMessage.emit(validResponse("PING", currentId));
  await current;
});

test("simulated browser shutdown rejects pending and disconnects", async () => {
  const { controller, ports } = fixture({ timeout: 100 });
  const pending = controller.request("PING", {});
  controller.close("BROWSER_SHUTDOWN");
  await assert.rejects(pending, /BROWSER_SHUTDOWN/);
  assert.equal(ports[0].disconnectCount, 1);
  assert.equal(controller.pendingCount, 0);
});
