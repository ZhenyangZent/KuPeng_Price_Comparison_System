from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

from tools.web_security_d06.targets import safe_member_name

from .temp_scope import scoped_temp


def replay(zip_path: str | Path, *, role: str, evidence_path: str | Path) -> dict[str, object]:
    source = Path(zip_path)
    evidence = Path(evidence_path)
    with scoped_temp(f"upstream-{role.casefold()}") as temporary:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if archive.testzip() is not None or any(not safe_member_name(item.filename) for item in infos) or any(stat.S_ISLNK(item.external_attr >> 16) for item in infos):
                raise ValueError("UPSTREAM_ARCHIVE_SAFETY_FAILURE")
            for item in infos:
                if item.is_dir():
                    continue
                target = temporary / PurePosixPath(item.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item.filename))
        roots = [item for item in temporary.iterdir() if item.is_dir()]
        if len(roots) != 1:
            raise ValueError("UPSTREAM_ARCHIVE_ROOT_INVALID")
        if role == "B10":
            command = [
                sys.executable, "-m", "unittest",
                "tests.web.price_coupon_v4.test_coupon_v4",
                "tests.web.price_query_v3.test_adapter", "-v",
            ]
        elif role == "F05":
            command = [sys.executable, "-m", "unittest", "tests.affiliate_coupon_gate_v5.test_affiliate_coupon_gate_v5", "-v"]
        else:
            raise ValueError("UPSTREAM_ROLE_UNSUPPORTED")
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            command, cwd=roots[0], env=environment, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=False, timeout=180,
        )
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            "COMMAND: " + " ".join(command) + f"\nTARGET: {source.name}\nEXIT_CODE: {result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}",
            encoding="utf-8",
        )
        if result.returncode:
            raise RuntimeError(f"UPSTREAM_SUITE_FAILURE:{role}:{result.returncode}")
        combined = result.stdout + result.stderr
        count = None
        if "Ran " in combined:
            text = combined.split("Ran ", 1)[1].split(" ", 1)[0]
            count = int(text) if text.isdigit() else None
        return {"role": role, "exit_code": result.returncode, "tests_run": count, "evidence": str(evidence)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay exact B10 or F05 upstream tests offline")
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--role", choices=("B10", "F05"), required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.zip, role=args.role, evidence_path=args.evidence), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
