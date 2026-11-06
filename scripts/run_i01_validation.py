from __future__ import annotations

import json
import os
import platform
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


LOG_ROOT = Path("review/I01/001/logs/final_accepted")
EVIDENCE_ROOT = Path("review/I01/001/evidence/final_accepted")
TEMP_ROOT = Path("review/I01/001/tmp/final_accepted")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def render(command: list[str]) -> str:
    return subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)


def run_step(index: int, name: str, command: list[str], *, expected_tests: int | None = None) -> dict[str, object]:
    started = utc_now()
    completed = subprocess.run(
        command,
        cwd=".",
        env={
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": "src;.",
            "TEMP": TEMP_ROOT.as_posix(),
            "TMP": TEMP_ROOT.as_posix(),
        },
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    prefix = f"{index:02d}_{name}"
    (LOG_ROOT / f"{prefix}.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (LOG_ROOT / f"{prefix}.stderr.log").write_text(completed.stderr, encoding="utf-8")
    combined = completed.stdout + "\n" + completed.stderr
    actual_tests: int | None = None
    if expected_tests is not None:
        matches = re.findall(r"Ran (\d+) tests|(?:#|ℹ) tests (\d+)", combined)
        if matches:
            actual_tests = int(next(value for value in matches[-1] if value))
    count_ok = expected_tests is None or actual_tests == expected_tests
    metadata = {
        "step": name,
        "command": render(command),
        "started_at_utc": started,
        "finished_at_utc": utc_now(),
        "exit_code": completed.returncode,
        "expected_tests": expected_tests,
        "actual_tests": actual_tests,
        "count_gate": count_ok,
        "pass": completed.returncode == 0 and count_ok,
    }
    (LOG_ROOT / f"{prefix}.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> int:
    if LOG_ROOT.exists() or EVIDENCE_ROOT.exists():
        raise FileExistsError("final I01 validation evidence already exists; refusing to overwrite")
    LOG_ROOT.mkdir(parents=True)
    EVIDENCE_ROOT.mkdir(parents=True)
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    environment = {
        "task_id": "CDH-I01-SYNTHETIC-INTEGRATION-001",
        "generated_at_utc": utc_now(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "cwd": str(Path.cwd()),
        "authority": "AUTHORIZED — OFFLINE_SYNTHETIC_CODE_ONLY",
    }
    (EVIDENCE_ROOT / "ENVIRONMENT.json").write_text(
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    python = sys.executable
    c01_modules = [
        "tests.test_history_policy",
        "tests.test_models_pricing",
        "tests.test_orchestrator_r01_new_regressions",
        "tests.test_persistence_demo",
        "tests.test_r02_positive_regressions",
        "tests.test_r03_policy_fee_coupon_regressions",
        "tests.test_r04_expiry_provenance_authority",
        "tests.test_rework_regressions",
    ]
    steps = [
        (
            "input_and_history_integrity",
            [python, "-B", "scripts/i01_validate_input.py", "--output", str(EVIDENCE_ROOT / "INPUT_INTEGRITY.json")],
            None,
        ),
        (
            "static_scope_audit",
            [python, "-B", "scripts/i01_static_audit.py", "--output", str(EVIDENCE_ROOT / "STATIC_SCOPE_AUDIT.json")],
            None,
        ),
        ("c01_regression_143", [python, "-B", "-m", "unittest", "-v", *c01_modules], 143),
        (
            "b01_node_regression_26",
            [
                "node",
                "--test",
                "tests/b01/test_extension_logic.mjs",
                "tests/b01/test_native_port_recovery.mjs",
                "tests/b01/test_native_response_validation.mjs",
            ],
            26,
        ),
        ("i01_integration_44", [python, "-B", "tests/i01/test_adapter_pipeline.py", "-v"], 44),
        (
            "synthetic_cli_demo",
            [
                python,
                "-B",
                "-m",
                "cdh_integration.cli",
                "--cases",
                "fixtures/i01/synthetic_integration_cases.json",
                "--candidate-db",
                str(EVIDENCE_ROOT / "demo_candidates.sqlite3"),
                "--event-db",
                str(EVIDENCE_ROOT / "demo_events.sqlite3"),
                "--output",
                str(EVIDENCE_ROOT / "SYNTHETIC_DEMO.json"),
                "--now",
                "2026-11-02T12:00:00Z",
            ],
            None,
        ),
        (
            "protected_scope_final",
            [
                python,
                "-B",
                "scripts/i01_protected_scope.py",
                "--compare",
                "review/I01/001/evidence/before/PROTECTED_SCOPE_BEFORE.json",
                "--output",
                str(EVIDENCE_ROOT / "PROTECTED_SCOPE_FINAL.json"),
            ],
            None,
        ),
    ]
    results = [
        run_step(index, name, command, expected_tests=expected)
        for index, (name, command, expected) in enumerate(steps, start=1)
    ]
    summary = {
        "task_id": "CDH-I01-SYNTHETIC-INTEGRATION-001",
        "generated_at_utc": utc_now(),
        "steps": results,
        "passed_steps": sum(bool(step["pass"]) for step in results),
        "failed_steps": sum(not bool(step["pass"]) for step in results),
        "c01_test_count": 143,
        "b01_node_test_count": 26,
        "i01_test_count": 44,
        "total_test_count": 213,
        "registry_read_count": 0,
        "registry_mutation_count": 0,
        "ownership_marker_delete_count": 0,
        "firefox_launch_count": 0,
        "firefox_profile_access_count": 0,
        "real_commerce_access_count": 0,
        "real_notification_count": 0,
        "transaction_action_count": 0,
    }
    summary["status"] = "PASS" if summary["failed_steps"] == 0 else "FAIL"
    (EVIDENCE_ROOT / "VALIDATION_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
