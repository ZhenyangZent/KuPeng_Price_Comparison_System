from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.web_security.audit import AffiliatePolicy, audit_tree, validate_affiliate, validate_search_response
from tools.web_security.simulated_web import SimulatedProductService, render_affiliate_cta, render_title

from tests.web.security.helpers import NOW, affiliate, cleanup, search_response, summary, workspace


class OfflineIntegrationMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace()
        self.policy = AffiliatePolicy(
            frozenset({"partners.example.invalid"}),
            "product-1",
            "sku-1",
            NOW,
            official_host_evidence_sha256="a" * 64,
            exact_variant_evidence_sha256="b" * 64,
        )

    def tearDown(self) -> None:
        cleanup(self.root)

    def test_search_title_and_verified_cta_pipeline(self) -> None:
        item = summary(title='<iframe src="https://evil.invalid"></iframe> Coffee')
        service = SimulatedProductService.from_items((item,))
        response = service.search("Coffee")
        self.assertEqual(validate_search_response(response), ())
        rendered_title = render_title(response["items"][0]["title"])
        rendered_cta = render_affiliate_cta(affiliate(), self.policy)
        self.assertNotIn("<iframe", rendered_title)
        self.assertIn("affiliate-cta", rendered_cta)

    def test_failure_matrix_maps_to_a_b_f_owners(self) -> None:
        matrix = {
            "A": validate_search_response(search_response(summary(shipping_status=None))),
            "B": validate_search_response(search_response(summary(last_observed_price_twd=0))),
            "F": validate_affiliate(affiliate(bound_sku_id="other"), self.policy),
        }
        self.assertIn("ITEM_0_SHIPPING_STATUS_INVALID", matrix["A"])
        self.assertIn("ITEM_0_FORGED_OR_UNPROVEN_ZERO", matrix["B"])
        self.assertIn("AFFILIATE_SKU_MISMATCH", matrix["F"])

    def test_review_artifact_scan_reports_actionable_owner(self) -> None:
        artifact = self.root / "dist"
        artifact.mkdir()
        secret_like = "const client_" + "secret='" + ("A" * 24) + "';"
        (artifact / "app.js").write_text(secret_like, encoding="utf-8")
        result = audit_tree(artifact, allowed_root=self.root, owner="A")
        findings = [item for item in result.findings if item.code == "SECRET_LIKE_ASSIGNMENT"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].owner, "A")

    def test_no_live_network_or_browser_dependency_in_guardrail_source(self) -> None:
        forbidden = (
            "import requests",
            "import httpx",
            "import selenium",
            "import playwright",
            "import winreg",
            "import socket",
        )
        for path in Path("tools/web_security").rglob("*.py"):
            text = path.read_text(encoding="utf-8").casefold()
            for token in forbidden:
                self.assertNotIn(token, text, str(path))


if __name__ == "__main__":
    unittest.main()
