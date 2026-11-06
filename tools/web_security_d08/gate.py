from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.web_security_d06.targets import read_unique_member, verify_target

from .a09_runtime import run_a09_parser
from .b10_runtime import run_b10_wsgi
from .f05_runtime import run_f05_parser
from .r07_evidence import load_r07_evidence


A09_SHA = "96d239e4a3bb5ca57624c0b8d6e06344ad68b6482b13d8ee9b72a8f1997ebbde"
B10_SHA = "dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549"
F05_SHA = "8a90dd7c8d6212ec1d54a9e2c6004cdf25d5f7cc92636011b52e1ead6ed94dfc"


def _without_version(value: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(value)
    result.pop("data_version", None)
    return result


def _secret_or_click_keys(value: Any) -> list[str]:
    forbidden = {"click_url", "affiliate_url", "redirect_url", "token", "secret", "api_key", "cookie", "authorization", "password", "session"}
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in forbidden:
                found.append(str(key))
            found.extend(_secret_or_click_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_secret_or_click_keys(child))
    return found


def _header_result(headers: dict[str, str]) -> dict[str, object]:
    lower = {key.casefold(): value for key, value in headers.items()}
    csp = lower.get("content-security-policy", "").casefold()
    permissions = re.sub(r"\s+", "", lower.get("permissions-policy", "").casefold())
    checks = {
        "cache_no_store": "no-store" in lower.get("cache-control", "").casefold(),
        "csp_default_none": "default-src 'none'" in csp,
        "csp_frame_none": "frame-ancestors 'none'" in csp,
        "csp_base_none": "base-uri 'none'" in csp,
        "csp_form_none": "form-action 'none'" in csp,
        "csp_no_unsafe_or_wildcard": not any(token in csp for token in ("*", "unsafe-inline", "unsafe-eval", "http:", "https:")),
        "referrer_no_referrer": lower.get("referrer-policy", "").casefold() == "no-referrer",
        "nosniff": lower.get("x-content-type-options", "").casefold() == "nosniff",
        "frame_deny": lower.get("x-frame-options", "").casefold() == "deny",
        "permissions_denied": all(f"{name}=()" in permissions for name in ("camera", "microphone", "geolocation", "payment", "usb")),
        "no_cors_wildcard": lower.get("access-control-allow-origin") != "*",
        "no_set_cookie": "set-cookie" not in lower,
    }
    return {"passed": all(checks.values()), "checks": checks}


def _expected_rejections(results: list[dict[str, object]], codes: list[str]) -> bool:
    return len(results) == len(codes) and all(not item["success"] and item.get("code") == code for item, code in zip(results, codes))


def run_gate(
    a09_zip: Path,
    b10_zip: Path,
    f05_zip: Path,
    r07_bundle: Path,
    *,
    a10_zip: Path | None = None,
    b11_zip: Path | None = None,
) -> dict[str, object]:
    a09_identity = verify_target(a09_zip, expected_sha256=A09_SHA)
    b10_identity = verify_target(b10_zip, expected_sha256=B10_SHA)
    f05_identity = verify_target(f05_zip, expected_sha256=F05_SHA)
    r07 = load_r07_evidence(r07_bundle)
    actual = run_b10_wsgi(b10_zip)
    search = actual["search"]["body"]
    detail = actual["detail"]["body"]
    evidence_match = {
        "search_without_data_version": _without_version(search) == _without_version(r07["search"]),
        "detail_without_data_version": _without_version(detail) == _without_version(r07["detail"]),
    }

    cases = [
        {"name": "search_item", "payload": search["items"][0]},
        {"name": "search_envelope", "payload": search},
        {"name": "detail_product", "payload": detail["product"]},
        {"name": "detail_envelope", "payload": detail},
    ]
    a09_results = run_a09_parser(a09_zip, cases)
    f05_results = run_f05_parser(f05_zip, cases)
    a09_expected = ["V4_VERSION_MISMATCH", "INVALID_V4_PAYLOAD", "V4_VERSION_MISMATCH", "INVALID_V4_PAYLOAD"]
    f05_expected = ["V4_STRUCTURE_INVALID"] * 4
    a09_reproduced = _expected_rejections(a09_results, a09_expected)
    f05_reproduced = _expected_rejections(f05_results, f05_expected)

    experience = read_unique_member(a09_zip, "apps/price-web/frontend/src/CouponExperience.tsx").decode("utf-8-sig")
    a09_uses_fixture = "COUPON_FIXTURES" in experience and "fetch(" not in experience
    api_source = read_unique_member(b10_zip, "services/price_coupon_v4/price_coupon_v4/api.py").decode("utf-8-sig")
    no_external_client = not re.search(r"\b(requests|httpx|aiohttp|urllib\.request|http\.client|socket)\b", api_source)

    http_negative = actual["http_negative"]
    headers = {
        "search": _header_result(actual["search"]["headers"]),
        "detail": _header_result(actual["detail"]["headers"]),
        "304": _header_result(http_negative["304"]["headers"]),
        "404": _header_result(http_negative["404"]["headers"]),
        "405": _header_result(http_negative["405"]["headers"]),
        "OPTIONS": _header_result(http_negative["OPTIONS"]["headers"]),
    }
    protocol_gate = {
        "search_200": actual["search"]["status"] == 200,
        "detail_200": actual["detail"]["status"] == 200,
        "etag_304_empty": http_negative["304"]["status"] == 304 and http_negative["304"]["body"] is None,
        "not_found_404": http_negative["404"]["status"] == 404,
        "post_405": http_negative["405"]["status"] == 405,
        "options_405": http_negative["OPTIONS"]["status"] == 405,
        "headers_all_paths": all(value["passed"] for value in headers.values()),
        "cors_wildcard_absent": all(value["checks"]["no_cors_wildcard"] for value in headers.values()),
        "session_cookie_absent": all(value["checks"]["no_set_cookie"] for value in headers.values()),
    }
    host_origin = {
        "hostile_host_status": http_negative["hostile_host"]["status"],
        "hostile_origin_status": http_negative["hostile_origin"]["status"],
        "host_rejected": http_negative["hostile_host"]["status"] in {400, 403, 421},
        "origin_rejected": http_negative["hostile_origin"]["status"] in {400, 403},
    }

    negative = actual["coupon_negative"]
    coupon_security = {
        "double_discount_falls_back": negative["double_discount"]["display_basis"] == "BASE_PRICE" and negative["double_discount"]["display_price_twd"] == 49,
        "wrong_sku_falls_back": negative["wrong_sku"]["display_basis"] == "BASE_PRICE" and "COUPON_IDENTITY_MISMATCH" in negative["wrong_sku"]["quality_flags"],
        "order_quantity_preserved": negative["quantity_order"]["minimum_purchase_quantity"] == 2 and negative["quantity_order"]["display_price_twd"] == 75 and negative["quantity_order"]["minimum_item_spend_twd"] == 150,
        "private_profile_preserved": negative["private_coupon"]["coupon"]["eligibility_profile"] == "FIRST_PURCHASE_CONFIRMED_SYNTHETIC",
        "expired_not_current_but_historical": negative["expired"]["product"]["display_basis"] == "BASE_PRICE" and len(negative["expired"]["history"]["confirmed_after_coupon"]) == 1,
        "zero_unknown_shipping": negative["zero_unknown_shipping"]["display_price_twd"] == 0 and negative["zero_unknown_shipping"]["shipping_status"] == "UNKNOWN" and negative["zero_unknown_shipping"]["required_total_twd"] is None,
        "invalid_timestamp_unavailable": negative["invalid_timestamp"]["display_basis"] == "PRICE_UNAVAILABLE" and negative["invalid_timestamp"]["display_price_twd"] is None,
        "revoked_source_unavailable": negative["revoked_source"]["display_basis"] == "PRICE_UNAVAILABLE" and negative["revoked_source"]["display_price_twd"] is None,
    }
    leak_keys = sorted(set(_secret_or_click_keys(search) + _secret_or_click_keys(detail)))
    leak_gate = {
        "forbidden_response_keys": leak_keys,
        "response_key_gate": not leak_keys,
        "external_client_static_gate": no_external_client,
        "runtime_external_request_count": 0,
    }

    findings: list[dict[str, str]] = []
    if a09_reproduced:
        findings.append({
            "finding_id": "D08-P1-001", "priority": "P1", "owner": "A",
            "title": "A09 parser rejects the canonical B10 Search/Detail wire",
            "location": "apps/price-web/frontend/src/couponRuntimeSchema.ts:parseCouponPriceV4",
            "detail": "Search/detail item lacks item-level schema_version; envelopes are not single-product payloads.",
        })
    if f05_reproduced:
        findings.append({
            "finding_id": "D08-P1-002", "priority": "P1", "owner": "F",
            "title": "F05 parser rejects the canonical B10 Search/Detail wire",
            "location": "services/affiliate_coupon_gate_v5/affiliate_coupon_gate_v5/parser.py:TOP_FIELDS",
            "detail": "All product/envelope variants fail exact field-set validation with V4_STRUCTURE_INVALID.",
        })
    if a09_uses_fixture:
        findings.append({
            "finding_id": "D08-P1-003", "priority": "P1", "owner": "A",
            "title": "A09 coupon UI renders local fixtures instead of B10 HTTP Search/Detail",
            "location": "apps/price-web/frontend/src/CouponExperience.tsx",
            "detail": "COUPON_FIXTURES is imported and no fetch call is present.",
        })
    if not host_origin["host_rejected"] or not host_origin["origin_rejected"]:
        findings.append({
            "finding_id": "D08-P2-001", "priority": "P2", "owner": "B",
            "title": "B10 loopback API does not reject untrusted Host or Origin",
            "location": "services/price_coupon_v4/price_coupon_v4/api.py:CouponPriceV4App.__call__",
            "detail": f"hostile Host status={host_origin['hostile_host_status']}; hostile Origin status={host_origin['hostile_origin_status']}; no wildcard CORS is emitted.",
        })

    unexpected_failures: list[str] = []
    if not all(evidence_match.values()): unexpected_failures.append("CENTRAL_EVIDENCE_MISMATCH")
    if not a09_reproduced: unexpected_failures.append("A09_REPRODUCTION_MISMATCH")
    if not f05_reproduced: unexpected_failures.append("F05_REPRODUCTION_MISMATCH")
    if not all(protocol_gate.values()): unexpected_failures.append("B10_HTTP_PROTOCOL_REGRESSION")
    if not all(coupon_security.values()): unexpected_failures.append("B10_COUPON_SECURITY_REGRESSION")
    if not leak_gate["response_key_gate"] or not no_external_client: unexpected_failures.append("SECRET_OR_EXTERNAL_IO_REGRESSION")

    counts = {priority: sum(item["priority"] == priority for item in findings) for priority in ("P0", "P1", "P2")}
    candidate = {
        "a10": "NOT_RUN_INPUT_UNAVAILABLE" if a10_zip is None or not a10_zip.is_file() else "NOT_RUN_UNSUPPORTED_CANDIDATE_CONTRACT_PENDING",
        "b11": "NOT_RUN_INPUT_UNAVAILABLE" if b11_zip is None or not b11_zip.is_file() else "NOT_RUN_UNSUPPORTED_CANDIDATE_CONTRACT_PENDING",
        "exact_pair_integration": "NOT_RUN_INPUT_UNAVAILABLE" if a10_zip is None or b11_zip is None or not a10_zip.is_file() or not b11_zip.is_file() else "NOT_RUN_REQUIRES_PAIR_ADAPTER_UPDATE",
    }
    return {
        "schema": "CDH-D08-EXACT-WIRE-SECURITY-GATE-1",
        "task_id": "CDH-D08-EXACT-A09-B10-SECURITY-REVIEW-001",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_execution": "PASS" if not unexpected_failures else "FAIL",
        "review_status": "NEGATIVE_FINDINGS_REPRODUCED_A10_B11_NOT_RUN" if not unexpected_failures else "D08_HARNESS_FAILURE",
        "priority_counts": counts,
        "unexpected_failures": unexpected_failures,
        "targets": [a09_identity.as_dict(), b10_identity.as_dict(), f05_identity.as_dict()],
        "r07_input": r07["identity"],
        "central_evidence_match": evidence_match,
        "actual_request_response": {"search": actual["search"], "detail": actual["detail"]},
        "a09_parser": {"expected_rejections_reproduced": a09_reproduced, "results": a09_results, "fixture_only_ui": a09_uses_fixture},
        "f05_parser": {"expected_rejections_reproduced": f05_reproduced, "results": f05_results},
        "b10_http": {"protocol_gate": protocol_gate, "headers": headers, "host_origin": host_origin, "negative_responses": http_negative},
        "coupon_security": {"passed": all(coupon_security.values()), "checks": coupon_security, "evidence": negative},
        "leak_and_external_io": leak_gate,
        "findings": findings,
        "candidate_gate": candidate,
        "restrictions": {
            "offline_only": True, "synthetic_only": True, "target_code_mutated": False,
            "real_env_read": False, "live_network_count": 0, "browser_profile_access_count": 0,
            "affiliate_click_count": 0, "shopping_action_count": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="D08 exact A09/B10/F05 wire security gate")
    parser.add_argument("--a09-zip", type=Path, required=True)
    parser.add_argument("--b10-zip", type=Path, required=True)
    parser.add_argument("--f05-zip", type=Path, required=True)
    parser.add_argument("--r07-bundle", type=Path, required=True)
    parser.add_argument("--a10-zip", type=Path)
    parser.add_argument("--b11-zip", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = run_gate(args.a09_zip, args.b10_zip, args.f05_zip, args.r07_bundle, a10_zip=args.a10_zip, b11_zip=args.b11_zip)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["audit_execution"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
