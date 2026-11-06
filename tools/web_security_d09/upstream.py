from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.web_security_d09.portable import extract_portable
from tools.web_security_d09.temp_scope import scoped_temp


COMMANDS = {
    "B11": [
        "tests.web.price_coupon_v4.test_coupon_v4",
        "tests.web.price_coupon_v4.test_b11_wire",
        "tests.web.price_query_v3.test_adapter",
    ],
    "F06": ["tests.affiliate_coupon_gate_v6.test_affiliate_coupon_gate_v6"],
}


def replay(path: str | Path, role: str, evidence: str | Path) -> dict[str, object]:
    with scoped_temp("upstream-" + role.casefold()) as temp:
        extracted = extract_portable(path, temp / "input")
        roots = [item for item in extracted.iterdir() if item.is_dir()]
        if len(roots) != 1:
            raise ValueError("UPSTREAM_ARCHIVE_ROOT_INVALID")
        command = [sys.executable, "-m", "unittest", *COMMANDS[role], "-v"]
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(command, cwd=roots[0], env=environment, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=300, check=False)
        evidence = Path(evidence)
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text("COMMAND: " + " ".join(command) + f"\nROLE: {role}\nEXIT_CODE: {result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}", encoding="utf-8")
        combined = result.stdout + result.stderr
        tests = None
        if "Ran " in combined:
            value = combined.split("Ran ", 1)[1].split(" ", 1)[0]
            tests = int(value) if value.isdigit() else None
        if result.returncode:
            raise RuntimeError(f"UPSTREAM_REPLAY_FAILURE:{role}:{result.returncode}")
        return {"role": role, "exit_code": result.returncode, "tests_run": tests, "evidence": str(evidence)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--role", choices=tuple(COMMANDS), required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.zip, args.role, args.evidence), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
