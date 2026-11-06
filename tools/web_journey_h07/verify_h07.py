from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H07 = ROOT / "review" / "H07"
EVIDENCE = H07 / "evidence"
OUT = EVIDENCE / "H07_VERIFICATION.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    inputs = load(H07 / "INPUT_READBACK.json")
    browser = load(EVIDENCE / "ACTUAL_A10R08_B11_BROWSER.json")
    http = load(EVIDENCE / "B11_ACTUAL_HTTP.json")
    har = load(EVIDENCE / "NETWORK_HAR.json")
    confirmed = http["details"]["confirmed"]["body"]
    screenshot_paths = [item["screenshot"] for item in browser["journeys"]] + [browser["daily_history_dom_gate"]["history_screenshot"]]
    screenshots = []
    for rel in screenshot_paths:
        path = ROOT / rel
        data = path.read_bytes(); width, height = struct.unpack(">II", data[16:24])
        screenshots.append({"path": rel, "sha256": sha256(path), "width": width, "height": height})

    patterns = [re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"sk-[A-Za-z0-9_-]{20,}"), re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")]
    hits = []
    for base in (ROOT / "tools" / "web_journey_h07", ROOT / "tests" / "web" / "journey_h07", ROOT / "reports" / "H07", EVIDENCE):
        if not base.exists(): continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".png", ".zip", ".pyc"} or path.name.startswith("RUN_FAILURE") or path.name.startswith("run-failure"): continue
            data = path.read_bytes()
            for pattern in patterns:
                if pattern.search(data): hits.append({"path": path.relative_to(ROOT).as_posix(), "pattern": pattern.pattern.decode()})

    gates = {
        "input_integrity": inputs["status"] == "PASS_INPUT_INTEGRITY_PINNED_R09",
        "a10_r08_hash_bound": inputs["inputs"]["A10_R08"]["sha256"] == "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
        "b11_hash_bound": inputs["inputs"]["B11"]["sha256"] == "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
        "real_b11_http": http["search"]["status"] == 200 and all(item["status"] == 200 for item in http["details"].values()),
        "confirmed_price": confirmed["product"]["display_price_twd"] == 49 and confirmed["product"]["before_coupon_price_twd"] == 99,
        "raw_history": len(confirmed["history"]["before_coupon"]) == 1 and len(confirmed["history"]["confirmed_after_coupon"]) == 1,
        "daily_history_wire": browser["daily_history_wire_gate"]["pass"] is True,
        "daily_history_dom_gap_reproduced": browser["daily_history_dom_gate"]["pass"] is False and browser["product_integration_gate"] == "FAIL_DAILY_HISTORY_NOT_RENDERED",
        "actual_browser_journeys": len(browser["journeys"]) == 10 and all(item["pass"] for item in browser["journeys"]),
        "browser_http_requests": browser["browser_search_request_count"] > 0 and browser["browser_detail_request_count"] > 0,
        "negative_semantics": http["details"]["zero"]["body"]["product"]["display_price_twd"] == 0 and http["details"]["unavailable"]["body"]["product"]["display_price_twd"] is None,
        "http_security": http["missing"]["status"] == 404 and http["hostile_host"]["status"] == 400 and http["hostile_origin"]["status"] == 403,
        "cta_disabled": all(item["disabled_cta_count"] == item["expected_disabled_cta_count"] and item["outbound_anchor_count"] == 0 for item in browser["journeys"]),
        "network_isolation": browser["external_request_count"] == 0 and har["external_request_count"] == 0,
        "screenshots": len(screenshots) == 11 and all(item["width"] >= 390 and item["height"] >= 844 for item in screenshots),
        "no_substitute_website": not list((ROOT / "tools" / "web_journey_h07").glob("*.html")),
        "secret_scan": not hits,
    }
    evidence_status = "PASS_COMPLETE_EVIDENCE_PRODUCT_GAP_REPRODUCED" if all(gates.values()) else "FAIL_EVIDENCE_VERIFICATION"
    result = {
        "task_id": "CDH-H07-A10R08-B11-FULL_BROWSER-001", "authority": "SCOPED_OFFLINE_LOCAL_ONLY_R09_H",
        "gates": gates, "a10_r08_sha256": inputs["inputs"]["A10_R08"]["sha256"], "b11_sha256": inputs["inputs"]["B11"]["sha256"],
        "evidence_collection_gate": browser["evidence_collection_gate"], "product_integration_gate": browser["product_integration_gate"],
        "browser_search_request_count": browser["browser_search_request_count"], "browser_detail_request_count": browser["browser_detail_request_count"],
        "journey_count": len(browser["journeys"]), "external_request_count": browser["external_request_count"],
        "daily_history_wire_gate": browser["daily_history_wire_gate"], "daily_history_dom_gate": browser["daily_history_dom_gate"],
        "screenshots": screenshots, "secret_scan_hits": hits, "status": evidence_status,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": evidence_status, "product_integration_gate": browser["product_integration_gate"], "gates": gates}, ensure_ascii=False))
    raise SystemExit(0 if evidence_status.startswith("PASS") else 1)


if __name__ == "__main__":
    main()
