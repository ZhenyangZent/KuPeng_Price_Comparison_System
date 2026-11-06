from __future__ import annotations
import unittest
from pathlib import Path

class SafetyTests(unittest.TestCase):
    def test_stack_is_loopback_and_proxy_is_read_only(self):
        source=Path("tools/ci_web_g08/stack_server.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count('"127.0.0.1"'),3); self.assertNotIn('("0.0.0.0"',source)
        self.assertNotIn("do_PUT",source); self.assertNotIn("do_DELETE",source)
    def test_browser_requires_network_dom_and_screenshot(self):
        source=Path("tools/ci_web_g08/browser_probe.mjs").read_text(encoding="utf-8")
        for term in ("network.har","domRoot","Page.captureScreenshot","real_browser_search_requests","retry_click_recovered"): self.assertIn(term,source)
    def test_import_probe_requires_zero_writes_and_denial(self):
        source=Path("tools/ci_web_g08/import_probe.py").read_text(encoding="utf-8")
        self.assertIn("database_write_zero",source); self.assertIn("default_source_denied",source); self.assertIn("b11_sqlite_unchanged",source)

if __name__=="__main__": unittest.main()
