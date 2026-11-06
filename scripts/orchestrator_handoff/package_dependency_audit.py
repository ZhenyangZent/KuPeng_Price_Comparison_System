#!/usr/bin/env python3
"""Audit a review ZIP for historical dependencies and text-only secret scans.

Binary members such as ``.pyc`` are never decoded.  Historical evidence paths
referenced by tests must either be bundled byte-for-byte or declared in a
single INPUT_DEPENDENCY.json as NOT_RUN_INPUT_UNAVAILABLE with an exact hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HISTORICAL_REF_RE = re.compile(
    r"review/[A-H][0-9]{2}/[A-Z][A-Z0-9_.-]+\.(?:json|csv|md|zip)", re.ASCII
)
TEXT_SUFFIXES = {
    ".css", ".csv", ".html", ".ini", ".js", ".json", ".md", ".ps1",
    ".py", ".sh", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
}


class AuditError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if not name or "\\" in name or name.startswith("/") or ".." in path.parts:
        raise AuditError("UNSAFE_ZIP_PATH", name)
    return path.as_posix()


def _is_actual_env(name: str) -> bool:
    basename = PurePosixPath(name).name.casefold()
    return basename == ".env" or (basename.startswith(".env.") and basename != ".env.example")


def _dependencies(archive: zipfile.ZipFile, names: set[str]) -> dict[str, dict]:
    candidates = [name for name in names if PurePosixPath(name).name == "INPUT_DEPENDENCY.json"]
    if len(candidates) > 1:
        raise AuditError("DEPENDENCY_MANIFEST_AMBIGUOUS", str(candidates))
    if not candidates:
        return {}
    try:
        payload = json.loads(archive.read(candidates[0]))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError("INVALID_DEPENDENCY_MANIFEST", type(exc).__name__) from exc
    records = payload.get("dependencies") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise AuditError("INVALID_DEPENDENCY_MANIFEST", "dependencies must be an array")
    result: dict[str, dict] = {}
    for record in records:
        if not isinstance(record, dict):
            raise AuditError("INVALID_DEPENDENCY_RECORD", "record must be an object")
        path = record.get("path")
        sha256 = record.get("sha256")
        status = record.get("status")
        if not isinstance(path, str) or _safe_name(path) != path:
            raise AuditError("INVALID_DEPENDENCY_PATH", str(path))
        if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
            raise AuditError("INVALID_DEPENDENCY_SHA256", path)
        if status != "NOT_RUN_INPUT_UNAVAILABLE":
            raise AuditError("INVALID_DEPENDENCY_STATUS", path)
        if path in result:
            raise AuditError("DUPLICATE_DEPENDENCY", path)
        result[path] = record
    return result


def audit_zip(path: Path) -> dict:
    path = path.resolve(strict=True)
    references: set[str] = set()
    text_scanned = 0
    binary_skipped = 0
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise AuditError("CRC_FAILURE", path.name)
        names_list = [_safe_name(info.filename) for info in archive.infolist() if not info.is_dir()]
        if len({name.casefold() for name in names_list}) != len(names_list):
            raise AuditError("ZIP_PATH_COLLISION", path.name)
        names = set(names_list)
        env_paths = [name for name in names if _is_actual_env(name)]
        if env_paths:
            raise AuditError("ACTUAL_ENV_FORBIDDEN", env_paths[0])
        dependencies = _dependencies(archive, names)
        for name in sorted(names):
            suffix = PurePosixPath(name).suffix.casefold()
            if suffix not in TEXT_SUFFIXES:
                binary_skipped += 1
                continue
            try:
                text = archive.read(name).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise AuditError("TEXT_MEMBER_NOT_UTF8", name) from exc
            text_scanned += 1
            if name.startswith("tests/") or "/tests/" in name:
                references.update(HISTORICAL_REF_RE.findall(text))
        missing = sorted(ref for ref in references if ref not in names and ref not in dependencies)
        if missing:
            raise AuditError("UNDECLARED_HISTORICAL_DEPENDENCY", missing[0])
        declared_not_run = sorted(ref for ref in references if ref not in names and ref in dependencies)
        bundled = sorted(ref for ref in references if ref in names)
        return {
            "schema": "CDH-PACKAGE-DEPENDENCY-AUDIT-1",
            "zip": path.name,
            "zip_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "crc_gate": "PASS",
            "actual_env_gate": "PASS",
            "text_only_scan_gate": "PASS",
            "dependency_gate": "PASS",
            "text_members_scanned": text_scanned,
            "binary_members_skipped": binary_skipped,
            "historical_reference_count": len(references),
            "bundled_dependency_count": len(bundled),
            "not_run_input_unavailable_count": len(declared_not_run),
            "bundled_dependencies": bundled,
            "not_run_input_unavailable": declared_not_run,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(audit_zip(args.zip), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AuditError as exc:
        print(json.dumps({"error": exc.code, "detail": exc.detail}), file=sys.stderr)
        sys.exit(2)
