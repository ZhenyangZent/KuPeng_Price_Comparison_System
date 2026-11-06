from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tools.web_security_d09.portable import extract_portable
from tools.web_security_d10.targets import FILES
from tools.web_security_d10.temp_scope import scoped_temp


def _root(path: Path) -> Path:
    roots = [item for item in path.iterdir() if item.is_dir()]
    if len(roots) != 1:
        raise ValueError("D10_ARCHIVE_ROOT_INVALID")
    return roots[0]


def run_exact(releases: str | Path) -> dict[str, object]:
    releases = Path(releases)
    with scoped_temp("exact") as temp:
        roots = {}
        for role, filename in FILES.items():
            roots[role] = _root(extract_portable(releases / filename, temp / role.casefold()))
        command = [
            sys.executable, "-m", "tools.web_security_d10.runtime_child",
            "--a10", str(roots["A10"]), "--b11", str(roots["B11"]),
            "--b12", str(roots["B12"]), "--c09", str(roots["C09"]),
            "--f07", str(roots["F07"]), "--temp", str(temp / "inputs"),
        ]
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process = subprocess.run(command, cwd=Path.cwd(), env=environment, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False, timeout=240)
        if process.returncode:
            raise RuntimeError(f"D10_RUNTIME_FAILURE:{process.returncode}:{process.stdout}:{process.stderr}")
        return json.loads(process.stdout)
