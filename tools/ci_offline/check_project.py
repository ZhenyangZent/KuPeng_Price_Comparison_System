from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .archive_audit import audit_review_zip
from .runner import Dependency, ExitCode, SuiteSpec, run_checks
from .sensitive_scan import scan_allowed_sources
from .workline import check_workline_registry


TASK_ID = "CDH-G02-OFFLINE-CI-RUNNER-001"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def output_path_allowed(project_root: Path, output_dir: Path) -> bool:
    output_dir = output_dir.resolve()
    allowed = ((project_root / "reports" / "G02").resolve(), (project_root / "review" / "G02").resolve())
    return any(output_dir == root or _is_relative_to(output_dir, root) for root in allowed)


def _version(command: list[str]) -> dict:
    executable = shutil.which(command[0])
    if executable is None:
        return {"available": False, "executable": None, "version": None}
    completed = subprocess.run(
        [executable, *command[1:]],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    return {
        "available": completed.returncode == 0,
        "executable": executable,
        "version": completed.stdout.strip(),
        "return_code": completed.returncode,
    }


def detect_runtimes() -> dict:
    return {
        "python": {"available": True, "executable": sys.executable, "version": sys.version.split()[0]},
        "node": _version(["node", "--version"]),
        "npm": _version(["npm", "--version"]),
    }


def suite_catalog(project_root: Path) -> dict[str, SuiteSpec]:
    frontend = project_root / "apps" / "price-web" / "frontend"
    return {
        "g02_self": SuiteSpec(
            name="g02_self",
            description="G02 standard-library unit and adversarial tests",
            command=(
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests/ci_offline",
                "-p",
                "test_*.py",
                "-v",
            ),
            cwd=project_root,
            dependencies=(Dependency("path", "tests/ci_offline", "G02 test directory"),),
            timeout_seconds=180,
        ),
        "frontend_vitest": SuiteSpec(
            name="frontend_vitest",
            description="Existing A06/A05 frontend Vitest entrypoint using preinstalled local dependencies",
            command=(
                shutil.which("node") or "node",
                "node_modules/vitest/vitest.mjs",
                "run",
            ),
            cwd=frontend,
            dependencies=(
                Dependency("executable", "node", "Node.js runtime"),
                Dependency("path", "apps/price-web/frontend/node_modules/vitest/vitest.mjs", "local Vitest module"),
                Dependency("path", "apps/price-web/frontend/package.json", "frontend package manifest"),
            ),
            timeout_seconds=300,
        ),
        "desktop_a04": SuiteSpec(
            name="desktop_a04",
            description="Desktop GUI regression suite; local execution remains blocked outside G02 write scope",
            command=(sys.executable, "-m", "unittest", "tests.a04.test_a04_gui", "-v"),
            cwd=project_root,
            dependencies=(
                Dependency("python_module", "PySide6", "PySide6 Python module"),
                Dependency("path", "tests/a04/test_a04_gui.py", "A04 GUI test entrypoint"),
            ),
            execution_allowed=False,
            policy_block_reason="A04 tests write outside the G02 whitelist and must run in their owning lane or isolated CI workspace",
        ),
    }


def _parse_archive(value: str) -> tuple[Path, str | None]:
    if "::" not in value:
        return Path(value), None
    path, expected = value.rsplit("::", 1)
    if len(expected) != 64 or any(character not in "0123456789abcdefABCDEF" for character in expected):
        raise argparse.ArgumentTypeError("expected ZIP SHA-256 must be 64 hex characters")
    return Path(path), expected.lower()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run bounded offline CDH checks without installing dependencies.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("reports/G02/latest"))
    parser.add_argument("--suite", action="append", choices=("g02_self", "frontend_vitest", "desktop_a04"))
    parser.add_argument("--review-zip", action="append", type=_parse_archive, default=[])
    parser.add_argument("--scan-source", action="append", type=Path, default=[])
    parser.add_argument("--workline-registry", type=Path)
    parser.add_argument("--list-suites", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    output_dir = args.output_dir if args.output_dir.is_absolute() else project_root / args.output_dir
    if not output_path_allowed(project_root, output_dir):
        print(
            json.dumps(
                {
                    "error": "OUTPUT_PATH_OUTSIDE_G02_WHITELIST",
                    "output_dir": str(output_dir.resolve()),
                    "allowed": [str(project_root / "reports" / "G02"), str(project_root / "review" / "G02")],
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return int(ExitCode.USAGE_ERROR)
    catalog = suite_catalog(project_root)
    if args.list_suites:
        value = {
            name: {
                "description": spec.description,
                "command": list(spec.command),
                "cwd": str(spec.cwd),
                "dependencies": [dependency.__dict__ for dependency in spec.dependencies],
                "execution_allowed": spec.execution_allowed,
            }
            for name, spec in catalog.items()
        }
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return int(ExitCode.PASS)
    selected = args.suite or ["g02_self", "frontend_vitest"]
    archive_audits = []
    for path, expected in args.review_zip:
        resolved = path if path.is_absolute() else project_root / path
        archive_audits.append(audit_review_zip(resolved, expected))
    source_scans = []
    if args.scan_source:
        source_scans.append(scan_allowed_sources(project_root, args.scan_source))
    workline_check = None
    if args.workline_registry:
        registry = args.workline_registry if args.workline_registry.is_absolute() else project_root / args.workline_registry
        workline_check = check_workline_registry(registry)
    report, exit_code = run_checks(
        project_root=project_root,
        output_dir=output_dir,
        suite_specs=[catalog[name] for name in selected],
        runtimes=detect_runtimes(),
        archive_audits=archive_audits,
        source_scans=source_scans,
        workline_check=workline_check,
    )
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
