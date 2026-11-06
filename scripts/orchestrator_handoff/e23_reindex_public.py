#!/usr/bin/env python3
"""Rebuild the public Git candidate's path/hash index from staged paths."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "review/E23_GITHUB_CANDIDATE/repo"
INDEX = "docs/HANDOFF/PROJECT_FILE_INDEX.csv"


def main() -> None:
    assert ROOT.name == "酷澎比價系統" and (DEST / ".git").is_dir()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=DEST, text=True).strip()
    if branch not in {"main", "chore/cdh-github-consolidation-20261106"}:
        raise RuntimeError("unexpected branch")
    paths = subprocess.check_output(["git", "ls-files", "-z", "--cached"], cwd=DEST).split(b"\0")
    names = sorted({p.decode("utf-8") for p in paths if p and p.decode("utf-8") != INDEX})
    scope = "PUBLIC_MAIN" if branch == "main" else "PUBLIC_BRANCH_CANDIDATE"
    target = DEST / INDEX
    with target.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["relative_path", "sha256", "bytes", "publication_scope"])
        for name in names:
            path = DEST / name
            if not path.is_file() or path.is_symlink():
                raise RuntimeError(f"unsafe indexed path: {name}")
            data = subprocess.check_output(["git", "show", ":" + name], cwd=DEST)
            writer.writerow([name, hashlib.sha256(data).hexdigest(), len(data), scope])
    print(f"BRANCH={branch} INDEX_ROWS={len(names)}")


if __name__ == "__main__":
    main()
