import assert from "node:assert/strict";
import test from "node:test";

import {
  NativePortController,
  validateNativeResponse,
} from "../../experiments/B01/extension/bridge_logic.mjs";

class Emitter {
  constructor() { this.listeners = []; }
  addListener(callback) { this.listeners.push(callback); }
  emit(value) { for (const callback of this.listeners) callback(value); }
}

class MockPort {
  constructor() {
    this.onMessage = new Emitter();
    this.onDisconnect = new Emitter();
    this.sent = [];
    this.disconnectCount = 0;
  }
  postMessage(value) { this.sent.push(value); }
  disconnect() { this.disconnectCount += 1; this.onDisconnect.emit(); }
}

function success(action, messageId) {
  const payloads = {
    PING: { reply: "PONG", host_version: "0.1.0", protocol_version: "1.0" },
    STATUS: { status: "READY", host_version: "0.1.0", accepted_count: 3 },
    MOCK_OBSERVATION: {
      accepted: true,
      observation_sha256: "a".repeat(64),
      scope: "SYNTHETIC_ONLY",
    },
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

function fixture() {
  const ports = [];
  let sequence = 0;
  const controller = new NativePortController({
    connectNative: () => {
      const port = new MockPort();
      ports.push(port);
      return port;
    },
    randomUUID: () => `response-${++sequence}`,
    responseTimeoutMs: 100,
  });
  return { controller, ports };
}

test("valid PING, STATUS and synthetic observation envelopes pass", () => {
  for (const action of ["PING", "STATUS", "MOCK_OBSERVATION"]) {
    const response = success(action, `valid-${action}`);
    assert.equal(validateNativeResponse(response, action, response.message_id), response);
  }
});

test("controller resolves a fully valid PING reply", async () => {
  const { controller, ports } = fixture();
  const pending = controller.request("PING", {});
  const id = ports[0].sent[0].message_id;
  ports[0].onMessage.emit(success("PING", id));
  assert.equal((await pending).payload.reply, "PONG");
  assert.equal(controller.hasActivePort, true);
});

test("incompatible version and type counterexample rejects and resets", async () => {
  const { controller, ports } = fixture();
  const pending = controller.request("PING", {});
  const id = ports[0].sent[0].message_id;
  ports[0].onMessage.emit({
    protocol_version: "999.0",
    message_id: id,
    ok: true,
    type: "WRONG_RESULT",
    payload: { accepted: true, scope: "REAL_SITE" },
    duplicate: false,
  });
  await assert.rejects(pending, /NATIVE_RESPONSE_VERSION_REJECTED/);
  assert.equal(ports[0].disconnectCount, 1);
  assert.equal(controller.pendingCount, 0);
});

test("correct version with wrong response type rejects and resets", async () => {
  const { controller, ports } = fixture();
  const pending = controller.request("PING", {});
  const id = ports[0].sent[0].message_id;
  const response = success("PING", id);
  response.type = "STATUS_RESULT";
  ports[0].onMessage.emit(response);
  await assert.rejects(pending, /NATIVE_RESPONSE_TYPE_REJECTED/);
  assert.equal(controller.hasActivePort, false);
});

test("non-boolean ok is rejected as malformed envelope", async () => {
  const { controller, ports } = fixture();
  const pending = controller.request("PING", {});
  const id = ports[0].sent[0].message_id;
  ports[0].onMessage.emit({ protocol_version: "1.0", message_id: id, ok: "yes", error: {} });
  await assert.rejects(pending, /NATIVE_RESPONSE_OK_REJECTED|NATIVE_RESPONSE_ERROR_SCHEMA_REJECTED/);
  assert.equal(ports[0].disconnectCount, 1);
});

test("PING payload with synthetic or real-site scope is rejected", async () => {
  const { controller, ports } = fixture();
  const pending = controller.request("PING", {});
  const id = ports[0].sent[0].message_id;
  const response = success("PING", id);
  response.payload = { accepted: true, scope: "REAL_SITE" };
  ports[0].onMessage.emit(response);
  await assert.rejects(pending, /NATIVE_RESPONSE_PING_SCHEMA_REJECTED/);
  assert.equal(controller.hasActivePort, false);
});

test("synthetic response requires SYNTHETIC_ONLY scope and SHA-256", () => {
  const wrongScope = success("MOCK_OBSERVATION", "obs-1");
  wrongScope.payload.scope = "REAL_SITE";
  assert.throws(
    () => validateNativeResponse(wrongScope, "MOCK_OBSERVATION", "obs-1"),
    /NATIVE_RESPONSE_OBSERVATION_VALUE_REJECTED/,
  );
  const wrongHash = success("MOCK_OBSERVATION", "obs-2");
  wrongHash.payload.observation_sha256 = "not-a-hash";
  assert.throws(
    () => validateNativeResponse(wrongHash, "MOCK_OBSERVATION", "obs-2"),
    /NATIVE_RESPONSE_OBSERVATION_VALUE_REJECTED/,
  );
});

test("valid host error rejects request without poisoning healthy port", async () => {
  const { controller, ports } = fixture();
  const pending = controller.request("PING", {});
  const id = ports[0].sent[0].message_id;
  ports[0].onMessage.emit({
    protocol_version: "1.0",
    message_id: id,
    ok: false,
    error: { code: "TYPE_NOT_ALLOWLISTED", detail: "rejected" },
  });
  await assert.rejects(pending, /NATIVE_HOST_ERROR:TYPE_NOT_ALLOWLISTED:rejected/);
  assert.equal(controller.hasActivePort, true);
  assert.equal(ports[0].disconnectCount, 0);
});

test("malformed error schema rejects and resets port", async () => {
  const { controller, ports } = fixture();
  const pending = controller.request("PING", {});
  const id = ports[0].sent[0].message_id;
  ports[0].onMessage.emit({
    protocol_version: "1.0",
    message_id: id,
    ok: false,
    error: { code: "bad code", detail: 9 },
  });
  await assert.rejects(pending, /NATIVE_RESPONSE_ERROR_CODE_REJECTED|NATIVE_RESPONSE_ERROR_DETAIL_REJECTED/);
  assert.equal(ports[0].disconnectCount, 1);
});

test("unmatched current-generation message id rejects all pending and resets", async () => {
  const { controller, ports } = fixture();
  const first = controller.request("PING", {});
  const second = controller.request("STATUS", {});
  ports[0].onMessage.emit(success("PING", "unknown-id"));
  const results = await Promise.allSettled([first, second]);
  assert.deepEqual(results.map((item) => item.status), ["rejected", "rejected"]);
  assert.equal(ports[0].disconnectCount, 1);
  assert.equal(controller.pendingCount, 0);
});

test("invalid stale-generation reply cannot affect a replacement request", async () => {
  const { controller, ports } = fixture();
  const first = controller.request("PING", {});
  controller.close("TEST_ROTATE");
  await assert.rejects(first, /TEST_ROTATE/);
  const second = controller.request("PING", {});
  const secondId = ports[1].sent[0].message_id;
  ports[0].onMessage.emit({ protocol_version: "999.0", message_id: secondId });
  ports[1].onMessage.emit(success("PING", secondId));
  assert.equal((await second).ok, true);
});
