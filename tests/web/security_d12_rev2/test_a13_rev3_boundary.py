from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
A13 = ROOT / "review/D12/002/input_a13_rev3/CDH_A_R11_003_REVIEW"
EVIDENCE = ROOT / "review/D12/002/evidence"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class A13Rev3BoundaryAddendumTests(unittest.TestCase):
    def test_01_exact_selected_sources_match_a13_manifest(self):
        manifest_path = A13 / "SHA256_MANIFEST.json"
        self.assertEqual(sha256(manifest_path), "e17bd9f625889a5d29e2a556dcb02d4feb4c20016f94e838adc10d54d0ff3423")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = {item["path"]: item for item in manifest["payloads"]}
        selected = (
            "apps/price-web/local-preview-a11/preview_server.py",
            "apps/price-web/local-preview-a11/control.py",
            "apps/price-web/frontend/src/manualObservationClient.ts",
            "apps/price-web/frontend/tests/a13_manual_observation.test.tsx",
        )
        for relative in selected:
            with self.subTest(relative=relative):
                path = A13 / relative
                self.assertEqual((path.stat().st_size, sha256(path)), (records[relative]["size"], records[relative]["sha256"]))
        preview = (A13 / selected[0]).read_text(encoding="utf-8")
        client = (A13 / selected[2]).read_text(encoding="utf-8")
        self.assertIn('B15_SHA256 = "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe"', preview)
        self.assertIn("allowed_project_root=allowed_project_root", preview)
        self.assertIn('private readonly basePath = "/cdh-private-observations"', client)
        self.assertIn('"backup_cleanup_removed_count"', client)

    def test_02_actual_a13_proxy_to_b15_boundary_evidence_passes(self):
        input_result = json.loads((EVIDENCE / "A13_REV3_INPUT_VERIFICATION.json").read_text(encoding="utf-8"))
        probe = json.loads((EVIDENCE / "A13_REV3_B15_REV2_BOUNDARY.json").read_text(encoding="utf-8"))
        self.assertEqual(input_result["gate"], "PASS")
        self.assertEqual(probe["gate"], "PASS")
        self.assertEqual(probe["a13_rev3_sha256"], "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274")
        self.assertEqual(probe["b15_rev2_sha256"], "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe")
        self.assertEqual(probe["statuses"], [400, 403, 200, 403, 400, 200, 201, 200, 200])
        self.assertTrue(probe["outside_data_root_rejected"])
        self.assertEqual(probe["outside_sqlite_created_count"], 0)
        self.assertTrue(probe["confirmed_coupon_separation"])
        self.assertEqual(probe["external_request_count"], 0)


if __name__ == "__main__":
    unittest.main()
