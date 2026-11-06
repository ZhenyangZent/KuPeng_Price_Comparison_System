from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H05 = ROOT / "review" / "H05"
EVIDENCE = H05 / "evidence"
OUT = EVIDENCE / "H05_VERIFICATION.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    inputs = load(H05 / "INPUT_READBACK.json")
    http = load(EVIDENCE / "B10_ACTUAL_HTTP.json")
    parser = load(EVIDENCE / "A09_B10_PARSER_RESULT.json")
    browser = load(EVIDENCE / "EXACT_A09_B10_BROWSER.json")
    har = load(EVIDENCE / "NETWORK_HAR.json")

    screenshots = []
    for rel in (browser["a09_ui"]["screenshot"], browser["b10_real_http"]["screenshot"]):
        path = ROOT / rel
        data = path.read_bytes()
        width, height = struct.unpack(">II", data[16:24])
        screenshots.append({"path": rel, "sha256": sha256(path), "width": width, "height": height})

    scan_roots = [ROOT / "tools" / "web_journey_h05", ROOT / "tests" / "web" / "journey_h05", ROOT / "reports" / "H05", EVIDENCE]
    patterns = [
        re.compile(rb"AKIA[0-9A-Z]{16}"),
        re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\."),
    ]
    secret_hits = []
    for base in scan_roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".png", ".zip", ".pyc"}:
                continue
            data = path.read_bytes()
            for pattern in patterns:
                if pattern.search(data):
                    secret_hits.append({"path": path.relative_to(ROOT).as_posix(), "pattern": pattern.pattern.decode()})

    expected_codes = ["V4_VERSION_MISMATCH", "INVALID_V4_PAYLOAD", "V4_VERSION_MISMATCH", "INVALID_V4_PAYLOAD"]
    detail = http["detail"]["body"]
    gates = {
        "input_integrity": inputs["status"] == "PASS",
        "real_b10_http": http["search"]["status"] == 200 and http["detail"]["status"] == 200,
        "confirmed_coupon_price": detail["product"]["display_price_twd"] == 49 and detail["product"]["before_coupon_price_twd"] == 99,
        "dual_history": len(detail["history"]["before_coupon"]) == 1 and len(detail["history"]["confirmed_after_coupon"]) == 1,
        "negative_http": http["missing"]["status"] == 404 and http["not_modified"]["status"] == 304,
        "exact_wire_blocker_reproduced": [x["code"] for x in parser["attempts"]] == expected_codes,
        "a09_no_b10_ui_fetch": browser["a09_ui"]["b10_api_requests_during_ui"] == 0,
        "cors_blocker_reproduced": browser["cors_fetch_from_a09"]["ok"] is False and browser["cors_fetch_from_a09"]["name"] == "TypeError",
        "cta_disabled": browser["a09_ui"]["disabled_cta_count"] == 1 and browser["a09_ui"]["outbound_cta_count"] == 0,
        "network_isolation": browser["network"]["external_request_count"] == 0 and har["external_request_count"] == 0,
        "screenshots": all(x["width"] >= 800 and x["height"] >= 600 for x in screenshots),
        "a10_b11_not_misreported": inputs["inputs"]["A10"]["state"] == "NOT_AVAILABLE" and inputs["inputs"]["B11"]["state"] == "NOT_AVAILABLE" and browser["exact_a10_b11_gate"] == "NOT_RUN_INPUT_UNAVAILABLE",
        "secret_scan": not secret_hits,
    }
    status = "PASS_EVIDENCE_A09_B10_FAIL_A10_B11_NOT_RUN" if all(gates.values()) else "FAIL_EVIDENCE_VERIFICATION"
    result = {
        "task_id": "CDH-H05-REAL-A10-B11-BROWSER-JOURNEY-001",
        "authority": "AUTHORIZED_OFFLINE_R07_H_ONLY",
        "gates": gates,
        "exact_a09_b10_integration": "FAIL_INCOMPATIBLE_NO_UI_FETCH",
        "exact_a10_b11_integration": "NOT_RUN_INPUT_UNAVAILABLE",
        "real_b10": {"search_status": 200, "detail_status": 200, "display_price_twd": 49, "before_coupon_price_twd": 99},
        "parser_error_codes": expected_codes,
        "a09_ui_b10_api_request_count": browser["a09_ui"]["b10_api_requests_during_ui"],
        "external_request_count": browser["network"]["external_request_count"],
        "screenshots": screenshots,
        "secret_scan_hits": secret_hits,
        "status": status,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "gates": gates}, ensure_ascii=False))
    raise SystemExit(0 if status.startswith("PASS") else 1)


if __name__ == "__main__":
    main()
