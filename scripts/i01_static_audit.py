from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from urllib.parse import urlsplit


SOURCE_ROOT = Path("src/cdh_integration")
FORBIDDEN_IMPORTS = {
    "http.client",
    "requests",
    "selenium",
    "socket",
    "subprocess",
    "urllib.request",
    "webbrowser",
    "winreg",
}


def imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source_files = sorted(SOURCE_ROOT.glob("*.py"))
    syntax_failures: list[str] = []
    forbidden_imports: dict[str, list[str]] = {}
    b01_coupling: list[str] = []
    for path in source_files:
        try:
            imports = imports_for(path)
        except SyntaxError as exc:
            syntax_failures.append(f"{path.as_posix()}:{exc.lineno}:{exc.msg}")
            continue
        blocked = sorted(
            name
            for name in imports
            if any(name == item or name.startswith(item + ".") for item in FORBIDDEN_IMPORTS)
        )
        if blocked:
            forbidden_imports[path.as_posix()] = blocked
        if any(name == "experiments.B01" or name.startswith("experiments.B01.") for name in imports):
            b01_coupling.append(path.as_posix())
    cases = json.loads(Path("fixtures/i01/synthetic_integration_cases.json").read_text(encoding="utf-8"))
    bad_fixture_urls: list[str] = []
    for case in cases:
        url = case["observation"]["product_url"]
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "synthetic.invalid":
            bad_fixture_urls.append(url)
    text_paths = [*source_files, Path("fixtures/i01/synthetic_integration_cases.json")]
    forbidden_literals = {
        path.as_posix(): literal
        for path in text_paths
        for literal in ("coupang.com", "HKEY_CURRENT_USER", "NativeMessagingHosts", "cookies.sqlite")
        if literal.casefold() in path.read_text(encoding="utf-8").casefold()
    }
    gates = {
        "PYTHON_SYNTAX": {"pass": not syntax_failures, "detail": syntax_failures},
        "NO_NETWORK_OR_REGISTRY_IMPORTS": {"pass": not forbidden_imports, "detail": forbidden_imports},
        "NO_FROZEN_B01_IMPORT_COUPLING": {"pass": not b01_coupling, "detail": b01_coupling},
        "FIXTURES_SYNTHETIC_INVALID_ONLY": {"pass": not bad_fixture_urls, "detail": bad_fixture_urls},
        "NO_REAL_COMMERCE_OR_PROFILE_LITERALS": {"pass": not forbidden_literals, "detail": forbidden_literals},
        "FIXTURE_CASE_COUNT": {"pass": len(cases) >= 5, "detail": len(cases)},
    }
    result = {
        "task_id": "CDH-I01-SYNTHETIC-INTEGRATION-001",
        "source_file_count": len(source_files),
        "gates": gates,
        "passed": sum(bool(item["pass"]) for item in gates.values()),
        "failed": sum(not bool(item["pass"]) for item in gates.values()),
    }
    result["status"] = "PASS" if result["failed"] == 0 else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

