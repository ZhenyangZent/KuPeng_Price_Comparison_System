import assert from "node:assert/strict";
import test from "node:test";

import {
  CHANNEL,
  buildNativeEnvelope,
  isTrustedExtensionSender,
  validateClientMessage,
  validateSyntheticObservation,
  withTimeout,
} from "../../experiments/B01/extension/bridge_logic.mjs";

function observation() {
  return {
    source_class: "SYNTHETIC_TEST_PAGE",
    sku: "SYNTH-B01-0001",
    title: "合成測試商品",
    product_url: "https://synthetic.invalid/products/b01-0001",
    price_minor: 0,
    currency: "TWD",
    observed_at: "2026-11-02T00:00:00.000Z",
  };
}

test("trusted extension sender is accepted", () => {
  assert.equal(
    isTrustedExtensionSender(
      { id: "extension-id", url: "moz-extension://uuid/popup.html" },
      "extension-id",
      "moz-extension://uuid/",
    ),
    true,
  );
});

test("web sender cannot trigger native bridge", () => {
  assert.equal(
    isTrustedExtensionSender(
      { id: "extension-id", url: "https://synthetic.invalid/products/x" },
      "extension-id",
      "moz-extension://uuid/",
    ),
    false,
  );
});

test("client operation allowlist rejects arbitrary command", () => {
  assert.throws(
    () => validateClientMessage({ channel: CHANNEL, action: "RUN_COMMAND", payload: {} }),
    /CLIENT_ACTION_NOT_ALLOWLISTED/,
  );
});

test("valid observation passes closed schema", () => {
  assert.equal(validateSyntheticObservation(observation()).sku, "SYNTH-B01-0001");
});

test("real Coupang URL is rejected", () => {
  const value = observation();
  value.product_url = "https://www.tw.coupang.com/products/real";
  assert.throws(() => validateSyntheticObservation(value), /OBSERVATION_URL_REJECTED/);
});

test("native envelope binds fixed protocol and message id", () => {
  assert.deepEqual(buildNativeEnvelope("PING", {}, "node-1"), {
    protocol_version: "1.0",
    message_id: "node-1",
    type: "PING",
    payload: {},
  });
});

test("timeout rejects an unresponsive native host", async () => {
  await assert.rejects(withTimeout(new Promise(() => {}), 10), /NATIVE_RESPONSE_TIMEOUT/);
});

test("resolved native response clears timeout", async () => {
  assert.equal(await withTimeout(Promise.resolve("PONG"), 100), "PONG");
});
