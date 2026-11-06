from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = PROJECT_ROOT / "scripts/orchestrator_handoff"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import package_dependency_audit as audit


LOCAL_TEMP = PROJECT_ROOT / "review/E08/test_tmp"
LOCAL_TEMP.mkdir(parents=True, exist_ok=True)
REF = "review/" + "H03/HISTORICAL_EVIDENCE.json"
HASH = hashlib.sha256(b"external-evidence").hexdigest()


class PackageDependencyAuditTests(unittest.TestCase):
    def make_zip(self, members: dict[str, bytes | str]) -> Path:
        temporary = tempfile.NamedTemporaryFile(suffix=".zip", dir=LOCAL_TEMP, delete=False)
        temporary.close()
        path = Path(temporary.name)
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_missing_historical_evidence_is_rejected(self) -> None:
        path = self.make_zip({"tests/test_h.py": f'EVIDENCE = "{REF}"'})
        with self.assertRaisesRegex(audit.AuditError, "review/H03") as caught:
            audit.audit_zip(path)
        self.assertEqual(caught.exception.code, "UNDECLARED_HISTORICAL_DEPENDENCY")

    def test_bundled_historical_evidence_passes(self) -> None:
        path = self.make_zip({"tests/test_h.py": f'EVIDENCE = "{REF}"', REF: "{}"})
        result = audit.audit_zip(path)
        self.assertEqual(result["bundled_dependency_count"], 1)
        self.assertEqual(result["dependency_gate"], "PASS")

    def test_exact_not_run_dependency_manifest_passes(self) -> None:
        dependency = {
            "schema": "CDH-INPUT-DEPENDENCY-1",
            "dependencies": [{"path": REF, "sha256": HASH, "status": "NOT_RUN_INPUT_UNAVAILABLE"}],
        }
        path = self.make_zip({
            "tests/test_h.py": f'EVIDENCE = "{REF}"',
            "INPUT_DEPENDENCY.json": json.dumps(dependency),
        })
        result = audit.audit_zip(path)
        self.assertEqual(result["not_run_input_unavailable"], [REF])

    def test_wrong_dependency_status_is_rejected(self) -> None:
        dependency = {"dependencies": [{"path": REF, "sha256": HASH, "status": "PASS"}]}
        path = self.make_zip({"INPUT_DEPENDENCY.json": json.dumps(dependency)})
        with self.assertRaises(audit.AuditError) as caught:
            audit.audit_zip(path)
        self.assertEqual(caught.exception.code, "INVALID_DEPENDENCY_STATUS")

    def test_pyc_is_skipped_without_decoding(self) -> None:
        path = self.make_zip({"module.pyc": b"\xff\xfe\x00", "notes.md": "safe"})
        result = audit.audit_zip(path)
        self.assertEqual(result["binary_members_skipped"], 1)
        self.assertEqual(result["text_only_scan_gate"], "PASS")

    def test_env_example_allowed_actual_env_forbidden(self) -> None:
        allowed = self.make_zip({"app/.env.example": "TOKEN=placeholder"})
        self.assertEqual(audit.audit_zip(allowed)["actual_env_gate"], "PASS")
        forbidden = self.make_zip({"app/.env": "TOKEN=secret"})
        with self.assertRaises(audit.AuditError) as caught:
            audit.audit_zip(forbidden)
        self.assertEqual(caught.exception.code, "ACTUAL_ENV_FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
