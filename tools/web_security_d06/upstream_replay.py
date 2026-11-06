from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

from .targets import safe_member_name
from .temp_scope import scoped_temp


def run_backend_suite(backend_zip: str | Path, evidence_path: str | Path) -> dict[str, object]:
    source = Path(backend_zip)
    evidence = Path(evidence_path)
    with scoped_temp("upstream") as temporary:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if (
                archive.testzip() is not None
                or any(not safe_member_name(item.filename) for item in infos)
                or any(stat.S_ISLNK(item.external_attr >> 16) for item in infos)
            ):
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
        root = roots[0]
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.web.price_query_v3.test_adapter", "-v"],
            cwd=root,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=120,
        )
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            f"COMMAND: {sys.executable} -m unittest tests.web.price_query_v3.test_adapter -v\n"
            f"TARGET: {source.name}\nEXIT_CODE: {result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}",
            encoding="utf-8",
        )
        if result.returncode:
            raise RuntimeError(f"UPSTREAM_SUITE_FAILURE:{result.returncode}")
        combined = result.stdout + result.stderr
        marker = "Ran "
        count = None
        if marker in combined:
            tail = combined.split(marker, 1)[1].split(" ", 1)[0]
            count = int(tail) if tail.isdigit() else None
        return {"exit_code": result.returncode, "tests_run": count, "evidence": str(evidence)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the packaged B09 upstream adapter tests offline")
    parser.add_argument("--backend-zip", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = run_backend_suite(args.backend_zip, args.evidence)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
