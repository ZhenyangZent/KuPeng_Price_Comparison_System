from __future__ import annotations

import unittest

from tools.web_security_d05.frontend import assess_frontend
from tools.web_security_d05.targets import read_unique_member
from tests.web.security_d05.helpers import RELEASES


def text(zip_name: str, suffix: str) -> str:
    return read_unique_member(RELEASES / zip_name, suffix).decode("utf-8-sig")


class A06SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checks, cls.findings = assess_frontend(
            typescript_types=text("CDH_A06_001_REVIEW.zip", "apps/price-web/frontend/src/types.ts"),
            local_api=text("CDH_A06_001_REVIEW.zip", "apps/price-web/frontend/src/localApi.ts"),
            affiliate=text("CDH_A06_001_REVIEW.zip", "apps/price-web/frontend/src/affiliate.ts"),
            app=text("CDH_A06_001_REVIEW.zip", "apps/price-web/frontend/src/App.tsx"),
            vite_config=text("CDH_A06_001_REVIEW.zip", "apps/price-web/frontend/vite.config.ts"),
            index_html=text("CDH_A06_001_REVIEW.zip", "apps/price-web/frontend/index.html"),
            api_source=text("CDH_B06_001_REVIEW.zip", "services/price_query/price_query/api.py"),
        )

    def test_loopback_same_origin_and_no_cors_pass(self) -> None:
        by_id = {item.check_id: item for item in self.checks}
        self.assertTrue(by_id["LOOPBACK_SAME_ORIGIN_NO_CORS"].passed)

    def test_react_rendering_has_no_raw_html_sink(self) -> None:
        by_id = {item.check_id: item for item in self.checks}
        self.assertTrue(by_id["REACT_TEXT_RENDERING_NO_RAW_HTML"].passed)

    def test_cta_current_policy_is_fail_closed(self) -> None:
        by_id = {item.check_id: item for item in self.checks}
        self.assertTrue(by_id["CTA_FAIL_CLOSED_WITHOUT_TW_AUTHORITY"].passed)
        self.assertNotIn("D05-P0-003", {item.finding_id for item in self.findings})

    def test_v1_downgrade_and_missing_csp_are_detected(self) -> None:
        ids = {item.finding_id for item in self.findings}
        self.assertIn("D05-P1-001", ids)
        self.assertIn("D05-P2-001", ids)
        self.assertIn("D05-P2-002", ids)


if __name__ == "__main__":
    unittest.main()
