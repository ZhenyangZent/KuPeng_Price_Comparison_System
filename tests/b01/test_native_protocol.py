from __future__ import annotations

import io
import json
import struct
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOST_DIR = ROOT / "experiments" / "B01" / "native_host"
sys.path.insert(0, str(HOST_DIR))

from protocol import (  # noqa: E402
    MAX_INCOMING_BYTES,
    HostState,
    ProtocolError,
    encode_frame,
    handle_request,
    read_frame,
)


def envelope(message_id: str = "msg-1", message_type: str = "PING", payload: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "protocol_version": "1.0",
        "message_id": message_id,
        "type": message_type,
        "payload": {} if payload is None else payload,
    }


def observation() -> dict[str, object]:
    return {
        "source_class": "SYNTHETIC_TEST_PAGE",
        "sku": "SYNTH-B01-0001",
        "title": "合成零元測試商品",
        "product_url": "https://synthetic.invalid/products/b01-0001",
        "price_minor": 0,
        "currency": "TWD",
        "observed_at": "2026-11-02T00:00:00Z",
    }


def decode_all(payload: bytes) -> list[dict[str, object]]:
    stream = io.BytesIO(payload)
    messages: list[dict[str, object]] = []
    while True:
        message = read_frame(stream, maximum=1024 * 1024)
        if message is None:
            return messages
        messages.append(message)


class FramingTests(unittest.TestCase):
    def test_01_native_endian_frame_round_trip_with_utf8(self) -> None:
        value = {"text": "中文根目錄"}
        self.assertEqual(read_frame(io.BytesIO(encode_frame(value))), value)

    def test_02_multiple_packets_are_read_in_order(self) -> None:
        stream = io.BytesIO(encode_frame({"n": 1}) + encode_frame({"n": 2}))
        self.assertEqual(read_frame(stream), {"n": 1})
        self.assertEqual(read_frame(stream), {"n": 2})
        self.assertIsNone(read_frame(stream))

    def test_03_empty_input_is_clean_eof(self) -> None:
        self.assertIsNone(read_frame(io.BytesIO()))

    def test_04_zero_length_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "zero-length"):
            read_frame(io.BytesIO(struct.pack("@I", 0)))

    def test_05_truncated_header_is_fatal(self) -> None:
        with self.assertRaises(ProtocolError) as caught:
            read_frame(io.BytesIO(b"\x01\x00"))
        self.assertEqual(caught.exception.code, "TRUNCATED_HEADER")
        self.assertTrue(caught.exception.fatal)

    def test_06_truncated_payload_is_fatal(self) -> None:
        with self.assertRaises(ProtocolError) as caught:
            read_frame(io.BytesIO(struct.pack("@I", 8) + b"{}"))
        self.assertEqual(caught.exception.code, "TRUNCATED_FRAME")

    def test_07_oversized_input_is_rejected_before_body_read(self) -> None:
        with self.assertRaises(ProtocolError) as caught:
            read_frame(io.BytesIO(struct.pack("@I", MAX_INCOMING_BYTES + 1)))
        self.assertEqual(caught.exception.code, "INPUT_TOO_LARGE")
        self.assertTrue(caught.exception.fatal)

    def test_08_invalid_utf8_is_rejected(self) -> None:
        raw = b"\xff"
        with self.assertRaises(ProtocolError) as caught:
            read_frame(io.BytesIO(struct.pack("@I", len(raw)) + raw))
        self.assertEqual(caught.exception.code, "INVALID_UTF8")

    def test_09_invalid_json_is_rejected(self) -> None:
        raw = b"{"
        with self.assertRaises(ProtocolError) as caught:
            read_frame(io.BytesIO(struct.pack("@I", len(raw)) + raw))
        self.assertEqual(caught.exception.code, "INVALID_JSON")

    def test_10_duplicate_json_key_is_rejected(self) -> None:
        raw = b'{"type":"PING","type":"STATUS"}'
        with self.assertRaises(ProtocolError) as caught:
            read_frame(io.BytesIO(struct.pack("@I", len(raw)) + raw))
        self.assertEqual(caught.exception.code, "DUPLICATE_JSON_KEY")


class MessagePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = HostState()

    def test_11_ping_handshake(self) -> None:
        response = handle_request(envelope(), self.state)
        self.assertTrue(response["ok"])
        self.assertEqual(response["payload"]["reply"], "PONG")

    def test_12_status_is_allowlisted(self) -> None:
        response = handle_request(envelope(message_type="STATUS"), self.state)
        self.assertTrue(response["ok"])
        self.assertEqual(response["payload"]["status"], "READY")

    def test_13_unknown_type_is_rejected(self) -> None:
        response = handle_request(envelope(message_type="RUN_COMMAND"), self.state)
        self.assertEqual(response["error"]["code"], "TYPE_NOT_ALLOWLISTED")

    def test_14_command_field_is_rejected(self) -> None:
        request = envelope()
        request["command"] = "calc.exe"
        response = handle_request(request, self.state)
        self.assertEqual(response["error"]["code"], "UNKNOWN_TOP_LEVEL_FIELD")

    def test_15_protocol_version_mismatch_is_rejected(self) -> None:
        request = envelope()
        request["protocol_version"] = "2.0"
        response = handle_request(request, self.state)
        self.assertEqual(response["error"]["code"], "UNSUPPORTED_PROTOCOL_VERSION")

    def test_16_invalid_message_id_is_rejected(self) -> None:
        response = handle_request(envelope(message_id="bad id"), self.state)
        self.assertEqual(response["error"]["code"], "INVALID_MESSAGE_ID")

    def test_17_valid_synthetic_observation_is_accepted(self) -> None:
        response = handle_request(envelope(message_type="MOCK_OBSERVATION", payload=observation()), self.state)
        self.assertTrue(response["ok"])
        self.assertEqual(response["payload"]["scope"], "SYNTHETIC_ONLY")

    def test_18_real_or_malicious_url_is_rejected(self) -> None:
        payload = observation()
        payload["product_url"] = "https://www.tw.coupang.com/products/real"
        response = handle_request(envelope(message_type="MOCK_OBSERVATION", payload=payload), self.state)
        self.assertEqual(response["error"]["code"], "URL_NOT_SYNTHETIC")

    def test_19_lookalike_url_is_rejected(self) -> None:
        payload = observation()
        payload["product_url"] = "https://synthetic.invalid.evil.example/products/x"
        response = handle_request(envelope(message_type="MOCK_OBSERVATION", payload=payload), self.state)
        self.assertEqual(response["error"]["code"], "URL_NOT_SYNTHETIC")

    def test_20_boolean_price_is_rejected(self) -> None:
        payload = observation()
        payload["price_minor"] = True
        response = handle_request(envelope(message_type="MOCK_OBSERVATION", payload=payload), self.state)
        self.assertEqual(response["error"]["code"], "INVALID_PRICE")

    def test_21_unknown_observation_field_is_rejected(self) -> None:
        payload = observation()
        payload["shell"] = "powershell"
        response = handle_request(envelope(message_type="MOCK_OBSERVATION", payload=payload), self.state)
        self.assertEqual(response["error"]["code"], "INVALID_OBSERVATION_FIELDS")

    def test_22_exact_duplicate_is_idempotent(self) -> None:
        request = envelope(message_type="MOCK_OBSERVATION", payload=observation())
        first = handle_request(request, self.state)
        second = handle_request(request, self.state)
        self.assertTrue(first["ok"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["payload"], second["payload"])

    def test_23_same_id_with_different_message_is_rejected(self) -> None:
        handle_request(envelope(), self.state)
        response = handle_request(envelope(message_type="STATUS"), self.state)
        self.assertEqual(response["error"]["code"], "MESSAGE_ID_CONFLICT")

    def test_24_non_utc_timestamp_is_rejected(self) -> None:
        payload = observation()
        payload["observed_at"] = "2026-11-02T08:00:00+08:00"
        response = handle_request(envelope(message_type="MOCK_OBSERVATION", payload=payload), self.state)
        self.assertEqual(response["error"]["code"], "INVALID_OBSERVED_AT")


class NativeExecutableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.launcher = HOST_DIR / "native_host_launcher.exe"
        if not cls.launcher.is_file():
            raise RuntimeError("run experiments/B01/build_native_host.ps1 first")

    def run_host(self, payload: bytes) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [str(self.launcher)],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ROOT,
            timeout=10,
            check=False,
        )

    def test_25_compiled_launcher_handles_multiple_packets_without_stdout_pollution(self) -> None:
        payload = encode_frame(envelope("multi-1")) + encode_frame(envelope("multi-2", "STATUS"))
        completed = self.run_host(payload)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        responses = decode_all(completed.stdout)
        self.assertEqual([item["message_id"] for item in responses], ["multi-1", "multi-2"])
        self.assertTrue(all(item["ok"] for item in responses))

    def test_26_oversized_frame_causes_protocol_error_and_host_exit(self) -> None:
        completed = self.run_host(struct.pack("@I", MAX_INCOMING_BYTES + 1))
        self.assertEqual(completed.returncode, 2)
        response = decode_all(completed.stdout)
        self.assertEqual(response[0]["error"]["code"], "INPUT_TOO_LARGE")

    def test_27_truncated_frame_causes_protocol_error_and_host_exit(self) -> None:
        completed = self.run_host(struct.pack("@I", 50) + b"{}")
        self.assertEqual(completed.returncode, 2)
        response = decode_all(completed.stdout)
        self.assertEqual(response[0]["error"]["code"], "TRUNCATED_FRAME")

    def test_28_host_restart_after_protocol_crash_accepts_new_handshake(self) -> None:
        crashed = self.run_host(struct.pack("@I", MAX_INCOMING_BYTES + 1))
        restarted = self.run_host(encode_frame(envelope("after-restart")))
        self.assertEqual(crashed.returncode, 2)
        self.assertEqual(restarted.returncode, 0)
        self.assertTrue(decode_all(restarted.stdout)[0]["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
