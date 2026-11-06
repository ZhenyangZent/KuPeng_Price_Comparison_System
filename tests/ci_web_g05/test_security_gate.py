from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.ci_web_g05.security_gate import inspect


class SecurityGateTests(unittest.TestCase):
    def setUp(self):
        parent = Path("reports/G05/test_tmp").resolve(); parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent); self.root = Path(self.temp.name)
        self.front = self.root / "front"; self.back = self.root / "back"; (self.front / "src").mkdir(parents=True); (self.back / "services").mkdir(parents=True)

    def tearDown(self): self.temp.cleanup()

    def test_complete_csp_headers_and_clean_urls_pass(self):
        (self.front / "index.html").write_text('<meta http-equiv="Content-Security-Policy" content="default-src \'self\'">', encoding="utf-8")
        (self.front / "src" / "x.ts").write_text("const x='https://example.invalid/path'", encoding="utf-8")
        (self.back / "services" / "api.py").write_text("\n".join(("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy")), encoding="utf-8")
        result = inspect(self.front, self.back); self.assertEqual((result["csp_gate"], result["backend_header_gate"], result["url_leak_gate"]), ("PASS", "PASS", "PASS"))

    def test_missing_csp_and_headers_are_independent_failures(self):
        (self.front / "index.html").write_text("<html>", encoding="utf-8"); (self.back / "services" / "api.py").write_text("", encoding="utf-8")
        result = inspect(self.front, self.back); self.assertEqual((result["csp_gate"], result["backend_header_gate"]), ("FAIL", "FAIL"))

    def test_token_bearing_url_is_rejected(self):
        (self.front / "index.html").write_text("content-security-policy", encoding="utf-8")
        unsafe_url = "https://example.invalid/?to" + "ken=synthetic-secret-value"
        (self.front / "src" / "x.ts").write_text(f"const x='{unsafe_url}'", encoding="utf-8")
        (self.back / "services" / "api.py").write_text("\n".join(("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy")), encoding="utf-8")
        self.assertEqual(inspect(self.front, self.back)["url_leak_gate"], "FAIL")


if __name__ == "__main__": unittest.main()
