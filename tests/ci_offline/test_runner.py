from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.ci_offline.runner import Dependency, ExitCode, Status, SuiteSpec, determine_exit_code, run_checks

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = PROJECT_ROOT / "reports" / "G02" / "test_tmp"


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT, ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        (self.root / "reports" / "G02").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def spec(self, name: str, code: int) -> SuiteSpec:
        return SuiteSpec(
            name=name,
            description=f"fixture {name}",
            command=(sys.executable, "-c", f"print('fixture:{name}'); raise SystemExit({code})"),
            cwd=self.root,
        )

    def test_success_writes_json_junit_and_actual_return_code(self) -> None:
        output = self.root / "reports" / "G02" / "pass"
        report, code = run_checks(
            project_root=self.root,
            output_dir=output,
            suite_specs=[self.spec("pass", 0)],
            runtimes={"python": {"available": True}},
        )
        self.assertEqual(code, ExitCode.PASS)
        self.assertEqual(report["suites"][0]["actual_return_code"], 0)
        self.assertEqual(report["suites"][0]["status"], Status.PASS.value)
        persisted = json.loads((output / "check_project.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["summary"]["return_code"], 0)
        xml = ET.parse(output / "check_project.junit.xml").getroot()
        self.assertEqual(xml.attrib["failures"], "0")
        self.assertIn('"actual_return_code": 0', xml.find("testcase/system-out").text or "")

    def test_program_failure_is_not_pass_and_returns_two(self) -> None:
        output = self.root / "reports" / "G02" / "failure"
        report, code = run_checks(
            project_root=self.root,
            output_dir=output,
            suite_specs=[self.spec("failure", 17)],
            runtimes={},
        )
        self.assertEqual(code, ExitCode.TEST_FAILURE)
        self.assertEqual(report["suites"][0]["status"], Status.FAIL.value)
        self.assertEqual(report["suites"][0]["actual_return_code"], 17)

    def test_missing_dependency_is_explicit_and_returns_three(self) -> None:
        spec = SuiteSpec(
            name="missing",
            description="missing dependency fixture",
            command=(sys.executable, "-c", "raise SystemExit(0)"),
            cwd=self.root,
            dependencies=(Dependency("executable", "cdh-command-that-does-not-exist", "missing fake executable"),),
        )
        report, code = run_checks(
            project_root=self.root,
            output_dir=self.root / "reports" / "G02" / "missing",
            suite_specs=[spec],
            runtimes={},
        )
        self.assertEqual(code, ExitCode.DEPENDENCY_MISSING)
        self.assertEqual(report["suites"][0]["status"], Status.NOT_EXECUTED_DEPENDENCY.value)
        self.assertIsNone(report["suites"][0]["actual_return_code"])

    def test_policy_skip_is_not_pass(self) -> None:
        spec = SuiteSpec(
            name="blocked",
            description="policy fixture",
            command=(sys.executable, "-c", "raise SystemExit(0)"),
            cwd=self.root,
            execution_allowed=False,
            policy_block_reason="owner lane required",
        )
        report, code = run_checks(
            project_root=self.root,
            output_dir=self.root / "reports" / "G02" / "blocked",
            suite_specs=[spec],
            runtimes={},
        )
        self.assertEqual(code, ExitCode.DEPENDENCY_MISSING)
        self.assertEqual(report["suites"][0]["status"], Status.NOT_EXECUTED_POLICY.value)

    def test_exit_codes_for_security_conflict_and_runner_error_are_distinct(self) -> None:
        passed = [{"status": Status.PASS.value}]
        errored = [{"status": Status.ERROR.value}]
        self.assertEqual(determine_exit_code(passed, security_failed=True), ExitCode.SECURITY_FAILURE)
        self.assertEqual(determine_exit_code(passed, version_conflict=True), ExitCode.VERSION_CONFLICT)
        self.assertEqual(determine_exit_code(errored), ExitCode.RUNNER_ERROR)

    def test_security_gate_is_a_failing_junit_case(self) -> None:
        output = self.root / "reports" / "G02" / "security"
        _, code = run_checks(
            project_root=self.root,
            output_dir=output,
            suite_specs=[self.spec("pass", 0)],
            runtimes={},
            archive_audits=[{"path": "malicious.zip", "passed": False}],
        )
        self.assertEqual(code, ExitCode.SECURITY_FAILURE)
        xml = ET.parse(output / "check_project.junit.xml").getroot()
        self.assertEqual(xml.attrib["tests"], "2")
        self.assertEqual(xml.attrib["failures"], "1")


if __name__ == "__main__":
    unittest.main()
