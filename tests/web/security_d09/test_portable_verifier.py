from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.web.security_d09.helpers import A09, B11, F06
from tools.web_security_d09.portable import verify_review_target


A09_SHA = "96d239e4a3bb5ca57624c0b8d6e06344ad68b6482b13d8ee9b72a8f1997ebbde"
B11_SHA = "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"
F06_SHA = "c2db9aa981cbc935b52944516d5b4259829ffa5af892ac3dc7d28fc6b022ac89"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_zip(path: Path, payload_names: list[str], *, manifest_separator: str = "/", extra: list[tuple[zipfile.ZipInfo | str, bytes]] | None = None):
    records = []
    content = b"synthetic"
    for name in payload_names:
        relative = name.replace("\\", "/").split("/", 1)[-1]
        records.append({"path": relative, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    raw = json.dumps({"files": records}, sort_keys=True).encode()
    with zipfile.ZipFile(path, "x") as archive:
        for name in payload_names:
            archive.writestr(name, content)
        archive.writestr(f"ROOT{manifest_separator}MANIFEST.json", raw)
        for name, value in extra or []:
            archive.writestr(name, value)
    return path


class ExactPortableTargets(unittest.TestCase):
    def test_legacy_a09_raw_backslashes_pass_without_rewrite(self):
        before = digest(A09)
        result = verify_review_target(A09, A09_SHA)
        self.assertEqual(result.manifest_mismatch_count, 0)
        self.assertEqual(result.manifest_undeclared_count, 0)
        self.assertEqual(digest(A09), before)
        with zipfile.ZipFile(A09) as archive:
            self.assertTrue(any("\\" in item.orig_filename for item in archive.infolist()))

    def test_exact_b11_and_f06_pass_strict_manifest_gate(self):
        for path, expected in ((B11, B11_SHA), (F06, F06_SHA)):
            with self.subTest(path=path.name):
                result = verify_review_target(path, expected)
                self.assertTrue(result.crc_pass)
                self.assertEqual((result.manifest_missing_count, result.manifest_mismatch_count, result.manifest_undeclared_count), (0, 0, 0))

    def test_synthetic_legacy_backslash_archive_passes(self):
        with tempfile.TemporaryDirectory(dir=Path("review/D09/001").resolve()) as folder:
            target = make_zip(Path(folder) / "legacy.zip", [r"ROOT\payload.txt"], manifest_separator="\\")
            result = verify_review_target(target, digest(target))
            self.assertEqual(result.manifest_path, "ROOT/MANIFEST.json")


class EvilArchiveRejections(unittest.TestCase):
    def rejection(self, member: str, code: str):
        with tempfile.TemporaryDirectory(dir=Path("review/D09/001").resolve()) as folder:
            target = Path(folder) / "evil.zip"
            written = member.replace("\\", "/") if "\\" in member and "/" in member else member
            make_zip(target, [written])
            if written != member:
                raw = target.read_bytes()
                self.assertEqual(len(written.encode()), len(member.encode()))
                self.assertEqual(raw.count(written.encode()), 2)
                target.write_bytes(raw.replace(written.encode(), member.encode()))
            with self.assertRaisesRegex(ValueError, code):
                verify_review_target(target, digest(target))

    def test_absolute_drive_traversal_and_separator_rejections(self):
        cases = (
            ("/absolute.txt", "ABSOLUTE_OR_DRIVE"), (r"C:\drive.txt", "ABSOLUTE_OR_DRIVE"),
            (r"ROOT\..\escape.txt", "TRAVERSAL"), (r"ROOT\\double.txt", "AMBIGUOUS_SEPARATOR"),
            (r"ROOT\mixed/path.txt", "AMBIGUOUS_SEPARATOR"), ("ROOT/.hidden", "CONCEALED_DOTFILE"),
            ("ROOT/file.txt:ads", "CONCEALED_WINDOWS_NAME"), ("ROOT/evil\u202e.txt", "CONTROL_OR_BIDI"),
        )
        for member, code in cases:
            with self.subTest(member=member):
                self.rejection(member, code)

    def test_casefold_duplicate_rejected_after_normalization(self):
        with tempfile.TemporaryDirectory(dir=Path("review/D09/001").resolve()) as folder:
            target = make_zip(Path(folder) / "duplicate.zip", ["ROOT/File.txt", "ROOT/file.txt"])
            with self.assertRaisesRegex(ValueError, "CASEFOLD_DUPLICATE"):
                verify_review_target(target, digest(target))

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path("review/D09/001").resolve()) as folder:
            info = zipfile.ZipInfo("ROOT/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            target = make_zip(Path(folder) / "symlink.zip", ["ROOT/payload.txt"], extra=[(info, b"payload.txt")])
            with self.assertRaisesRegex(ValueError, "ZIP_SAFETY_FAILURE"):
                verify_review_target(target, digest(target))

    def test_undeclared_extra_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path("review/D09/001").resolve()) as folder:
            target = make_zip(Path(folder) / "extra.zip", ["ROOT/payload.txt"], extra=[("ROOT/extra.txt", b"extra")])
            with self.assertRaisesRegex(ValueError, "UNDECLARED_FILES"):
                verify_review_target(target, digest(target))


if __name__ == "__main__":
    unittest.main()
