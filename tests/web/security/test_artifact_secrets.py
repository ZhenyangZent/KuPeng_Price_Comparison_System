from __future__ import annotations

import unittest
import zipfile
from pathlib import Path

from tools.web_security.audit import audit_tree, audit_zip

from tests.web.security.helpers import cleanup, workspace


SENTINEL = b"SYNTHETIC_D02_SECRET_SENTINEL_7f4b1a"


class TreeArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace()

    def tearDown(self) -> None:
        cleanup(self.root)

    def test_clean_browser_artifact_passes(self) -> None:
        (self.root / "dist").mkdir()
        (self.root / "dist/app.js").write_text("console.log('offline fixture');", encoding="utf-8")
        (self.root / "dist/app.js.map").write_text('{"version":3,"sources":[]}', encoding="utf-8")
        result = audit_tree(self.root / "dist", allowed_root=self.root, sentinels=(SENTINEL,))
        self.assertTrue(result.passed, result.findings)
        self.assertEqual(result.files_scanned, 2)

    def test_secret_sentinel_is_found_in_bundle_map_log_and_screenshot(self) -> None:
        targets = (
            "dist/app.js",
            "dist/app.js.map",
            "logs/browser.log",
            "screenshots/failure.png",
        )
        for relative in targets:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"prefix:" + SENTINEL + b":suffix")
        result = audit_tree(self.root, allowed_root=self.root, sentinels=(SENTINEL,))
        exposed = [item for item in result.findings if item.code == "SECRET_SENTINEL_EXPOSED"]
        self.assertEqual(len(exposed), 4)
        self.assertFalse(result.passed)

    def test_env_and_private_key_filenames_are_rejected_without_reading_real_env(self) -> None:
        (self.root / ".env").write_text("PLACEHOLDER_ONLY=1", encoding="utf-8")
        (self.root / "client.key").write_text("placeholder", encoding="utf-8")
        result = audit_tree(self.root, allowed_root=self.root)
        codes = {item.code for item in result.findings}
        self.assertIn("SENSITIVE_FILENAME", codes)
        self.assertIn("SENSITIVE_FILE_TYPE", codes)

    def test_strictly_inert_env_example_is_allowed(self) -> None:
        (self.root / ".env.example").write_text(
            "# placeholders only\nVITE_API=http://127.0.0.1:8080\nTOKEN=placeholder\n",
            encoding="utf-8",
        )
        result = audit_tree(self.root, allowed_root=self.root)
        self.assertTrue(result.passed, result.findings)
        self.assertEqual(result.findings, ())

    def test_env_example_with_secret_or_external_endpoint_is_critical(self) -> None:
        cases = (
            "API_" + "KEY=" + "abcdefghijklmnopqrstuvwxyz012345\n",
            "VITE_API=https://api.example.com\n",
            "export TOKEN=placeholder\n",
            "DUP=placeholder\nDUP=example\n",
        )
        for index, content in enumerate(cases):
            with self.subTest(index=index):
                target = self.root / str(index)
                target.mkdir()
                (target / ".env.example").write_text(content, encoding="utf-8")
                result = audit_tree(target, allowed_root=self.root)
                self.assertFalse(result.passed)
                self.assertTrue(
                    {item.code for item in result.findings}
                    & {"SECRET_LIKE_ASSIGNMENT", "ENV_EXAMPLE_VALUE_NOT_INERT", "ENV_EXAMPLE_MALFORMED", "ENV_EXAMPLE_KEY_INVALID"}
                )

    def test_outside_allowed_root_is_rejected_before_file_read(self) -> None:
        outside = self.root.parent / "outside.txt"
        outside.write_text("do not read", encoding="utf-8")
        try:
            with self.assertRaisesRegex(ValueError, "AUDIT_TARGET_OUTSIDE_ALLOWED_ROOT"):
                audit_tree(outside, allowed_root=self.root)
        finally:
            outside.unlink()


class ZipArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace()

    def tearDown(self) -> None:
        cleanup(self.root)

    def test_clean_zip_passes_crc_path_and_secret_scan(self) -> None:
        archive = self.root / "clean.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("dist/app.js", "console.log('safe')")
        result = audit_zip(archive, sentinels=(SENTINEL,))
        self.assertTrue(result.passed, result.findings)

    def test_zip_allows_only_inert_env_example(self) -> None:
        safe = self.root / "safe-example.zip"
        with zipfile.ZipFile(safe, "w") as output:
            output.writestr("frontend/.env.example", "VITE_API=http://localhost:8080\n")
        self.assertTrue(audit_zip(safe).passed)
        unsafe = self.root / "unsafe-example.zip"
        with zipfile.ZipFile(unsafe, "w") as output:
            output.writestr("frontend/.env.example", "TOKEN=realistic_secret_material_12345\n")
        result = audit_zip(unsafe)
        self.assertFalse(result.passed)
        self.assertIn("ENV_EXAMPLE_VALUE_NOT_INERT", {item.code for item in result.findings})

    def test_zip_traversal_case_collision_secret_and_env_are_detected(self) -> None:
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("../escape.js", "x")
            output.writestr("dist/App.js", "x")
            output.writestr("dist/app.js", SENTINEL)
            output.writestr("dist/.env.production", "placeholder")
        result = audit_zip(archive, sentinels=(SENTINEL,))
        codes = {item.code for item in result.findings}
        self.assertTrue(
            {"UNSAFE_ZIP_PATH", "DUPLICATE_ZIP_PATH", "SECRET_SENTINEL_EXPOSED", "SENSITIVE_FILENAME"}
            <= codes
        )

    def test_zip_symlink_entry_is_rejected(self) -> None:
        archive = self.root / "symlink.zip"
        info = zipfile.ZipInfo("dist/link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr(info, "../../secret")
        result = audit_zip(archive)
        self.assertIn("ZIP_SYMLINK_DENIED", {item.code for item in result.findings})

    def test_invalid_zip_fails_closed(self) -> None:
        path = self.root / "invalid.zip"
        path.write_bytes(b"not a zip")
        result = audit_zip(path)
        self.assertIn("INVALID_ZIP", {item.code for item in result.findings})


if __name__ == "__main__":
    unittest.main()
