from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H11 = ROOT / "review" / "H11"
ATTEMPT = H11 / "attempt2"
OUT = H11 / "FINAL_VERIFICATION.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def port_closed(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def main() -> None:
    failed = json.loads((H11 / "evidence" / "ACTUAL_H11_BROWSER_HTTP.json").read_text(encoding="utf-8"))
    actual = json.loads((ATTEMPT / "evidence" / "ACTUAL_H11_BROWSER_HTTP.json").read_text(encoding="utf-8"))
    receipt = json.loads((ATTEMPT / "evidence" / "BROWSER_PROCESS_RECEIPT.json").read_text(encoding="utf-8"))
    sqlite = json.loads((ATTEMPT / "evidence" / "SQLITE_READONLY_EVIDENCE.json").read_text(encoding="utf-8"))
    daily = json.loads((ATTEMPT / "evidence" / "DAILY_DOM_RECONCILIATION.json").read_text(encoding="utf-8"))
    inputs = json.loads((H11 / "INPUT_READBACK.json").read_text(encoding="utf-8"))
    staged = json.loads((ATTEMPT / "STAGED_PROJECT.json").read_text(encoding="utf-8"))
    gates = {
        "exact_a15_release": sha256(ROOT / "review" / "releases" / "CDH_A_R12_001_REVIEW.zip") == "5cc44dedd910ff9b2055cfc2772ad0c3d6db627ffc818794f81fd3d9b5552d4b",
        "exact_b16_rev2_release": sha256(ROOT / "review" / "releases" / "CDH_B_R12_002_REVIEW.zip") == "6904b7ab2ffd6daac0325be75a119cd906c67c7c479a4607760ce24739444ed6",
        "input_archives_integrity": inputs["status"] == "PASS" and all(item["crc"] == "PASS" and all(item[key] == 0 for key in ("mismatch", "missing", "undeclared", "duplicates", "case_collisions", "unsafe_paths", "symlinks")) for item in inputs["inputs"].values()),
        "api_schema_unchanged": inputs["api_compatibility_claim"]["route_or_request_schema_change_count"] == 0,
        "attempt1_fail_preserved": failed["status"] == "FAIL" and "PROD-B16-EXAMPLE detail" in failed["error"],
        "attempt2_processes_exit_zero": receipt["exit_code"] == actual["browser_test_exit_code"] == actual["chrome_process_exit_code"] == 0,
        "product_gates_15_of_15": len(actual["gates"]) == 15 and all(actual["gates"].values()),
        "daily_dom_gates_6_of_6": len(daily["gates"]) == 6 and all(daily["gates"].values()),
        "sqlite_four_rows_immutable": sqlite["row_counts"]["observations"] == 4 and sqlite["read_only_hash_unchanged"] and sqlite["evidence_database_copy_matches"],
        "reported_never_confirmed": all(row["confirmed_after_coupon_price_twd"] is None and row["platform_verified"] == 0 for row in sqlite["observations"]),
        "duplicate_no_new_rows": actual["rows_after_json"] == actual["rows_after_replay"] == 4,
        "read_only_after_restart": actual["browser_post_after_restart_count"] == 0 and actual["database_sha256_before_read"] == actual["database_sha256_after_read"],
        "no_external_requests": actual["external_request_count"] == 0,
        "capture_evidence_complete": len(actual["captures"]) == 12 and all((ROOT / item["screenshot"]).is_file() and (ROOT / item["dom"]).is_file() for item in actual["captures"]),
        "test_cache_excluded": staged["vitest_temp_count"] == 0,
        "loopback_port_closed": port_closed(12332),
    }
    result = {
        "task_id": "H11",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "actual_browser_attempt_count": 2,
        "failed_attempt_count": 1,
        "passed_attempt_count": 1,
        "final_product_gate_count": len(actual["gates"]),
        "final_product_gate_pass_count": sum(bool(value) for value in actual["gates"].values()),
        "browser_test_exit_code": actual["browser_test_exit_code"],
        "chrome_process_exit_code": actual["chrome_process_exit_code"],
        "database_sha256": sqlite["sha256_after"],
        "gates": gates,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
