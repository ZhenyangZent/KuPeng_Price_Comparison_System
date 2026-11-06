from __future__ import annotations

import unittest

from tools.web_security_d06.targets import read_unique_member
from tools.web_security_d07.header_policy import assess_header_set, backend_literal_headers, frontend_meta_headers
from tests.web.security_d07.helpers import A08, B09_002


SECURE_CSP = (
    "default-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'none'; img-src 'self' data:"
)
SECURE_HEADERS = {
    "Content-Security-Policy": SECURE_CSP,
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}


class HeaderPolicyTests(unittest.TestCase):
    def test_a08_frontend_baseline_fails_before_gate(self) -> None:
        index = read_unique_member(A08, "apps/price-web/frontend/index.html").decode("utf-8-sig")
        value = assess_header_set(frontend_meta_headers(index), require_frame=False, require_permissions=False)
        self.assertFalse(value["passed"])
        self.assertIn("CSP_MISSING", value["reasons"])
        self.assertIn("REFERRER_POLICY_MISSING", value["reasons"])

    def test_b09_002_api_baseline_fails_before_gate(self) -> None:
        source = read_unique_member(B09_002, "services/price_query_v3/price_query_v3/api.py").decode("utf-8-sig")
        value = assess_header_set(backend_literal_headers(source))
        self.assertFalse(value["passed"])
        self.assertIn("CSP_MISSING", value["reasons"])
        self.assertIn("X_FRAME_OPTIONS_MISSING", value["reasons"])
        self.assertIn("PERMISSIONS_POLICY_MISSING", value["reasons"])

    def test_restrictive_after_fixture_passes(self) -> None:
        value = assess_header_set(SECURE_HEADERS)
        self.assertTrue(value["passed"], value["reasons"])

    def test_wildcard_does_not_masquerade_as_csp_pass(self) -> None:
        headers = dict(SECURE_HEADERS)
        headers["Content-Security-Policy"] = SECURE_CSP + "; img-src *"
        value = assess_header_set(headers)
        self.assertFalse(value["passed"])
        self.assertTrue(any("UNSAFE" in reason for reason in value["reasons"]))

    def test_unsafe_inline_and_eval_fail(self) -> None:
        headers = dict(SECURE_HEADERS)
        headers["Content-Security-Policy"] = SECURE_CSP.replace("script-src 'self'", "script-src 'self' 'unsafe-inline' 'unsafe-eval'")
        value = assess_header_set(headers)
        self.assertFalse(value["passed"])

    def test_https_scheme_allow_all_fails(self) -> None:
        headers = dict(SECURE_HEADERS)
        headers["Content-Security-Policy"] = SECURE_CSP.replace("connect-src 'self'", "connect-src 'self' https:")
        self.assertFalse(assess_header_set(headers)["passed"])

    def test_incomplete_permissions_policy_fails(self) -> None:
        headers = dict(SECURE_HEADERS)
        headers["Permissions-Policy"] = "camera=(), microphone=()"
        value = assess_header_set(headers)
        self.assertFalse(value["passed"])
        self.assertIn("PERMISSIONS_POLICY_NOT_DENIED:payment", value["reasons"])

    def test_sameorigin_frame_policy_fails_strict_deny_gate(self) -> None:
        headers = dict(SECURE_HEADERS)
        headers["X-Frame-Options"] = "SAMEORIGIN"
        self.assertFalse(assess_header_set(headers)["passed"])


if __name__ == "__main__":
    unittest.main()
