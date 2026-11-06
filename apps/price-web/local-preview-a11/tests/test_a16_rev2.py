from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
EXPECTED = {
    "CDH_A_R08_001_REVIEW.zip": "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
    "CDH_B_R07_001_REVIEW.zip": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
    "CDH_B_R09_001_REVIEW.zip": "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638",
    "CDH_B_R10_001_REVIEW.zip": "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9",
    "CDH_C_R10_002_REVIEW.zip": "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa",
    "CDH_A_R11_004_REVIEW.zip": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
    "CDH_B_R11_002_REVIEW.zip": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
    "CDH_B_R12_003_REVIEW.zip": "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
}


class A16Rev2Tests(unittest.TestCase):
    def test_document_and_preflight_name_the_same_complete_set(self) -> None:
        common = (ROOT / "scripts" / "windows-mvp" / "CDH-Mvp.Common.ps1").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "user-guides" / "WINDOWS_LOCAL_MVP_FIRST_USE.md").read_text(encoding="utf-8")
        preflight = dict(re.findall(r"File = '([^']+)'; Sha256 = '([0-9a-f]{64})'", common))
        documented = dict(re.findall(r"`(CDH_[A-Z0-9_]+_REVIEW\.zip)` — `([0-9a-f]{64})`", guide))
        self.assertEqual(preflight, EXPECTED)
        self.assertEqual(documented, EXPECTED)

    def test_root_cmd_files_are_crlf_only_and_preserve_exit_code(self) -> None:
        for name in ("Start-CDH-MVP.cmd", "Status-CDH-MVP.cmd", "Stop-CDH-MVP.cmd"):
            payload = (ROOT / name).read_bytes()
            self.assertIn(b"\r\n", payload, name)
            self.assertNotIn(b"\n", payload.replace(b"\r\n", b""), name)
            text = payload.decode("utf-8")
            self.assertIn('set "CDH_EXIT=%ERRORLEVEL%"', text)
            self.assertIn("exit /b %CDH_EXIT%", text)
            self.assertIn('if "%~1"==""', text)
        start = (ROOT / "Start-CDH-MVP.cmd").read_text(encoding="utf-8")
        self.assertNotIn("-NoExit", start)


if __name__ == "__main__":
    unittest.main()
