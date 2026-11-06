from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REV = ROOT / "review" / "H10_REV3"
EVIDENCE = REV / "evidence"
OUT = REV / "VERIFICATION_RESULT.json"


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
    actual = json.loads((EVIDENCE / "ACTUAL_H10_REV3_BROWSER_HTTP.json").read_text(encoding="utf-8"))
    receipt = json.loads((EVIDENCE / "BROWSER_PROCESS_RECEIPT.json").read_text(encoding="utf-8"))
    sqlite = json.loads((EVIDENCE / "SQLITE_READONLY_EVIDENCE.json").read_text(encoding="utf-8"))
    inputs = json.loads((REV / "INPUT_READBACK.json").read_text(encoding="utf-8"))
    staged = json.loads((REV / "STAGED_PROJECT.json").read_text(encoding="utf-8"))
    expected_old = {
        "review/releases/CDH_H_R11_002_REVIEW.zip": "bdfe4ba6671400a6479213c53b8d1f7d4f1a20c75a8b393c170795baa2d36257",
        "review/releases/CDH_H_R11_004_STATUS_ONLY.zip": "c02ca574c31c53719198d2ec21c5701b1c32c57747e3e6257ce7623d5da1f7ab",
    }
    old_hashes = {name: sha256(ROOT / name) for name in expected_old}
    gates = {
        "exact_upstream_integrity": inputs["status"] == "PASS" and all(
            item["crc"] == "PASS" and all(item[field] == 0 for field in ("mismatch", "missing", "undeclared", "duplicates", "case_collisions", "unsafe_paths", "symlinks"))
            for item in inputs["inputs"].values()
        ),
        "browser_process_exit_zero": receipt["exit_code"] == 0 and actual["browser_test_exit_code"] == 0,
        "chrome_process_exit_zero": actual["chrome_process_exit_code"] == 0,
        "product_gates_23_of_23": len(actual["gates"]) == 23 and all(actual["gates"].values()),
        "two_rows_and_read_only": actual["rows_before_read"] == actual["rows_after_read"] == 2 and actual["browser_post_after_restart_count"] == 0 and actual["database_unchanged_by_read"],
        "daily_tracks_exact": actual["gates"]["before_daily"] and actual["gates"]["reported_daily"] and actual["gates"]["confirmed_empty"],
        "isolated_sqlite_exact": sqlite["row_counts"]["observations"] == 2 and sqlite["read_only_hash_unchanged"] and sqlite["evidence_database_copy_matches"],
        "capture_evidence_complete": len(actual["captures"]) == 9 and all((ROOT / item["screenshot"]).is_file() and (ROOT / item["dom"]).is_file() for item in actual["captures"]),
        "no_external_or_affiliate_action": actual["external_request_count"] == 0 and all(item["cta_disabled"] and item["external_links"] == 0 for item in actual["search_results"]),
        "staged_cache_excluded": staged["vitest_cache_count"] == 0,
        "rev1_rev2_preserved": old_hashes == expected_old,
        "loopback_port_closed_after_run": port_closed(12330),
    }
    result = {
        "task_id": "CDH-H10-PRIVATE-HISTORY-REOPEN-E2E-001",
        "revision": "REV3",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "product_journey_run_count": 1,
        "product_gate_count": len(actual["gates"]),
        "product_gate_pass_count": sum(bool(value) for value in actual["gates"].values()),
        "browser_test_exit_code": actual["browser_test_exit_code"],
        "chrome_process_exit_code": actual["chrome_process_exit_code"],
        "old_delivery_hashes": old_hashes,
        "database_sha256": sqlite["sha256_after"],
        "gates": gates,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
