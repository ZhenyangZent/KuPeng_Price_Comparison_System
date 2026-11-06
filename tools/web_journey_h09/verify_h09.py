from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H09 = ROOT / "review" / "H09"
EVIDENCE = H09 / "evidence"
OUT = EVIDENCE / "H09_VERIFICATION.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    inputs = load(H09 / "INPUT_READBACK.json")
    staged = load(H09 / "STAGED_PROJECT.json")
    raw = load(EVIDENCE / "ACTUAL_H09_BROWSER_HTTP.json")
    database = load(EVIDENCE / "SQLITE_READONLY_EVIDENCE.json")
    persistent = raw["negative_results"]["persistent_detail"]
    negative = raw["negative_results"]
    screenshots = []
    for capture in raw["captures"]:
        path = ROOT / capture["screenshot"]
        data = path.read_bytes(); width, height = struct.unpack(">II", data[16:24])
        screenshots.append({"path": capture["screenshot"], "sha256": sha256(path), "width": width, "height": height})
    patterns = [re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"sk-[A-Za-z0-9_-]{20,}"), re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")]
    hits = []
    for base in (ROOT / "tools" / "web_journey_h09", ROOT / "tests" / "web" / "journey_h09", ROOT / "reports" / "H09", EVIDENCE):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".png", ".sqlite3", ".pyc", ".zip"}:
                continue
            data = path.read_bytes()
            for pattern in patterns:
                if pattern.search(data):
                    hits.append({"path": path.relative_to(ROOT).as_posix(), "pattern": pattern.pattern.decode()})
    controls = [item["result"]["status"] for item in raw["controls"]]
    main_text = raw["commit2"]["readbackText"]
    restart_text = raw["restart_replay"]["readbackText"]
    gates = {
        "exact_input_integrity": inputs["status"] == "PASS_EXACT_INPUTS_AVAILABLE" and inputs["inputs"]["A13_REV3"]["sha256"] == "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274" and inputs["inputs"]["B15_REV2"]["sha256"] == "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
        "exact_staged_project": staged["source_a13_release_sha256"] == "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274" and staged["release_copies"]["CDH_B_R11_002_REVIEW.zip"] == "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
        "windows_launcher_lifecycle": controls == ["READY", "READY", "STOPPED", "READY", "READY", "STOPPED"],
        "preview_no_database_write": raw["preview1"]["writeCount"] == "寫入次數 0" and raw["preview2"]["writeCount"] == "寫入次數 0",
        "two_explicit_commits": raw["commit1"]["saveText"].startswith("已保存至隔離本機觀測庫") and raw["commit2"]["saveText"].startswith("已保存至隔離本機觀測庫"),
        "two_date_raw_history": persistent["before"] == [1000, 950] and "2 筆 raw · 2 日" in main_text,
        "two_date_daily_history": persistent["daily"] == [{"representative_price_twd": 1000, "sample_count": 1, "taipei_date": "2026-11-03"}, {"representative_price_twd": 950, "sample_count": 1, "taipei_date": "2026-11-04"}],
        "reported_coupon_not_promoted": persistent["confirmed"] == [] and persistent["reported"] == [900] and "已確認券後歷史\n0 筆 raw · 0 日" in main_text and "使用者自報券後歷史\n1 筆 raw · 1 日" in main_text,
        "unknown_totals_preserved": raw["preview1"]["totalText"] == "UNKNOWN" and raw["preview2"]["totalText"] == "UNKNOWN" and persistent["required_total_twd"] is None,
        "private_source_label": raw["preview1"]["sourceText"] == "USER_ENTERED · PRIVATE_LOCAL · NOT_PLATFORM_VERIFIED" and negative["persistent_search"]["classification"] == "PRIVATE_LOCAL_USER_ENTERED" and persistent["source_state"] == "PRIVATE_LOCAL_ONLY",
        "restart_persistence": raw["database_sha256_before_restart"] == raw["database_sha256_after_idempotent_replay"] and raw["restart_replay"]["saveText"].startswith("相同觀測已存在，未重複新增") and "2 筆 raw · 2 日" in restart_text,
        "csrf_rejected": negative["missing_csrf"]["status"] == 403 and negative["missing_csrf"]["code"] == "CSRF_TOKEN_INVALID",
        "duplicate_json_rejected": negative["duplicate_json"]["status"] == 400 and negative["duplicate_json"]["code"] == "JSON_DUPLICATE_KEY",
        "source_rejected": negative["rejected_source"]["status"] == 400 and negative["rejected_source"]["code"] == "SOURCE_CLASS_NOT_ALLOWED",
        "identity_conflict_rejected": negative["submission_conflict"]["confirm_status"] == 409 and negative["submission_conflict"]["code"] == "SUBMISSION_ID_CONTENT_CONFLICT",
        "cta_disabled": persistent["cta_enabled"] is False and persistent["click_url"] is None and raw["commit2"]["ctaDisabled"] is True and raw["restart_replay"]["ctaDisabled"] is True,
        "isolated_sqlite": database["read_only_hash_unchanged"] is True and database["evidence_database_copy_matches"] is True and database["row_counts"]["observations"] == 3 and database["h09_main_product_matches"]["observations"] == 2,
        "backup_evidence": database["backup_count"] == 2,
        "baseline_immutable": raw["baseline_before"] == raw["baseline_after"],
        "formal_database_untouched": raw["formal_database_write_count"] == 0,
        "screenshots": len(screenshots) == 7 and all(item["width"] >= 1400 and item["height"] >= 1100 for item in screenshots) and all(item["width"] == 1440 and item["height"] == 1100 for item in raw["captures"]),
        "visible_dom_layout": all(not item["horizontal_overflow"] and not item["external_anchors"] for item in raw["captures"]),
        "network_isolation": raw["external_request_count"] == 0,
        "console_exceptions": not [item for item in raw["console_events"] if item["type"] == "exception"],
        "secret_scan": not hits,
    }
    all_pass = all(gates.values())
    result = {
        "task_id": "CDH-H09-A13REV3-B15REV2-WINDOWS-E2E-001",
        "authority": "R11_H09_EXACT_A13_REV3_B15_REV2_LOCAL_ONLY",
        "status": "PASS_COMPLETE_WINDOWS_PRIVATE_OBSERVATION_E2E" if all_pass else "FAIL_EVIDENCE_VERIFICATION",
        "raw_harness_status": raw["status"],
        "harness_assertion_reconciliation": {
            "status": "PASS_ASSERTION_SCOPE_CORRECTED_OFFLINE" if all_pass else "FAIL",
            "detail": "Original four false booleans used page-global history selectors and one undefined Detail field; exact B15 API, scoped visible readback text, restart DB hash and SQLite evidence are authoritative. Product journey was not rerun.",
            "product_journey_run_count": 1,
        },
        "gates": gates, "screenshots": screenshots, "secret_scan_hits": hits,
        "external_request_count": raw["external_request_count"],
        "network_request_count": len(raw["network"]),
        "database_sha256": database["sha256_after"],
        "database_observation_count": database["row_counts"]["observations"],
        "main_product_observation_count": database["h09_main_product_matches"]["observations"],
        "backup_count": database["backup_count"],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "gates": gates}, ensure_ascii=False))
    raise SystemExit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
