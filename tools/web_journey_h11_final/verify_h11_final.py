from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "review" / "H11_FINAL"
OUT = FINAL / "FINAL_VERIFICATION.json"


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
    actual = json.loads((FINAL / "evidence" / "ACTUAL_H11_BROWSER_HTTP.json").read_text(encoding="utf-8"))
    receipt = json.loads((FINAL / "evidence" / "BROWSER_PROCESS_RECEIPT.json").read_text(encoding="utf-8"))
    sqlite = json.loads((FINAL / "evidence" / "SQLITE_READONLY_EVIDENCE.json").read_text(encoding="utf-8"))
    daily = json.loads((FINAL / "evidence" / "DAILY_DOM_RECONCILIATION.json").read_text(encoding="utf-8"))
    inputs = json.loads((FINAL / "INPUT_READBACK.json").read_text(encoding="utf-8"))
    staged = json.loads((FINAL / "STAGED_PROJECT.json").read_text(encoding="utf-8"))
    clean_fields = ("mismatch", "missing", "undeclared", "duplicates", "case_collisions", "unsafe_paths", "symlinks")
    gates = {
        "exact_a15_rev2_release": sha256(ROOT / "review" / "releases" / "CDH_A_R12_002_REVIEW.zip") == "be0becbaa384e1a633c5893b266dbbb03c449ca405ef1f0c07bb8dd53456634b",
        "exact_b16_rev3_release": sha256(ROOT / "review" / "releases" / "CDH_B_R12_003_REVIEW.zip") == "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
        "exact_d13_rev3_release": sha256(ROOT / "review" / "releases" / "CDH_D_R12_003_REVIEW.zip") == "8aef750caa17c894159d13705f9962e4f6e856ef3ced1658ddb951523b241e54",
        "input_archives_integrity": inputs["status"] == "PASS" and all(item["crc"] == "PASS" and all(item[key] == 0 for key in clean_fields) for item in inputs["inputs"].values()),
        "official_launcher_bound_without_h_loader": staged["official_binding_gate"] and staged["h_test_loader_file_count"] == 0 and not actual["h_test_loader_used"],
        "health_exact_b16_rev3": actual["health"] == {"b16_r12_sha256": "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7", "b16_revision": "REV3", "b16_api_schema": "CDH-B16-PRIVATE-BATCH-API-1"},
        "browser_processes_exit_zero": receipt["exit_code"] == actual["browser_test_exit_code"] == actual["chrome_process_exit_code"] == 0,
        "product_gates_15_of_15": len(actual["gates"]) == 15 and all(actual["gates"].values()),
        "daily_dom_gates_6_of_6": len(daily["gates"]) == 6 and all(daily["gates"].values()),
        "sqlite_four_rows_immutable": sqlite["row_counts"]["observations"] == 4 and sqlite["read_only_hash_unchanged"] and sqlite["evidence_database_copy_matches"],
        "reported_never_confirmed": all(row["confirmed_after_coupon_price_twd"] is None and row["platform_verified"] == 0 for row in sqlite["observations"]),
        "preview_and_duplicate_no_extra_write": actual["rows_after_json"] == actual["rows_after_replay"] == 4 and actual["csv_preview"]["database_write_zero"] and actual["json_preview"]["database_write_zero"],
        "restart_read_only": actual["first_instance_id"] != actual["second_instance_id"] and actual["browser_post_after_restart_count"] == 0 and actual["database_sha256_before_read"] == actual["database_sha256_after_read"],
        "no_external_requests": actual["external_request_count"] == 0,
        "capture_evidence_complete": len(actual["captures"]) == 12 and all((ROOT / item["screenshot"]).is_file() and (ROOT / item["dom"]).is_file() for item in actual["captures"]),
        "test_cache_excluded_from_stage": staged["vitest_temp_count"] == 0,
        "loopback_port_closed": port_closed(12332),
    }
    result = {
        "task_id": "H11",
        "revision": "FINAL_OFFICIAL_LAUNCHER",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "official_launcher_browser_run_count": 1,
        "browser_test_exit_code": actual["browser_test_exit_code"],
        "chrome_process_exit_code": actual["chrome_process_exit_code"],
        "product_gate_count": len(actual["gates"]),
        "product_gate_pass_count": sum(bool(value) for value in actual["gates"].values()),
        "database_sha256": sqlite["sha256_after"],
        "gates": gates,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
