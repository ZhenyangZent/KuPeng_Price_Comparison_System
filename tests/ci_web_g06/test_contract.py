from __future__ import annotations

import json
import unittest
from pathlib import Path


class ContractTests(unittest.TestCase):
    def test_role_contract_has_no_stub_pass(self):
        source = Path("tools/ci_web_g06/runner.py").read_text(encoding="utf-8")
        self.assertIn("NOT_RUN_INPUT_UNAVAILABLE", source)
        self.assertIn("EXPECTED_WIRE_FAILURE_REPRODUCED", source)
        self.assertNotIn('status, code = "PASS"', source)

    def test_preview_workflows_are_non_deploying(self):
        for path in (Path("docs/CI_PREVIEW/G06/windows-preview.yml"), Path("docs/CI_PREVIEW/G06/linux-preview.yml")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("deploy", text.casefold())
            self.assertNotIn("npm install", text.casefold())


if __name__ == "__main__": unittest.main()
