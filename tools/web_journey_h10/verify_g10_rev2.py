from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports" / "G10" / "H10_LOOPBACK_DIAGNOSIS.md"
APPROVED = ROOT / "reports" / "G10" / "h10_loopback_approved.json"
RESTRICTED = ROOT / "reports" / "G10" / "h10_loopback_restricted.json"
OUT = ROOT / "review" / "H10_REV2" / "G10_INPUT_READBACK.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    report_text = REPORT.read_text(encoding="utf-8")
    approved = json.loads(APPROVED.read_text(encoding="utf-8"))
    restricted = json.loads(RESTRICTED.read_text(encoding="utf-8"))
    gates = {
        "classification_environment_limitation": "ENVIRONMENT_LIMITATION_CONFIRMED" in report_text,
        "no_a14_revision_required": "A14 must not be revised" in report_text,
        "approved_exact_release_gate": approved.get("exact_release_gate") is True,
        "approved_python_http_200": approved.get("python_http", {}).get("status") == 200,
        "approved_node_http_200": approved.get("node_fetch", {}).get("return_code") == 0 and approved.get("node_fetch", {}).get("result", {}).get("status") == 200,
        "approved_chrome_http_visible": approved.get("chrome_dump_dom", {}).get("return_code") == 0 and approved.get("chrome_dump_dom", {}).get("health_visible") is True,
        "approved_shutdown_clean": approved.get("shutdown", {}).get("status") == 202 and approved.get("child_exit_code") == 0,
        "approved_no_database": approved.get("database_created") is False,
        "restricted_permission_error": "WinError 10013" in json.dumps(restricted, ensure_ascii=False),
        "a14_identity_in_diagnosis": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160" in report_text,
        "b15_exact": approved.get("release_hashes", {}).get("CDH_B_R11_002_REVIEW.zip") == "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
    }
    payload = {
        "task_id": "CDH-H10-PRIVATE-HISTORY-REOPEN-E2E-001",
        "revision": "REV2",
        "g10_task_id": "CDH-G10-H10-LOOPBACK-DIAGNOSTIC-001",
        "g10_status_only_zip": "NOT_AVAILABLE_AT_START",
        "classification": "ENVIRONMENT_LIMITATION_CONFIRMED",
        "a14_revision_required": False,
        "inputs": {
            "diagnosis": {"path": REPORT.relative_to(ROOT).as_posix(), "sha256": sha256(REPORT)},
            "approved": {"path": APPROVED.relative_to(ROOT).as_posix(), "sha256": sha256(APPROVED)},
            "restricted": {"path": RESTRICTED.relative_to(ROOT).as_posix(), "sha256": sha256(RESTRICTED)},
        },
        "gates": gates,
        "status": "PASS" if all(gates.values()) else "FAIL",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0 if payload["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
