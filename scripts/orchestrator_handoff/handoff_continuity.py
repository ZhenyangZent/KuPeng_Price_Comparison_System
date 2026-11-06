#!/usr/bin/env python3
"""Build an offline five-minute handoff status and protected hash inventory.

The scanner is deliberately allowlist-based.  It never reads root ``.env``
contents, follows no symlinks, performs no network/Git/browser/Registry work,
and writes only the three documented files under ``docs/HANDOFF``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from flat_queue import list_queue
from handoff_batch import HandoffError


ROLE_RE = re.compile(r"^[A-H]$")
STATUS_RE = re.compile(r"^[A-Z0-9_]{2,80}$")
EXPECTED_REVIEW_RE = re.compile(r"^CDH_[A-Z0-9_]+_(?:REVIEW|STATUS_ONLY)\.zip$")
PROTECTED_DOCS = (
    "docs/HANDOFF/MASTER_HANDOFF.md",
    "docs/HANDOFF/PROJECT_FILE_INDEX.csv",
    "docs/HANDOFF/TASK_STATUS_INDEX.json",
    "docs/HANDOFF/CROSSLINE_STATUS_INDEX.md",
    "docs/HANDOFF/RECEIPT_LEDGER.jsonl",
    "docs/HANDOFF/EXTERNAL_PATH_LEDGER.csv",
    "docs/HANDOFF/UPLOAD_QUEUE_PROTOCOL.md",
    "docs/HANDOFF/WINDOWS_USAGE.md",
    "docs/HANDOFF/NEXT_ACTIONS.md",
    "docs/HANDOFF/R05_RECEIPT_STATUS_LEDGER.json",
    "docs/HANDOFF/R06_RECEIPT_STATUS_LEDGER.json",
    "docs/HANDOFF/R07_RECEIPT_STATUS_LEDGER.json",
    "docs/HANDOFF/R08_RECEIPT_STATUS_LEDGER.json",
    "docs/HANDOFF/R09_RECEIPT_STATUS_LEDGER.json",
    "docs/HANDOFF/WORKLINE_STATUS.md",
)
STATUS_PATH = "docs/HANDOFF/LATEST_HANDOFF_STATUS.json"
INVENTORY_PATH = "docs/HANDOFF/PROTECTED_HASH_INVENTORY.json"
SUMMARY_PATH = "docs/HANDOFF/FIVE_MINUTE_STATUS.md"


def _fail(code: str, detail: str) -> None:
    raise HandoffError(code, detail)


def _root(root: Path) -> Path:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        _fail("INVALID_PROJECT_ROOT", "project root must be a directory")
    return resolved


def _inside(root: Path, path: Path, *, must_exist: bool = False) -> Path:
    resolved = path.resolve(strict=must_exist)
    if not resolved.is_relative_to(root):
        _fail("OUTSIDE_PROJECT_ROOT", f"path escapes project root: {path}")
    return resolved


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _read_json(path: Path, code: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(code, f"cannot read JSON {path.name}: {type(exc).__name__}")


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _canonical_hash(records: list[dict]) -> str:
    encoded = (
        json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_protected_inventory(root: Path) -> dict:
    root = _root(root)
    paths: list[Path] = []
    for relative in PROTECTED_DOCS:
        candidate = root / relative
        if candidate.exists():
            paths.append(candidate)
    releases = root / "review/releases"
    if releases.exists():
        paths.extend(sorted(releases.glob("*.zip"), key=lambda path: path.name.casefold()))
    archive_root = root / "review/90_UPLOADED_ARCHIVE"
    if archive_root.exists():
        paths.extend(
            sorted(archive_root.glob("*/ARCHIVE_RECEIPT.json"), key=lambda path: path.as_posix())
        )
    records: list[dict] = []
    seen: set[str] = set()
    for path in paths:
        resolved = _inside(root, path, must_exist=True)
        if resolved.is_symlink() or not resolved.is_file():
            _fail("UNSAFE_PROTECTED_PATH", f"protected path is not a regular file: {path}")
        relative = resolved.relative_to(root).as_posix()
        key = relative.casefold()
        if key in seen:
            _fail("PROTECTED_PATH_COLLISION", f"duplicate protected path: {relative}")
        seen.add(key)
        records.append(
            {"path": relative, "bytes": resolved.stat().st_size, "sha256": digest(resolved)}
        )
    records.sort(key=lambda item: item["path"].casefold())
    return {
        "schema": "CDH-PROTECTED-HASH-INVENTORY-1",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "record_count": len(records),
        "canonical_records_sha256": _canonical_hash(records),
        "root_env_content_read": False,
        "records": records,
    }


def _receipt_records(root: Path) -> list[dict]:
    archive_root = root / "review/90_UPLOADED_ARCHIVE"
    records: list[dict] = []
    identifiers: set[str] = set()
    if not archive_root.exists():
        return records
    for path in sorted(archive_root.glob("*/ARCHIVE_RECEIPT.json")):
        resolved = _inside(root, path, must_exist=True)
        payload = _read_json(resolved, "INVALID_ARCHIVE_RECEIPT")
        values = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            _fail("INVALID_ARCHIVE_RECEIPT", f"receipt has no records array: {path}")
        for record in values:
            if not isinstance(record, dict) or not isinstance(record.get("record_id"), str):
                _fail("INVALID_ARCHIVE_RECEIPT", f"invalid receipt record: {path}")
            if record["record_id"] in identifiers:
                _fail("DUPLICATE_RECEIPT_RECORD", record["record_id"])
            identifiers.add(record["record_id"])
            records.append(record)
    return sorted(records, key=lambda item: (item.get("archived_at_utc", ""), item["record_id"]))


def _assignments(root: Path, path: Path) -> dict:
    candidate = path if path.is_absolute() else root / path
    resolved = _inside(root, candidate, must_exist=True)
    if resolved.is_symlink() or not resolved.is_file():
        _fail("INVALID_ASSIGNMENTS", "assignments must be a regular file")
    payload = _read_json(resolved, "INVALID_ASSIGNMENTS")
    if not isinstance(payload, dict):
        _fail("INVALID_ASSIGNMENTS", "assignments root must be an object")
    roles = payload.get("roles")
    if isinstance(roles, dict):
        return {"roles": roles, "input_shape": "NESTED_ROLES"}
    worklines = payload.get("worklines")
    if isinstance(worklines, dict):
        return {"roles": worklines, "input_shape": "NESTED_WORKLINES"}
    # R05 changed ASSIGNMENTS.json to a flat A..H mapping.  Normalize both
    # centrally issued shapes so status rebuilding cannot silently omit every
    # role after an orchestrator format transition.
    flat_roles = {
        role: assignment
        for role, assignment in payload.items()
        if isinstance(role, str)
        and ROLE_RE.fullmatch(role)
        and isinstance(assignment, dict)
    }
    if not flat_roles:
        _fail("INVALID_ASSIGNMENTS", "assignments has no nested roles/worklines or flat A..H map")
    return {"roles": flat_roles, "input_shape": "FLAT_ROLE_MAP"}


def build_status(
    root: Path,
    assignments_path: Path,
    overrides: dict[str, str] | None = None,
    expected_overrides: dict[str, str] | None = None,
) -> dict:
    root = _root(root)
    queue = list_queue(root)
    receipts = _receipt_records(root)
    assignments = _assignments(root, assignments_path)
    queue_by_name = {item["name"]: item for item in queue["files"]}
    archived_by_name: dict[str, list[dict]] = {}
    for record in receipts:
        filename = record.get("filename")
        if isinstance(filename, str):
            archived_by_name.setdefault(filename, []).append(record)
    roles: dict[str, dict] = {}
    overrides = overrides or {}
    expected_overrides = expected_overrides or {}
    for role, assignment in sorted(assignments["roles"].items()):
        if not ROLE_RE.fullmatch(role) or not isinstance(assignment, dict):
            continue
        expected = expected_overrides.get(
            role,
            assignment.get(
                "expected_review",
                assignment.get("next_review_zip", assignment.get("deliverable")),
            ),
        )
        if not isinstance(expected, str):
            roles[role] = {
                "task_id": assignment.get("task_id", "UNKNOWN"),
                "expected_review": None,
                "state": overrides.get(role, "ASSIGNED_INPUT_UNAVAILABLE"),
                "observed_sha256": None,
            }
            continue
        release = root / "review/releases" / expected
        if expected in queue_by_name:
            state = "PENDING_UPLOAD"
            observed_sha = queue_by_name[expected]["sha256"]
        elif expected in archived_by_name:
            state = "ACKNOWLEDGED_ARCHIVED"
            observed_sha = archived_by_name[expected][-1].get("sha256")
        elif release.is_file() and not release.is_symlink():
            state = "RELEASE_EXISTS_NOT_QUEUED"
            observed_sha = digest(release)
        else:
            state = "AUTHORIZED_NOT_OBSERVED"
            observed_sha = None
        if role in overrides:
            state = overrides[role]
        roles[role] = {
            "task_id": assignment.get("task_id", "UNKNOWN"),
            "expected_review": expected,
            "state": state,
            "observed_sha256": observed_sha,
        }
    return {
        "schema": "CDH-LATEST-HANDOFF-STATUS-1",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "queue": queue,
        "receipt_record_count": len(receipts),
        "archive_batch_count": len({item.get("archive_id") for item in receipts}),
        "roles": roles,
        "assignments_input_shape": assignments["input_shape"],
        "source_status": "SOURCE_BLOCKED",
        "affiliate_capability": "UNVERIFIED",
        "functional_pass_inferred_from_ack": False,
    }


def render_summary(status: dict, inventory: dict) -> str:
    lines = [
        "# Coupang Deal Hunter｜五分鐘重建現況",
        "",
        f"GENERATED_AT_UTC: `{status['generated_at_utc']}`",
        f"QUEUE_PENDING_COUNT: `{status['queue']['pending_count']}`",
        f"RECEIPT_RECORD_COUNT: `{status['receipt_record_count']}`",
        f"PROTECTED_RECORD_COUNT: `{inventory['record_count']}`",
        f"PROTECTED_CANONICAL_SHA256: `{inventory['canonical_records_sha256']}`",
        "ROOT_ENV_CONTENT_READ: `false`",
        "",
        "## 五分鐘步驟",
        "",
        "1. 核對本檔、`LATEST_HANDOFF_STATUS.json` 與 `PROTECTED_HASH_INVENTORY.json`。",
        "2. 執行 `flat_queue.py list`；queue 只能含完整平面 review ZIP。",
        "3. 上傳 queue 內全部 ZIP；中央逐檔回完整 filename/SHA-256。",
        "4. 只有 exact ACK 才可 archive；RECEIVED 不等於功能 PASS。",
        "5. `.env`、Firefox、Registry、真實來源、部署與交易仍不在本工具權限。",
        "",
        "## Queue exact inventory",
        "",
    ]
    if status["queue"]["files"]:
        for item in status["queue"]["files"]:
            lines.append(f"- `{item['name']}` — `{item['sha256']}` — {item['size_bytes']} bytes")
    else:
        lines.append("- `EMPTY`")
    lines.extend(["", "## Role state", "", "| Role | Task | Expected review | State |", "|---|---|---|---|"])
    for role, item in status["roles"].items():
        lines.append(
            f"| {role} | `{item['task_id']}` | `"
            f"{item['expected_review'] if item['expected_review'] is not None else 'UNKNOWN'}` | "
            f"`{item['state']}` |"
        )
    lines.extend(
        [
            "",
            "`SOURCE_BLOCKED` and affiliate capability `UNVERIFIED` remain fail-closed.",
            "",
        ]
    )
    return "\n".join(lines)


def _overrides(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            _fail("INVALID_ROLE_OVERRIDE", "role override must be ROLE=STATUS")
        role, status = value.split("=", 1)
        if not ROLE_RE.fullmatch(role) or not STATUS_RE.fullmatch(status):
            _fail("INVALID_ROLE_OVERRIDE", f"invalid role override: {value}")
        parsed[role] = status
    return parsed


def _expected_overrides(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            _fail("INVALID_EXPECTED_OVERRIDE", "expected delivery override must be ROLE=FILENAME")
        role, filename = value.split("=", 1)
        if not ROLE_RE.fullmatch(role) or not EXPECTED_REVIEW_RE.fullmatch(filename):
            _fail("INVALID_EXPECTED_OVERRIDE", f"invalid expected review override: {value}")
        parsed[role] = filename
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--assignments", required=True, type=Path)
    parser.add_argument("--role-status", action="append", default=[])
    parser.add_argument("--expected-review", action="append", default=[])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = _root(args.project_root)
    inventory = build_protected_inventory(root)
    status = build_status(
        root,
        args.assignments,
        _overrides(args.role_status),
        _expected_overrides(args.expected_review),
    )
    summary = render_summary(status, inventory)
    if args.write:
        _write_atomic(root / INVENTORY_PATH, json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        _write_atomic(root / STATUS_PATH, json.dumps(status, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        _write_atomic(root / SUMMARY_PATH, summary)
    print(
        json.dumps(
            {
                "write": args.write,
                "queue_pending_count": status["queue"]["pending_count"],
                "receipt_record_count": status["receipt_record_count"],
                "protected_record_count": inventory["record_count"],
                "protected_canonical_sha256": inventory["canonical_records_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HandoffError as exc:
        print(json.dumps({"error": exc.code, "detail": exc.detail}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(json.dumps({"error": "UNEXPECTED_FAILURE", "detail": type(exc).__name__}), file=sys.stderr)
        sys.exit(3)
