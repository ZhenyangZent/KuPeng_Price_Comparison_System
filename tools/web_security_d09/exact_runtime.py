from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tools.web_security_d09.portable import extract_portable
from tools.web_security_d09.temp_scope import scoped_temp


def _single_root(path: Path) -> Path:
    roots = [item for item in path.iterdir() if item.is_dir()]
    if len(roots) != 1:
        raise ValueError("EXACT_ARCHIVE_ROOT_INVALID")
    return roots[0]


def run_exact_pair(b11_zip: str | Path, f06_zip: str | Path) -> dict[str, object]:
    with scoped_temp("d09-pair") as temp:
        b11_out = extract_portable(b11_zip, temp / "b11")
        f06_out = extract_portable(f06_zip, temp / "f06")
        command = [
            sys.executable, "-m", "tools.web_security_d09.exact_child",
            "--b11-root", str(_single_root(b11_out)), "--f06-root", str(_single_root(f06_out)),
            "--fixture", str(temp / "fixture"),
        ]
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(command, cwd=Path.cwd(), env=environment, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=180, check=False)
        if result.returncode:
            raise RuntimeError(f"EXACT_PAIR_RUNTIME_FAILURE:{result.returncode}:{result.stderr}:{result.stdout}")
        return json.loads(result.stdout)
