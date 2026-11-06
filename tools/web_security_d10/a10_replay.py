from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay(frontend: Path, dependency_frontend: Path, evidence: Path) -> dict[str, object]:
    package_identity = {
        name: {
            "exact_sha256": digest(frontend / name),
            "dependency_sha256": digest(dependency_frontend / name),
            "same_bytes": (frontend / name).read_bytes() == (dependency_frontend / name).read_bytes(),
        }
        for name in ("package.json", "package-lock.json")
    }
    if not all(item["same_bytes"] for item in package_identity.values()):
        raise ValueError("A10_DEPENDENCY_IDENTITY_MISMATCH")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    node = shutil.which("node.exe") or shutil.which("node")
    if not npm or not node:
        raise RuntimeError("A10_NODE_OR_NPM_UNAVAILABLE")
    commands = [
        ("UNIT", [npm, "test"]),
        ("ROLE", [npm, "run", "test:role"]),
        ("A08", [node, "scripts/run-a08-role-tests.mjs"]),
        ("A09", [node, "scripts/run-a09-role-tests.mjs"]),
        ("A10", [node, "scripts/run-a10-role-tests.mjs"]),
        ("BUILD", [npm, "run", "build"]),
    ]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    results = []
    evidence.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, command in commands:
        process = subprocess.run(command, cwd=frontend, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False, timeout=300, shell=False)
        combined = process.stdout + process.stderr
        match = re.search(r"Tests\s+(\d+) passed", combined)
        count = int(match.group(1)) if match else 0
        if name != "BUILD":
            total += count
        (evidence / f"A10_{name}.txt").write_text("COMMAND: " + " ".join(command) + f"\nEXIT_CODE: {process.returncode}\n\nSTDOUT\n{process.stdout}\nSTDERR\n{process.stderr}", encoding="utf-8")
        results.append({"name": name, "command": command, "exit_code": process.returncode, "tests_run": count})
        if process.returncode:
            raise RuntimeError(f"A10_SOURCE_REPLAY_FAILURE:{name}:{process.returncode}")
    result = {
        "schema": "CDH-D10-A10-SOURCE-REPLAY-1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "package_identity": package_identity,
        "results": results,
        "automated_tests_run": total,
        "automated_tests_passed": total,
        "build_pass": True,
        "browser_test": "NOT_RUN_ENV_BLOCKED",
        "npm_offline_install": "NOT_RUN_DEPENDENCY_UNAVAILABLE:yallist@3.1.1",
    }
    (evidence / "A10_SOURCE_REPLAY.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--dependency-frontend", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.frontend.resolve(), args.dependency_frontend.resolve(), args.evidence.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
