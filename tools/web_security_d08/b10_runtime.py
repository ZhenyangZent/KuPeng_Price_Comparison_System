from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

from tools.web_security_d06.targets import safe_member_name

from .temp_scope import scoped_temp


def run_b10_wsgi(b10_zip: str | Path) -> dict[str, object]:
    source = Path(b10_zip)
    child = Path(__file__).with_name("b10_child.py")
    with scoped_temp("b10") as temporary:
        extracted = temporary / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if archive.testzip() is not None:
                raise ValueError("B10_ARCHIVE_CRC_FAILURE")
            if any(not safe_member_name(item.filename) for item in infos):
                raise ValueError("B10_ARCHIVE_UNSAFE_PATH")
            if any(stat.S_ISLNK(item.external_attr >> 16) for item in infos):
                raise ValueError("B10_ARCHIVE_SYMLINK")
            for item in infos:
                if item.is_dir():
                    continue
                target = extracted / PurePosixPath(item.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item.filename))
        roots = [item for item in extracted.iterdir() if item.is_dir()]
        if len(roots) != 1:
            raise ValueError("B10_ARCHIVE_ROOT_INVALID")
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, str(child), "--root", str(roots[0]), "--work", str(temporary / "fixture")],
            cwd=temporary, env=environment, text=True, encoding="utf-8", errors="strict",
            capture_output=True, check=False, timeout=120,
        )
        if result.returncode:
            raise RuntimeError(f"B10_RUNTIME_FAILURE:{result.returncode}:{result.stderr}")
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise RuntimeError("B10_RUNTIME_OUTPUT_INVALID")
        return value
