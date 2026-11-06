from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tools.web_security_d06.targets import read_unique_member, verify_target

from .adapter_flow import run_exact_a08_b09_002_flow
from .coupon_policy import CouponContractError, evaluate_coupon_v4
from .header_policy import assess_header_set, backend_literal_headers, frontend_meta_headers
from .synthetic_cases import IDENTITY, confirmed_payload, history_point, unconfirmed_payload


A08_SHA = "5235d0842cc13b469dc52662d1eb3641134f542046c50cf030eb136a7b69e71d"
B09_002_SHA = "35539f8d3434540c660ff51613e636c443ffc06b237806bc53f32db1e78e62e3"
NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)


def _case(name: str, function: Callable[[], Any], check: Callable[[Any], bool]) -> dict[str, object]:
    try:
        value = function()
        passed = bool(check(value))
        return {"name": name, "passed": passed, "value": value, "error": None}
    except CouponContractError as exc:
        return {"name": name, "passed": False, "value": None, "error": {"code": exc.code, "detail": exc.detail}}


def _reject_case(name: str, function: Callable[[], Any], expected_code: str) -> dict[str, object]:
    try:
        function()
        return {"name": name, "passed": False, "value": None, "error": "ACCEPTED_UNSAFE_INPUT"}
    except CouponContractError as exc:
        return {"name": name, "passed": exc.code == expected_code, "value": None, "error": {"code": exc.code, "detail": exc.detail}}


def run_coupon_cases() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    results.append(_case(
        "T01_CONFIRMED_COUPON_FIRST",
        lambda: evaluate_coupon_v4(confirmed_payload(), now=NOW, expected_identity=IDENTITY, eligibility_profile="SYN-ELIGIBLE-PROFILE"),
        lambda value: value["display_price_twd"] == 49 and value["base_price_twd"] == 99 and value["coupon_applied"] is True,
    ))
    for status in ("CLAIM_REQUIRED", "UNVERIFIED", "INELIGIBLE", "EXPIRED", "UNKNOWN", "NONE"):
        results.append(_case(
            f"T02_{status}_FALLS_BACK",
            lambda status=status: evaluate_coupon_v4(unconfirmed_payload(status), now=NOW, expected_identity=IDENTITY),
            lambda value: value["display_price_twd"] == 99 and value["confirmed_coupon_price_twd"] is None and value["coupon_applied"] is False,
        ))

    included = confirmed_payload()
    included["base_price_twd"] = 49
    included["coupon"]["already_included_in_base"] = True
    included["confirmed_coupon_price_twd"] = 49
    included["display_price_twd"] = 49
    results.append(_case(
        "T03_ALREADY_INCLUDED_NO_DOUBLE_DISCOUNT",
        lambda: evaluate_coupon_v4(included, now=NOW, expected_identity=IDENTITY, eligibility_profile="SYN-ELIGIBLE-PROFILE"),
        lambda value: value["display_price_twd"] == 49,
    ))

    quantity = confirmed_payload()
    quantity["base_price_twd"] = 100
    quantity["confirmed_coupon_price_twd"] = 75
    quantity["display_price_twd"] = 75
    quantity["shipping_status"] = "FREE"
    quantity["required_total_twd"] = 150
    results.append(_case(
        "T04_ORDER_COUPON_QUANTITY",
        lambda: evaluate_coupon_v4(quantity, now=NOW, expected_identity=IDENTITY, eligibility_profile="SYN-ELIGIBLE-PROFILE", minimum_purchase_quantity=2, discount_scope="ORDER"),
        lambda value: value["display_price_twd"] == 75 and value["required_total_twd"] == 150,
    ))

    mismatch = deepcopy(IDENTITY)
    mismatch["sku_id"] = "SYN-SKU-OTHER"
    results.append(_reject_case(
        "T05_WRONG_SKU_REJECTED",
        lambda: evaluate_coupon_v4(confirmed_payload(), now=NOW, expected_identity=mismatch),
        "REQUEST_IDENTITY_MISMATCH",
    ))

    history = confirmed_payload()
    history["history"]["before_coupon"] = [history_point(price=99)]
    history["history"]["confirmed_after_coupon"] = [history_point(price=59, after=True)]
    results.append(_case(
        "T06_HISTORY_BRANCHES_PRESERVED",
        lambda: evaluate_coupon_v4(history, now=NOW, expected_identity=IDENTITY, eligibility_profile="SYN-ELIGIBLE-PROFILE"),
        lambda value: value["history"]["before_coupon"][0]["price_twd"] == 99 and value["history"]["confirmed_after_coupon"][0]["price_twd"] == 59 and value["display_price_twd"] == 49,
    ))

    results.append(_case(
        "T07_UNKNOWN_SHIPPING_NO_REQUIRED_TOTAL",
        lambda: evaluate_coupon_v4(confirmed_payload(), now=NOW, expected_identity=IDENTITY, eligibility_profile="SYN-ELIGIBLE-PROFILE"),
        lambda value: value["display_price_twd"] == 49 and value["required_total_twd"] is None,
    ))

    eligibility = confirmed_payload()
    eligibility["display_price_twd"] = 99
    eligibility["display_basis"] = "BASE_PRICE"
    eligibility["required_total_twd"] = None
    results.append(_case(
        "T08_ELIGIBILITY_MISMATCH_FAILS_CLOSED",
        lambda: evaluate_coupon_v4(eligibility, now=NOW, expected_identity=IDENTITY, eligibility_profile="SYN-DIFFERENT-PROFILE"),
        lambda value: value["coupon_applied"] is False and "ELIGIBILITY_PROFILE_MISMATCH" in value["reasons"],
    ))

    unauthorized = confirmed_payload()
    unauthorized["data_classification"] = "USER_RECORDED"
    unauthorized["source_id"] = "USER-SOURCE"
    results.append(_reject_case(
        "T09_UNAUTHORIZED_SOURCE_REJECTED",
        lambda: evaluate_coupon_v4(unauthorized, now=NOW, expected_identity=IDENTITY),
        "SOURCE_NOT_AUTHORIZED",
    ))

    zero = confirmed_payload()
    zero["base_price_twd"] = 50
    zero["confirmed_coupon_price_twd"] = 0
    zero["display_price_twd"] = 0
    zero["shipping_status"] = "FREE"
    zero["required_total_twd"] = 0
    results.append(_case(
        "T10_ZERO_IS_NOT_NULL",
        lambda: evaluate_coupon_v4(zero, now=NOW, expected_identity=IDENTITY, eligibility_profile="SYN-ELIGIBLE-PROFILE"),
        lambda value: value["display_price_twd"] == 0 and value["confirmed_coupon_price_twd"] == 0,
    ))

    unknown = unconfirmed_payload("NONE")
    unknown["base_price_twd"] = None
    unknown["possible_coupon_price_twd"] = None
    unknown["display_price_twd"] = None
    unknown["display_basis"] = "PRICE_UNKNOWN"
    results.append(_case(
        "T10_NULL_REMAINS_UNKNOWN",
        lambda: evaluate_coupon_v4(unknown, now=NOW, expected_identity=IDENTITY),
        lambda value: value["display_price_twd"] is None and value["display_basis"] == "PRICE_UNKNOWN",
    ))

    csv_attack = confirmed_payload()
    csv_attack["coupon"]["scope_evidence"] = "=WEBSERVICE(unsafe)"
    results.append(_reject_case(
        "T12_CSV_FORMULA_REJECTED",
        lambda: evaluate_coupon_v4(csv_attack, now=NOW, expected_identity=IDENTITY),
        "TEXT_INJECTION",
    ))
    url_attack = confirmed_payload()
    url_attack["redirect_url"] = "https://example.invalid/redirect?token=secret"
    results.append(_reject_case(
        "T12_URL_AND_UNKNOWN_FIELD_REJECTED",
        lambda: evaluate_coupon_v4(url_attack, now=NOW, expected_identity=IDENTITY),
        "INVALID_FIELDS",
    ))
    results.append(_case(
        "CTA_ALWAYS_DISABLED",
        lambda: evaluate_coupon_v4(confirmed_payload(), now=NOW, expected_identity=IDENTITY, eligibility_profile="SYN-ELIGIBLE-PROFILE"),
        lambda value: value["cta_enabled"] is False and value["cta_url"] is None,
    ))
    return results


def run_gate(frontend_zip: Path, backend_zip: Path) -> dict[str, object]:
    frontend_identity = verify_target(frontend_zip, expected_sha256=A08_SHA)
    backend_identity = verify_target(backend_zip, expected_sha256=B09_002_SHA)
    index = read_unique_member(frontend_zip, "apps/price-web/frontend/index.html").decode("utf-8-sig")
    api = read_unique_member(backend_zip, "services/price_query_v3/price_query_v3/api.py").decode("utf-8-sig")
    frontend_headers = assess_header_set(frontend_meta_headers(index), require_frame=False, require_permissions=False)
    backend_headers = assess_header_set(backend_literal_headers(api), require_frame=True, require_permissions=True)
    flow = run_exact_a08_b09_002_flow(frontend_zip, backend_zip)
    cases = run_coupon_cases()
    coupon_passed = sum(bool(item["passed"]) for item in cases)
    findings: list[dict[str, str]] = []
    if not frontend_headers["passed"]:
        findings.append({
            "finding_id": "D07-P2-001", "priority": "P2", "owner": "A",
            "title": "A08 frontend response policy lacks restrictive CSP/referrer controls",
            "detail": ";".join(frontend_headers["reasons"]),
        })
    if not backend_headers["passed"]:
        findings.append({
            "finding_id": "D07-P2-002", "priority": "P2", "owner": "B",
            "title": "B09-002 API response policy lacks complete restrictive security headers",
            "detail": ";".join(backend_headers["reasons"]),
        })
    if coupon_passed != len(cases):
        findings.append({
            "finding_id": "D07-P1-001", "priority": "P1", "owner": "D",
            "title": "D07 synthetic V4 coupon reference gate has failing cases",
            "detail": f"passed={coupon_passed}/{len(cases)}",
        })
    if flow["parser_failure_count"] or flow["v2_raw_min_twd"] != 10 or flow["v2_reported_min_twd"] != 10 or flow["v3_daily_representative_low_twd"] != 20:
        findings.append({
            "finding_id": "D07-P1-002", "priority": "P1", "owner": "A/B",
            "title": "Exact A08/B09-002 compatibility regression",
            "detail": f"parser={flow['parser_success_count']}/{flow['parser_call_count']}; raw={flow['v2_raw_min_twd']}; v2={flow['v2_reported_min_twd']}; v3={flow['v3_daily_representative_low_twd']}",
        })
    counts = {priority: sum(item["priority"] == priority for item in findings) for priority in ("P0", "P1", "P2")}
    return {
        "schema": "CDH-D07-COUPON-HEADER-SECURITY-GATE-1",
        "task_id": "CDH-D07-COUPON-AND-HEADER-SECURITY-001",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_identity_gate": "PASS",
        "integration_acceptance": "PASS_WITH_P2" if counts["P0"] + counts["P1"] == 0 else "BLOCKED",
        "priority_counts": counts,
        "targets": [frontend_identity.as_dict(), backend_identity.as_dict()],
        "baseline_headers": {"frontend": frontend_headers, "backend": backend_headers},
        "exact_adapter_flow": flow,
        "coupon_cases": {"executed": len(cases), "passed": coupon_passed, "results": cases},
        "findings": findings,
        "restrictions": {
            "offline_only": True, "synthetic_only": True, "target_code_mutated": False,
            "real_env_read": False, "live_network_count": 0, "browser_profile_access_count": 0,
            "affiliate_click_count": 0, "shopping_action_count": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="D07 coupon/header security gate")
    parser.add_argument("--frontend-zip", type=Path, required=True)
    parser.add_argument("--backend-zip", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = run_gate(args.frontend_zip, args.backend_zip)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 2 if result["priority_counts"]["P0"] + result["priority_counts"]["P1"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
