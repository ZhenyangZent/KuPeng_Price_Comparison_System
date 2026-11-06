from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H08 = ROOT / "review" / "H08"
EVIDENCE = H08 / "evidence"
OUT = EVIDENCE / "H08_VERIFICATION.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    inputs = load(H08 / "INPUT_READBACK.json")
    browser = load(EVIDENCE / "ACTUAL_A11_B11_BROWSER.json")
    http = load(EVIDENCE / "B11_ACTUAL_HTTP.json")
    har = load(EVIDENCE / "NETWORK_HAR.json")
    launcher = load(EVIDENCE / "A11_LAUNCHER_JOURNEY.json")
    screenshot_paths = [item["screenshot"] for item in browser["journeys"]] + [browser["daily_history_dom_gate"]["history_screenshot"]]
    screenshots = []
    for rel in screenshot_paths:
        path = ROOT / rel
        data = path.read_bytes(); width, height = struct.unpack(">II", data[16:24])
        screenshots.append({"path": rel, "sha256": sha256(path), "width": width, "height": height})
    patterns = [re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"sk-[A-Za-z0-9_-]{20,}"), re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")]
    hits = []
    for base in (ROOT / "tools" / "web_journey_h08", ROOT / "tests" / "web" / "journey_h08", ROOT / "reports" / "H08", EVIDENCE):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".png", ".zip", ".pyc"} or path.name.startswith("RUN_FAILURE") or path.name.startswith("run-failure"):
                continue
            data = path.read_bytes()
            for pattern in patterns:
                if pattern.search(data):
                    hits.append({"path": path.relative_to(ROOT).as_posix(), "pattern": pattern.pattern.decode()})
    confirmed = http["details"]["confirmed"]["body"]
    gates = {
        "input_integrity": inputs["status"] == "PASS_INPUT_INTEGRITY_PINNED_R10",
        "a11_hash_bound": inputs["inputs"]["A11_R09"]["sha256"] == "40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd",
        "b11_hash_bound": inputs["inputs"]["B11_R07"]["sha256"] == "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
        "real_b11_http": http["search"]["status"] == 200 and all(item["status"] == 200 for item in http["details"].values()),
        "confirmed_price": confirmed["product"]["display_price_twd"] == 49 and confirmed["product"]["before_coupon_price_twd"] == 99,
        "raw_history_dom": browser["raw_history_dom_gate"]["pass"] is True,
        "daily_history_wire": browser["daily_history_wire_gate"]["pass"] is True,
        "daily_history_dom": browser["daily_history_dom_gate"]["pass"] is True,
        "actual_browser_journeys": len(browser["journeys"]) == 11 and all(item["pass"] for item in browser["journeys"]),
        "browser_http_requests": browser["browser_search_request_count"] > 0 and browser["browser_detail_request_count"] > 0,
        "negative_semantics": http["details"]["zero"]["body"]["product"]["display_price_twd"] == 0 and http["details"]["unavailable"]["body"]["product"]["display_price_twd"] is None,
        "http_security": http["missing"]["status"] == 404 and http["hostile_host"]["status"] == 400 and http["hostile_origin"]["status"] == 403,
        "cta_disabled": all(item["disabled_cta_count"] == item["expected_disabled_cta_count"] and item["outbound_anchor_count"] == 0 for item in browser["journeys"]),
        "network_isolation": browser["external_request_count"] == 0 and har["external_request_count"] == 0,
        "launcher_lifecycle": launcher["all_pass"] is True,
        "launcher_wrong_token": launcher["checks"]["wrong_token_rejected"] and launcher["checks"]["wrong_token_no_effect"],
        "launcher_unknown_process_guard": launcher["checks"]["unknown_process_not_terminated"],
        "screenshots": len(screenshots) == 12 and all(item["width"] >= 390 and item["height"] >= 844 for item in screenshots),
        "no_substitute_website": not list((ROOT / "tools" / "web_journey_h08").glob("*.html")),
        "secret_scan": not hits,
    }
    status = "PASS_COMPLETE_A11_B11_DAILY_DOM_AND_LAUNCHER" if all(gates.values()) else "FAIL_EVIDENCE_VERIFICATION"
    result = {
        "task_id": "CDH-H08-A11-B11-DAILY-DOM-AND-LAUNCHER-JOURNEY-001", "authority": "SCOPED_OFFLINE_LOCAL_ONLY_R10_H",
        "gates": gates, "a11_r09_sha256": inputs["inputs"]["A11_R09"]["sha256"], "b11_r07_sha256": inputs["inputs"]["B11_R07"]["sha256"],
        "evidence_collection_gate": browser["evidence_collection_gate"], "product_integration_gate": browser["product_integration_gate"],
        "browser_search_request_count": browser["browser_search_request_count"], "browser_detail_request_count": browser["browser_detail_request_count"],
        "journey_count": len(browser["journeys"]), "external_request_count": browser["external_request_count"],
        "raw_history_dom_gate": browser["raw_history_dom_gate"], "daily_history_wire_gate": browser["daily_history_wire_gate"],
        "daily_history_dom_gate": browser["daily_history_dom_gate"], "launcher_checks": launcher["checks"],
        "screenshots": screenshots, "secret_scan_hits": hits, "status": status,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "product_integration_gate": browser["product_integration_gate"], "gates": gates}, ensure_ascii=False))
    raise SystemExit(0 if status.startswith("PASS") else 1)


if __name__ == "__main__":
    main()
