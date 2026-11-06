#!/usr/bin/env python3
"""Generate a path-only inventory from the explicitly selected project root.

The scanner does not follow symlinks or read sensitive file contents.  It only
hashes review ZIPs in release/queue/archive locations.  Dry-run is the default.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sys


SKIP_RELATIVE = {"docs/HANDOFF/PROJECT_FILE_INDEX.csv"}
SENSITIVE_PARTS = {".env", ".ssh", "credentials", "cookies", "secrets"}
ZIP_HASH_LOCATIONS = {"releases", "00_to_upload", "90_uploaded_archive"}
MAX_HASH_BYTES = 300_000_000


def sensitive_path(relative: Path) -> bool:
    return any(
        part.casefold() in SENSITIVE_PARTS or part.casefold().startswith(".env.")
        for part in relative.parts
    )


def hash_if_review_zip(path: Path, relative: Path, size: int) -> str:
    parts = {part.casefold() for part in relative.parts}
    if sensitive_path(relative):
        return "SKIPPED_SECRET"
    if (
        path.suffix.casefold() == ".zip"
        and "review" in parts
        and bool(ZIP_HASH_LOCATIONS & parts)
        and size <= MAX_HASH_BYTES
    ):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    return "NOT_HASHED"


def collect(root: Path) -> tuple[list[list[str]], list[str]]:
    records: list[list[str]] = []
    warnings: list[str] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory in list(directories):
            full = current_path / directory
            if full.is_symlink():
                directories.remove(directory)
                relative = full.relative_to(root)
                records.append([relative.as_posix(), "DIR_SYMLINK", "", "", "NOT_HASHED", "DO_NOT_FOLLOW"])
                warnings.append(relative.as_posix())
        for filename in files:
            full = current_path / filename
            relative = full.relative_to(root)
            if relative.as_posix() in SKIP_RELATIVE:
                continue
            try:
                if full.is_symlink():
                    records.append([relative.as_posix(), "SYMLINK", "", "", "NOT_HASHED", "DO_NOT_FOLLOW"])
                    warnings.append(relative.as_posix())
                    continue
                metadata = full.stat()
                records.append(
                    [
                        relative.as_posix(),
                        "FILE",
                        str(metadata.st_size),
                        datetime.fromtimestamp(metadata.st_mtime, timezone.utc).isoformat(),
                        hash_if_review_zip(full, relative, metadata.st_size),
                        "SENSITIVE_NAME_ONLY" if sensitive_path(relative) else "OK",
                    ]
                )
            except (OSError, PermissionError) as exc:
                records.append([relative.as_posix(), "ERROR", "", "", "NOT_HASHED", type(exc).__name__])
                warnings.append(relative.as_posix())
    records.sort(key=lambda record: record[0].casefold())
    return records, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.project_root.resolve(strict=True)
    if not root.is_dir() or root.name != "酷澎比價系統":
        raise RuntimeError("unexpected project root; external writes are denied")
    output = root / "docs/HANDOFF/PROJECT_FILE_INDEX.csv"
    records, warnings = collect(root)
    print(f"PROJECT_ROOT={root}")
    print(f"FILE_COUNT={len(records)};WARNINGS={len(warnings)};WRITE={args.write}")
    if warnings:
        print("WARNINGS_SAMPLES=" + repr(warnings[:10]))
    if not args.write:
        print("DRY_RUN: add --write to save inside docs/HANDOFF")
        return 0
    if output.exists():
        raise RuntimeError("PROJECT_FILE_INDEX.csv already exists; refusing overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".temporary")
    if temporary.exists():
        raise RuntimeError("inventory temporary file already exists")
    try:
        with temporary.open("x", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["relative_path", "kind", "bytes", "modified_utc", "sha256", "status"])
            writer.writerows(records)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(f"INVENTORY_WRITTEN={output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
