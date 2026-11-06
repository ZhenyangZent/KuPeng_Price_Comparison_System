from __future__ import annotations

import hashlib
import json
import socket
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H12 = ROOT / "review" / "H12"
PROJECT = H12 / "runtime" / "project"
EVIDENCE = H12 / "evidence"
OUT = EVIDENCE / "FIRST_USE_FAILURE_ANALYSIS.json"


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
    attempt1 = json.loads((EVIDENCE / "ACTUAL_H12_BROWSER_HTTP_ATTEMPT1_UNDOCUMENTED_DEPENDENCY_FAIL.json").read_text(encoding="utf-8"))
    attempt2 = json.loads((EVIDENCE / "ACTUAL_H12_BROWSER_HTTP.json").read_text(encoding="utf-8"))
    negative = json.loads((EVIDENCE / "LAUNCHER_NEGATIVE_TESTS.json").read_text(encoding="utf-8"))
    dependency_gap = json.loads((EVIDENCE / "A16_TRANSITIVE_DEPENDENCY_GAP.json").read_text(encoding="utf-8"))
    line_endings = {}
    for name in ("Start-CDH-MVP.cmd", "Status-CDH-MVP.cmd", "Stop-CDH-MVP.cmd"):
        path = PROJECT / name
        data = path.read_bytes()
        text = data.decode("utf-8")
        line_endings[name] = {
            "sha256": sha256(path),
            "bytes": len(data),
            "crlf_count": text.count("\r\n"),
            "bare_lf_count": sum(1 for index, char in enumerate(text) if char == "\n" and (index == 0 or text[index - 1] != "\r")),
        }
    state = PROJECT / "data" / "local_mvp" / "state"
    history_lines = [json.loads(line) for line in (state / "history.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    gates = {
        "a16_exact_input": json.loads((H12 / "INPUT_READBACK.json").read_text(encoding="utf-8"))["a16"]["sha256"] == "3c6d329cebdda9f8d269f3740952f897b6c95e932d0e04fef4a625defe0fc37e",
        "dependency_gap_reproduced": attempt1["status"] == "FAIL" and "CDH_B_R09_001_REVIEW.zip" in attempt1["error"] and dependency_gap["additional_transitive_release_count"] == 4,
        "start_reached_ready_after_exact_transitive_inputs": attempt2["launcher_receipts"][0]["payload"]["status"] == "READY",
        "root_status_cmd_failed": attempt2["launcher_receipts"][1]["entry"] == "Status-CDH-MVP.cmd" and attempt2["launcher_receipts"][1]["exit_code"] == 9009 and attempt2["launcher_receipts"][1]["payload"]["status"] == "FAILED",
        "root_cmd_files_lf_only": all(item["crlf_count"] == 0 and item["bare_lf_count"] > 0 for item in line_endings.values()),
        "missing_dependency_fail_closed": (negative["missing_dependency"].get("payload") or {}).get("status") == "FAILED" and "PINNED_RELEASE_MISSING" in (negative["missing_dependency"].get("payload") or {}).get("error", ""),
        "occupied_port_fail_closed": (negative["occupied_port"].get("payload") or {}).get("status") == "FAILED" and "PORT_IN_USE" in (negative["occupied_port"].get("payload") or {}).get("error", ""),
        "unknown_process_not_terminated": negative["unknown_process_termination_count"] == 0,
        "server_stopped_after_failure": history_lines[-1]["event"] == "STOP" and port_closed(12334) and not (state / "active.json").exists(),
        "no_private_database_created": not (PROJECT / "data" / "private_user_observations_b15" / "private_user_observations.sqlite3").exists(),
        "chrome_not_started": not attempt1["network"] and not attempt1["captures"] and not attempt2["network"] and not attempt2["captures"],
    }
    result = {
        "task_id": "CDH-H12-LOCAL-MVP-FIRST-USE-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL_A16_FIRST_USE_BLOCKERS",
        "responsible_workline": "A",
        "stronger_model_required": False,
        "product_attempt_count": 2,
        "chrome_process_start_count": 0,
        "formal_database_write_count": 0,
        "isolated_database_write_count": 0,
        "defects": [
            {
                "id": "A16-H12-001",
                "title": "A16 documentation and preflight omit four B16 transitive releases",
                "minimal_repro": "Stage only the four releases named by WINDOWS_LOCAL_MVP_FIRST_USE.md and CDH-Mvp.Common.ps1, then run Start-CDH-MVP.cmd; startup fails first at CDH_B_R09_001_REVIEW.zip.",
                "missing_exact_releases": dependency_gap["additional_transitive_releases"],
            },
            {
                "id": "A16-H12-002",
                "title": "LF-only root CMD wrappers break Status-CDH-MVP.cmd and emit command errors",
                "minimal_repro": "Run Start-CDH-MVP.cmd and Status-CDH-MVP.cmd from cmd.exe; Start emits command fragments and Status exits 9009 without machine-readable status JSON.",
                "line_endings": line_endings,
            },
        ],
        "negative_safety_note": "Payloads prove fail-closed PINNED_RELEASE_MISSING and PORT_IN_USE. The recorded negative harness marked FAIL only because it expected exit 2, while Start-CDH-MVP.cmd uses -NoExit and the fed interactive exit returns 0.",
        "gates": gates,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    required_true = all(gates.values())
    raise SystemExit(0 if required_true else 1)


if __name__ == "__main__":
    main()
