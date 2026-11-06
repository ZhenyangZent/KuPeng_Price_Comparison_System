from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H06 = ROOT / "review" / "H06"
EVIDENCE = H06 / "evidence"
OUT = EVIDENCE / "H06_VERIFICATION.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    inputs = load(H06 / "INPUT_READBACK.json")
    browser = load(EVIDENCE / "ACTUAL_A10_B11_BROWSER.json")
    http = load(EVIDENCE / "B11_ACTUAL_HTTP.json")
    har = load(EVIDENCE / "NETWORK_HAR.json")
    confirmed = http["details"]["confirmed"]["body"]
    screenshots = []
    for journey in browser["journeys"]:
        path = ROOT / journey["screenshot"]
        data = path.read_bytes()
        width, height = struct.unpack(">II", data[16:24])
        screenshots.append({"path": journey["screenshot"], "sha256": sha256(path), "width": width, "height": height})

    patterns = [re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"sk-[A-Za-z0-9_-]{20,}"), re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")]
    hits = []
    for base in (ROOT / "tools" / "web_journey_h06", ROOT / "tests" / "web" / "journey_h06", ROOT / "reports" / "H06", EVIDENCE):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".png", ".zip", ".pyc"} or path.name.startswith("RUN_FAILURE") or path.name.startswith("run-failure"):
                continue
            data = path.read_bytes()
            for pattern in patterns:
                if pattern.search(data):
                    hits.append({"path": path.relative_to(ROOT).as_posix(), "pattern": pattern.pattern.decode()})

    gates = {
        "input_integrity": inputs["status"] == "PASS_INPUT_INTEGRITY_A10_PRESENT_BUT_UNACKNOWLEDGED",
        "a10_hash_observed": inputs["inputs"]["A10"]["sha256"] == "eb4b449972f1bb6bccd9457e8ee88a2b3c69f2a2001b17fc5adfceb23c6a7e08",
        "b11_hash_bound": inputs["inputs"]["B11"]["sha256"] == "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
        "real_b11_http": http["search"]["status"] == 200 and all(item["status"] == 200 for item in http["details"].values()),
        "confirmed_price": confirmed["product"]["display_price_twd"] == 49 and confirmed["product"]["before_coupon_price_twd"] == 99,
        "dual_history": len(confirmed["history"]["before_coupon"]) == 1 and len(confirmed["history"]["confirmed_after_coupon"]) == 1,
        "zero_null_distinct": http["details"]["zero"]["body"]["product"]["display_price_twd"] == 0 and http["details"]["unavailable"]["body"]["product"]["display_price_twd"] is None,
        "http_negative_security": http["missing"]["status"] == 404 and http["hostile_host"]["status"] == 400 and http["hostile_origin"]["status"] == 403,
        "actual_browser_journeys": len(browser["journeys"]) == 7 and all(item["pass"] for item in browser["journeys"]),
        "browser_http_requests": browser["browser_search_request_count"] > 0 and browser["browser_detail_request_count"] > 0,
        "timeout_recovery": any(item["name"] == "a10-b11-timeout-mobile" and item["pass"] for item in browser["journeys"]) and any(item["name"] == "a10-b11-timeout-recovery-mobile" and item["pass"] for item in browser["journeys"]),
        "cta_disabled": all(item["disabled_cta_count"] == item["expected_disabled_cta_count"] and item["outbound_anchor_count"] == 0 for item in browser["journeys"]),
        "network_isolation": browser["external_request_count"] == 0 and har["external_request_count"] == 0,
        "screenshots": len(screenshots) == 7 and all(item["width"] >= 390 and item["height"] >= 844 for item in screenshots),
        "no_substitute_website": not list((ROOT / "tools" / "web_journey_h06").glob("*.html")),
        "a10_ack_fail_closed": inputs["inputs"]["A10"]["central_ack_state"] == "NOT_ACKNOWLEDGED_IN_R08_AUTHORITY" and browser["final_integration_gate"] == "PROVISIONAL_PASS_AWAITING_CENTRAL_A10_SHA_ACK",
        "secret_scan": not hits,
    }
    status = "PASS_PROVISIONAL_EVIDENCE_AWAITING_A10_ACK" if all(gates.values()) else "FAIL_EVIDENCE_VERIFICATION"
    result = {
        "task_id": "CDH-H06-A10-B11-ACTUAL-BROWSER-001",
        "authority": "AUTHORIZED_OFFLINE_R08_H_ONLY",
        "gates": gates,
        "a10_sha256_observed": inputs["inputs"]["A10"]["sha256"],
        "a10_central_ack_state": inputs["inputs"]["A10"]["central_ack_state"],
        "b11_sha256": inputs["inputs"]["B11"]["sha256"],
        "actual_browser_evidence": browser["evidence_result"],
        "final_integration_gate": browser["final_integration_gate"],
        "browser_search_request_count": browser["browser_search_request_count"],
        "browser_detail_request_count": browser["browser_detail_request_count"],
        "journey_count": len(browser["journeys"]),
        "external_request_count": browser["external_request_count"],
        "screenshots": screenshots,
        "secret_scan_hits": hits,
        "status": status,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "gates": gates}, ensure_ascii=False))
    raise SystemExit(0 if status.startswith("PASS") else 1)


if __name__ == "__main__":
    main()
