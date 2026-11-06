from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


BUNDLE = Path(__file__).resolve().parents[1]
PROJECT = BUNDLE.parents[2]


def load_preview():
    spec = importlib.util.spec_from_file_location("a17_preview_server", BUNDLE / "preview_server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class A17TrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.preview = load_preview()
        cls.manifest = json.loads((BUNDLE / "A17_RUNTIME_MANIFEST.json").read_text(encoding="utf-8"))

    def test_runtime_bundle_is_complete_and_hash_bound(self) -> None:
        evidence = self.preview.verify_bundle(BUNDLE)
        self.assertEqual(evidence["file_count"], len(self.manifest["files"]))
        self.assertEqual(len(self.manifest["files"]), 58)
        self.assertEqual(len(self.manifest["source_releases"]), 8)

    def test_b16_rev3_and_required_baseline_carriers_are_exact(self) -> None:
        expected = {
            "CDH_B_R07_001_REVIEW.zip": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
            "CDH_B_R09_001_REVIEW.zip": "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638",
            "CDH_B_R10_001_REVIEW.zip": "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9",
            "CDH_C_R10_002_REVIEW.zip": "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa",
            "CDH_A_R11_004_REVIEW.zip": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
            "CDH_B_R11_002_REVIEW.zip": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
        }
        root = BUNDLE / "vendor" / "baselines"
        self.assertEqual({item.name for item in root.iterdir()}, set(expected))
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(
            self.manifest["source_releases"]["B16_REV3"]["sha256"],
            "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
        )

    def test_manifest_rejects_tampered_runtime(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT / "reports" / "A17") as temporary:
            root = Path(temporary)
            (root / "vendor").mkdir()
            (root / "vendor" / "payload.txt").write_text("tampered", encoding="utf-8")
            (root / "A17_RUNTIME_MANIFEST.json").write_text(
                json.dumps(
                    {
                        "schema_version": "CDH-A17-RUNTIME-BUNDLE-MANIFEST-1",
                        "source_releases": {},
                        "files": [{"path": "payload.txt", "size": 8, "sha256": "0" * 64}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(self.preview.PreviewError, "A17_RUNTIME_BUNDLE_CONTENT_MISMATCH"):
                self.preview.verify_bundle(root)

    def test_runtime_does_not_require_review_release_lookup(self) -> None:
        preview = (BUNDLE / "preview_server.py").read_text(encoding="utf-8")
        control = (BUNDLE / "control.py").read_text(encoding="utf-8")
        common = (BUNDLE / "CDH-Trial.Common.ps1").read_text(encoding="utf-8")
        self.assertNotIn('root / "review" / "releases"', preview)
        self.assertNotIn('root / "review" / "releases"', control)
        self.assertNotIn("CDHExpectedReleases", common)

    def test_private_data_location_is_clear_and_separate(self) -> None:
        start = (BUNDLE / "Start-CDH-Trial.ps1").read_text(encoding="utf-8")
        guide = (PROJECT / "docs" / "user-guides" / "WINDOWS_TRIAL_FIRST_USE_A17.md").read_text(encoding="utf-8")
        self.assertIn("data\\A17_private_history", start)
        self.assertIn("data\\A17_private_history", guide)
        self.assertNotIn("A17_private_history", json.dumps(self.manifest))

    def test_cmd_files_are_crlf_and_machine_mode_preserves_exit(self) -> None:
        for name in ("Start-CDH-Trial.cmd", "Status-CDH-Trial.cmd", "Stop-CDH-Trial.cmd"):
            data = (BUNDLE / name).read_bytes()
            self.assertNotIn(b"\xef\xbb\xbf", data)
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
            self.assertIn(b"%ERRORLEVEL%", data)
            self.assertIn(b"exit /b %CDH_EXIT%", data)

    def test_review_payload_has_no_runtime_private_data_or_secret_files(self) -> None:
        forbidden_names = {".env", "cookies.sqlite", "logins.json", "key4.db", "private_user_observations.sqlite3"}
        self.assertFalse(any(item.name.lower() in forbidden_names for item in BUNDLE.rglob("*")))


if __name__ == "__main__":
    unittest.main()
