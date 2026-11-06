from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Iterable, Mapping, Sequence


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EXECUTED_DEPENDENCY = "NOT_EXECUTED_DEPENDENCY"
    NOT_EXECUTED_POLICY = "NOT_EXECUTED_POLICY"
    ERROR = "ERROR"


class ExitCode(IntEnum):
    PASS = 0
    TEST_FAILURE = 2
    DEPENDENCY_MISSING = 3
    SECURITY_FAILURE = 4
    VERSION_CONFLICT = 5
    RUNNER_ERROR = 6
    USAGE_ERROR = 64


@dataclass(frozen=True)
class Dependency:
    kind: str
    value: str
    description: str


@dataclass(frozen=True)
class SuiteSpec:
    name: str
    description: str
    command: tuple[str, ...]
    cwd: Path
    dependencies: tuple[Dependency, ...] = ()
    timeout_seconds: int = 300
    environment: Mapping[str, str] = field(default_factory=dict)
    execution_allowed: bool = True
    policy_block_reason: str | None = None


def _dependency_available(dependency: Dependency, project_root: Path) -> tuple[bool, str]:
    if dependency.kind == "executable":
        found = shutil.which(dependency.value)
        return (found is not None, found or f"executable not found: {dependency.value}")
    if dependency.kind == "path":
        path = (project_root / dependency.value).resolve()
        return (path.exists(), str(path))
    if dependency.kind == "python_module":
        found = importlib.util.find_spec(dependency.value) is not None
        return (found, dependency.value)
    raise ValueError(f"unsupported dependency kind: {dependency.kind}")


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_." else "_" for character in value)


def _run_suite(spec: SuiteSpec, project_root: Path, output_dir: Path) -> dict:
    missing: list[dict] = []
    dependency_evidence: list[dict] = []
    for dependency in spec.dependencies:
        available, evidence = _dependency_available(dependency, project_root)
        item = {
            "kind": dependency.kind,
            "value": dependency.value,
            "description": dependency.description,
            "available": available,
            "evidence": evidence,
        }
        dependency_evidence.append(item)
        if not available:
            missing.append(item)

    result = {
        "name": spec.name,
        "description": spec.description,
        "command": list(spec.command),
        "cwd": str(spec.cwd),
        "dependencies": dependency_evidence,
        "status": None,
        "actual_return_code": None,
        "duration_seconds": 0.0,
        "stdout_log": None,
        "stderr_log": None,
        "reason": None,
    }
    if missing:
        result["status"] = Status.NOT_EXECUTED_DEPENDENCY.value
        result["reason"] = "; ".join(item["description"] for item in missing)
        return result
    if not spec.execution_allowed:
        result["status"] = Status.NOT_EXECUTED_POLICY.value
        result["reason"] = spec.policy_block_reason or "execution is blocked by policy"
        return result

    log_dir = output_dir / "logs"
    temp_dir = output_dir / "tmp" / _safe_name(spec.name)
    log_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{_safe_name(spec.name)}.stdout.log"
    stderr_path = log_dir / f"{_safe_name(spec.name)}.stderr.log"
    environment = os.environ.copy()
    environment.update(spec.environment)
    environment["TEMP"] = str(temp_dir)
    environment["TMP"] = str(temp_dir)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(spec.command),
            cwd=spec.cwd,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=spec.timeout_seconds,
            shell=False,
            check=False,
        )
        result["duration_seconds"] = round(time.monotonic() - started, 6)
        result["actual_return_code"] = completed.returncode
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        result["stdout_log"] = str(stdout_path)
        result["stderr_log"] = str(stderr_path)
        result["status"] = Status.PASS.value if completed.returncode == 0 else Status.FAIL.value
        if completed.returncode != 0:
            result["reason"] = f"process exited with {completed.returncode}"
    except subprocess.TimeoutExpired as error:
        result["duration_seconds"] = round(time.monotonic() - started, 6)
        stdout_path.write_text(error.stdout or "", encoding="utf-8")
        stderr_path.write_text(error.stderr or "", encoding="utf-8")
        result["stdout_log"] = str(stdout_path)
        result["stderr_log"] = str(stderr_path)
        result["status"] = Status.ERROR.value
        result["reason"] = f"timeout after {spec.timeout_seconds} seconds"
    except OSError as error:
        result["duration_seconds"] = round(time.monotonic() - started, 6)
        result["status"] = Status.ERROR.value
        result["reason"] = f"process launch failed: {error}"
    return result


def _write_junit(path: Path, suites: Sequence[dict], exit_code: int) -> None:
    failures = sum(item["status"] == Status.FAIL.value for item in suites)
    errors = sum(item["status"] == Status.ERROR.value for item in suites)
    skipped = sum(item["status"] in {Status.NOT_EXECUTED_DEPENDENCY.value, Status.NOT_EXECUTED_POLICY.value} for item in suites)
    root = ET.Element(
        "testsuite",
        {
            "name": "cdh-check-project",
            "tests": str(len(suites)),
            "failures": str(failures),
            "errors": str(errors),
            "skipped": str(skipped),
        },
    )
    properties = ET.SubElement(root, "properties")
    ET.SubElement(properties, "property", {"name": "runner_exit_code", "value": str(exit_code)})
    for item in suites:
        case = ET.SubElement(
            root,
            "testcase",
            {
                "classname": "tools.ci_offline.check_project",
                "name": item["name"],
                "time": str(item["duration_seconds"]),
            },
        )
        status = item["status"]
        if status == Status.FAIL.value:
            failure = ET.SubElement(case, "failure", {"message": item["reason"] or "test failure"})
            failure.text = item["reason"] or "test failure"
        elif status == Status.ERROR.value:
            error = ET.SubElement(case, "error", {"message": item["reason"] or "runner error"})
            error.text = item["reason"] or "runner error"
        elif status in {Status.NOT_EXECUTED_DEPENDENCY.value, Status.NOT_EXECUTED_POLICY.value}:
            skipped_node = ET.SubElement(case, "skipped", {"message": item["reason"] or status})
            skipped_node.text = status
        system_out = ET.SubElement(case, "system-out")
        system_out.text = json.dumps(
            {"status": status, "actual_return_code": item["actual_return_code"], "command": item["command"]},
            ensure_ascii=False,
        )
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def determine_exit_code(
    suites: Sequence[dict],
    *,
    security_failed: bool = False,
    version_conflict: bool = False,
) -> ExitCode:
    if security_failed:
        return ExitCode.SECURITY_FAILURE
    if version_conflict:
        return ExitCode.VERSION_CONFLICT
    if any(item["status"] == Status.ERROR.value for item in suites):
        return ExitCode.RUNNER_ERROR
    if any(item["status"] in {Status.NOT_EXECUTED_DEPENDENCY.value, Status.NOT_EXECUTED_POLICY.value} for item in suites):
        return ExitCode.DEPENDENCY_MISSING
    if any(item["status"] == Status.FAIL.value for item in suites):
        return ExitCode.TEST_FAILURE
    return ExitCode.PASS


def run_checks(
    *,
    project_root: Path,
    output_dir: Path,
    suite_specs: Iterable[SuiteSpec],
    runtimes: dict,
    archive_audits: Sequence[dict] = (),
    source_scans: Sequence[dict] = (),
    workline_check: dict | None = None,
) -> tuple[dict, ExitCode]:
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    suite_results = [_run_suite(spec, project_root, output_dir) for spec in suite_specs]
    security_failed = any(not audit.get("passed", False) for audit in archive_audits) or any(
        not scan.get("passed", False) for scan in source_scans
    )
    version_conflict = bool(workline_check and not workline_check.get("passed", False))
    exit_code = determine_exit_code(
        suite_results,
        security_failed=security_failed,
        version_conflict=version_conflict,
    )
    report = {
        "schema": "CDH-OFFLINE-CI-RUN-1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "output_dir": str(output_dir),
        "runtimes": runtimes,
        "suites": suite_results,
        "archive_audits": list(archive_audits),
        "source_scans": list(source_scans),
        "workline_check": workline_check,
        "summary": {
            "suite_count": len(suite_results),
            "pass_count": sum(item["status"] == Status.PASS.value for item in suite_results),
            "fail_count": sum(item["status"] == Status.FAIL.value for item in suite_results),
            "not_executed_dependency_count": sum(
                item["status"] == Status.NOT_EXECUTED_DEPENDENCY.value for item in suite_results
            ),
            "not_executed_policy_count": sum(item["status"] == Status.NOT_EXECUTED_POLICY.value for item in suite_results),
            "error_count": sum(item["status"] == Status.ERROR.value for item in suite_results),
            "security_failed": security_failed,
            "version_conflict": version_conflict,
            "return_code": int(exit_code),
        },
    }
    json_path = output_dir / "check_project.json"
    junit_path = output_dir / "check_project.junit.xml"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    junit_results = list(suite_results)
    for index, audit in enumerate(archive_audits, start=1):
        junit_results.append(
            {
                "name": f"archive_audit_{index}",
                "description": audit.get("path", "review ZIP audit"),
                "command": [],
                "status": Status.PASS.value if audit.get("passed", False) else Status.FAIL.value,
                "actual_return_code": 0 if audit.get("passed", False) else int(ExitCode.SECURITY_FAILURE),
                "duration_seconds": 0.0,
                "reason": None if audit.get("passed", False) else "archive identity, manifest, CRC, path, or secret gate failed",
            }
        )
    for index, scan in enumerate(source_scans, start=1):
        junit_results.append(
            {
                "name": f"source_scan_{index}",
                "description": "allowlisted source secret scan",
                "command": [],
                "status": Status.PASS.value if scan.get("passed", False) else Status.FAIL.value,
                "actual_return_code": 0 if scan.get("passed", False) else int(ExitCode.SECURITY_FAILURE),
                "duration_seconds": 0.0,
                "reason": None if scan.get("passed", False) else "source scan rejected a path or detected a sensitive fixture",
            }
        )
    if workline_check is not None:
        junit_results.append(
            {
                "name": "workline_version_gate",
                "description": workline_check.get("path", "workline registry"),
                "command": [],
                "status": Status.PASS.value if workline_check.get("passed", False) else Status.FAIL.value,
                "actual_return_code": 0 if workline_check.get("passed", False) else int(ExitCode.VERSION_CONFLICT),
                "duration_seconds": 0.0,
                "reason": None if workline_check.get("passed", False) else "workline version/source identity conflict",
            }
        )
    _write_junit(junit_path, junit_results, int(exit_code))
    return report, exit_code
