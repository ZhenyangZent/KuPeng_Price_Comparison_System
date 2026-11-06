from __future__ import annotations

import hashlib
import json
import shutil
import socket
import sys
import unittest
import zipfile
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parents[2]
sys.path.insert(0, str(MODULE_ROOT))

import control  # noqa: E402
import preview_server  # noqa: E402


class PreviewUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = PROJECT_ROOT / "reports" / "A11" / "unit_test_tmp"
        if cls.base.exists():
            shutil.rmtree(cls.base)
        cls.base.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.base.exists():
            shutil.rmtree(cls.base)

    def test_pinned_release_hashes_are_exact(self) -> None:
        result = control.verify_inputs(PROJECT_ROOT)
        self.assertEqual(result["a10_r08_sha256"], preview_server.A10_SHA256)
        self.assertEqual(result["b11_r07_sha256"], preview_server.B11_SHA256)
        self.assertEqual(result["b15_r11_rev2_sha256"], preview_server.B15_SHA256)
        self.assertEqual(result["b16_r12_sha256"], preview_server.B16_SHA256)

    def test_hash_mismatch_is_fail_closed(self) -> None:
        candidate = self.base / "wrong.zip"
        candidate.write_bytes(b"not the pinned release")
        with self.assertRaisesRegex(preview_server.PreviewError, "SHA256_MISMATCH"):
            preview_server.verify_pinned_release(candidate, "0" * 64, "TEST")

    def test_archive_path_traversal_is_refused(self) -> None:
        with self.assertRaisesRegex(preview_server.PreviewError, "UNSAFE_ARCHIVE_MEMBER"):
            preview_server._safe_relative(preview_server.SERVICE_PREFIX + "../escape.py", preview_server.SERVICE_PREFIX)

    def test_exact_b11_service_extracts_and_rechecks(self) -> None:
        release = PROJECT_ROOT / "review" / "releases" / "CDH_B_R07_001_REVIEW.zip"
        runtime = self.base / "runtime"
        first = preview_server.ensure_exact_b11(release, runtime)
        second = preview_server.ensure_exact_b11(release, runtime)
        self.assertEqual(first, second)
        self.assertTrue((first / "price_coupon_v4" / "api.py").is_file())

    def test_tampered_runtime_is_refused_without_overwrite(self) -> None:
        release = PROJECT_ROOT / "review" / "releases" / "CDH_B_R07_001_REVIEW.zip"
        runtime = self.base / "tampered-runtime"
        target = preview_server.ensure_exact_b11(release, runtime)
        api = target / "price_coupon_v4" / "api.py"
        original = api.read_bytes()
        api.write_bytes(original + b"\n# tampered\n")
        with self.assertRaisesRegex(preview_server.PreviewError, "RUNTIME_CONTENT_MISMATCH"):
            preview_server.ensure_exact_b11(release, runtime)
        self.assertEqual(api.read_bytes(), original + b"\n# tampered\n")

    def test_receipt_atomic_write_roundtrip(self) -> None:
        receipt = self.base / "state" / "active.json"
        control.atomic_json(receipt, {"schema": "test", "port": 4174})
        self.assertEqual(control.read_receipt(receipt), {"schema": "test", "port": 4174})
        self.assertFalse(receipt.with_suffix(".json.tmp").exists())

    def test_control_token_is_not_stored_in_receipt_shape(self) -> None:
        token = "secret-token-for-test"
        receipt = {"control_token_sha256": hashlib.sha256(token.encode()).hexdigest()}
        self.assertNotIn(token, json.dumps(receipt))

    def test_port_probe_detects_an_owned_listener(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            self.assertFalse(control.port_free(listener.getsockname()[1]))

    def test_b11_release_crc_is_clean(self) -> None:
        release = PROJECT_ROOT / "review" / "releases" / "CDH_B_R07_001_REVIEW.zip"
        with zipfile.ZipFile(release) as archive:
            self.assertIsNone(archive.testzip())

    def test_exact_b15_service_extracts_and_rechecks(self) -> None:
        release = PROJECT_ROOT / "review" / "releases" / "CDH_B_R11_002_REVIEW.zip"
        runtime = self.base / "b15-runtime"
        first = preview_server.ensure_exact_b15(release, runtime)
        second = preview_server.ensure_exact_b15(release, runtime)
        self.assertEqual(first, second)
        self.assertTrue((first / "private_observation_b15" / "api.py").is_file())

    def test_b15_release_crc_is_clean(self) -> None:
        release = PROJECT_ROOT / "review" / "releases" / "CDH_B_R11_002_REVIEW.zip"
        with zipfile.ZipFile(release) as archive:
            self.assertIsNone(archive.testzip())

    def test_exact_b16_services_extract_and_recheck(self) -> None:
        release = PROJECT_ROOT / "review" / "releases" / "CDH_B_R12_003_REVIEW.zip"
        runtime = self.base / "b16-runtime"
        first = preview_server.ensure_exact_b16(release, runtime)
        second = preview_server.ensure_exact_b16(release, runtime)
        self.assertEqual(first, second)
        self.assertTrue((first / "private_batch_import_b16" / "private_batch_import_b16" / "api.py").is_file())
        self.assertTrue((first / "private_observation_b15" / "private_observation_b15" / "api.py").is_file())

    def test_b16_release_crc_is_clean(self) -> None:
        release = PROJECT_ROOT / "review" / "releases" / "CDH_B_R12_003_REVIEW.zip"
        with zipfile.ZipFile(release) as archive:
            self.assertIsNone(archive.testzip())

    def test_b16_store_is_bound_to_explicit_project_root(self) -> None:
        release = PROJECT_ROOT / "review" / "releases" / "CDH_B_R12_003_REVIEW.zip"
        service = preview_server.ensure_exact_b16(release, self.base / "b16-wsgi-runtime")
        allowed = self.base / "b16-allowed-project"
        allowed.mkdir()
        app = preview_server.create_b16_wsgi(service, allowed / "isolated-data", allowed, PROJECT_ROOT / "review" / "releases", ("http://127.0.0.1:4174",))
        self.assertIsNotNone(app)
        with self.assertRaisesRegex(Exception, "below the allowed project root"):
            preview_server.create_b16_wsgi(service, self.base / "outside-b16-data", allowed, PROJECT_ROOT / "review" / "releases", ("http://127.0.0.1:4174",))

    def test_b15_rev2_store_is_bound_to_explicit_project_root(self) -> None:
        release = PROJECT_ROOT / "review" / "releases" / "CDH_B_R11_002_REVIEW.zip"
        service = preview_server.ensure_exact_b15(release, self.base / "b15-wsgi-runtime")
        allowed = self.base / "allowed-project"
        allowed.mkdir()
        app = preview_server.create_b15_wsgi(
            service,
            allowed / "isolated-data",
            allowed,
            PROJECT_ROOT / "review" / "releases",
            ("http://127.0.0.1:4174",),
        )
        self.assertIsNotNone(app)
        with self.assertRaisesRegex(Exception, "below the allowed project root"):
            preview_server.create_b15_wsgi(
                service,
                self.base / "outside-data",
                allowed,
                PROJECT_ROOT / "review" / "releases",
                ("http://127.0.0.1:4174",),
            )

    def test_dist_manifest_binds_every_built_file(self) -> None:
        result = preview_server.verify_dist(PROJECT_ROOT / "apps" / "price-web" / "frontend" / "dist")
        self.assertGreaterEqual(result["file_count"], 3)
        self.assertEqual(len(result["manifest_sha256"]), 64)

    def test_proxy_preserves_exact_b16_request_limits(self) -> None:
        source = (PROJECT_ROOT / "apps" / "price-web" / "local-preview-a11" / "preview_server.py").read_text(encoding="utf-8")
        self.assertIn('1_500_000 if path == "/api/private-observations/v1/batch-preview"', source)
        self.assertIn('16 * 1024 if path == "/api/private-observations/v1/batch-confirm"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
