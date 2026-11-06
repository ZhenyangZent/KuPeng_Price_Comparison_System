from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
import shutil
from pathlib import Path

from tools.ci_web_g06.audit import audit_zip


class AuditTests(unittest.TestCase):
    def tearDown(self):
        for path in getattr(self, "_temps", []):
            shutil.rmtree(path, ignore_errors=True)

    def _archive(self, files: dict[str, bytes], *, bom: bool = False) -> tuple[Path, str]:
        base = Path.cwd() / "review" / "G06" / "test_tmp"; base.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(dir=base)); self._temps = [*getattr(self, "_temps", []), temp]
        path = temp / "release.zip"
        payloads = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()]
        manifest = json.dumps({"payloads": payloads}).encode(); manifest = (b"\xef\xbb\xbf" + manifest) if bom else manifest
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items(): archive.writestr(f"release/{name}", data)
            archive.writestr("release/MANIFEST.json", manifest)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_valid_bom_manifest_passes(self):
        path, digest = self._archive({"value.txt": b"safe"}, bom=True)
        self.assertTrue(audit_zip(path, digest)["passed"])

    def test_wrong_hash_fails(self):
        path, _ = self._archive({"value.txt": b"safe"})
        self.assertFalse(audit_zip(path, "0" * 64)["passed"])

    def test_secret_and_traversal_fail_closed(self):
        path, digest = self._archive({"config.txt": b"api_" + b"key=" + b"ABCDEFGHIJKLMNOPQRSTUV"})
        self.assertFalse(audit_zip(path, digest)["passed"])
        with zipfile.ZipFile(path, "a") as archive: archive.writestr("../escape.txt", b"bad")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertTrue(audit_zip(path, digest)["unsafe"])


if __name__ == "__main__": unittest.main()
