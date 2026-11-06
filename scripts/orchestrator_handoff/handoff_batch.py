#!/usr/bin/env python3
"""Offline, fail-closed handoff batch manager for Coupang Deal Hunter.

The tool only reads completed release ZIPs, writes a single pending batch ZIP,
and archives an acknowledged batch after an exact SHA-256 receipt check.
It uses only the Python standard library and performs no network access.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
import uuid
import zipfile
import zlib


SCHEMA = "CDH-HANDOFF-BATCH-1"
PKG_RE = re.compile(r"^CDH_[A-Z0-9_]+_REVIEW\.zip$")
BATCH_NAME_RE = re.compile(r"^CDH_BATCH_([A-Za-z0-9_-]{4,40})_REVIEW\.zip$")
BATCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_RELEASES = 30
MAX_FILE_BYTES = 1_000_000_000
MAX_BATCH_BYTES = 1_500_000_000
MAX_UNCOMPRESSED_BYTES = 1_500_000_000
MAX_MEMBERS = 20_000

SENSITIVE_COMPONENTS = {".venv", ".git", "__pycache__"}
SENSITIVE_SUFFIXES = {
    ".sqlite", ".sqlite3", ".db", ".db3", ".reg", ".pem", ".key",
    ".pfx", ".p12",
}
SENSITIVE_BASENAMES = {
    ".env", "cookies", "cookies.sqlite", "key4.db", "logins.json",
    "places.sqlite", "webappsstore.sqlite", "access_token", "refresh_token",
}
SENSITIVE_WORD_RE = re.compile(r"(?:^|[_.-])(token|cookie|credential|secret)(?:[_.-]|$)")
WINDOWS_RESERVED_RE = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.IGNORECASE
)


class HandoffError(ValueError):
    """Expected fail-closed validation error with a stable machine code."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _fail(code: str, detail: str) -> None:
    raise HandoffError(code, detail)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_member(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name, "r") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _under_root(root: Path, child: Path, *, must_exist: bool = False) -> Path:
    resolved_root = root.resolve(strict=True)
    resolved_child = child.resolve(strict=must_exist)
    if not resolved_child.is_relative_to(resolved_root):
        _fail("OUTSIDE_PROJECT_ROOT", f"path escapes project root: {child}")
    return resolved_child


def _ensure_directory(root: Path, relative: str) -> Path:
    target = root / relative
    existing = target
    while not existing.exists():
        if existing == existing.parent:
            _fail("OUTSIDE_PROJECT_ROOT", f"no safe ancestor for directory: {relative}")
        existing = existing.parent
    _under_root(root, existing, must_exist=True)
    target.mkdir(parents=True, exist_ok=True)
    resolved = _under_root(root, target, must_exist=True)
    if resolved.is_symlink() or not resolved.is_dir():
        _fail("UNSAFE_DIRECTORY", f"directory is not a regular directory: {relative}")
    return resolved


def _windows_key(name: str) -> str:
    parts: list[str] = []
    for raw in name.split("/"):
        normalized = unicodedata.normalize("NFC", raw).rstrip(" .").casefold()
        parts.append(normalized)
    return "/".join(parts)


def _validate_member_name(name: str) -> str:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        _fail("UNSAFE_ZIP_PATH", f"unsafe ZIP entry: {name!r}")
    if re.match(r"^[A-Za-z]:", name):
        _fail("UNSAFE_ZIP_PATH", f"drive-qualified ZIP entry: {name!r}")
    raw_parts = name.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts[:-1]) or raw_parts[-1] in {".", ".."}:
        _fail("UNSAFE_ZIP_PATH", f"relative traversal ZIP entry: {name!r}")
    path = PurePosixPath(name)
    parts = path.parts
    for part in parts:
        normalized = unicodedata.normalize("NFC", part)
        if normalized.rstrip(" .") != normalized or ":" in normalized:
            _fail("WINDOWS_UNSAFE_ZIP_PATH", f"Windows-unsafe ZIP entry: {name!r}")
        if WINDOWS_RESERVED_RE.fullmatch(normalized):
            _fail("WINDOWS_UNSAFE_ZIP_PATH", f"reserved Windows ZIP entry: {name!r}")
    return _windows_key(name)


def _sensitive_reason(name: str) -> str | None:
    normalized_parts = [unicodedata.normalize("NFC", p).casefold() for p in name.split("/")]
    if any(part in SENSITIVE_COMPONENTS for part in normalized_parts):
        return "environment, VCS, or cache directory"
    basename = normalized_parts[-1].rstrip("/")
    if basename in SENSITIVE_BASENAMES:
        return "credential, browser-profile, or environment filename"
    if Path(basename).suffix.casefold() in SENSITIVE_SUFFIXES:
        return "database, registry, or private-key file"
    if SENSITIVE_WORD_RE.search(basename):
        return "credential-like filename"
    return None


def inspect_zip(path: Path, *, reject_sensitive: bool = True) -> dict:
    """Validate CRC, member paths/types, duplicate aliases, limits, and secrets."""
    if not path.is_file() or path.is_symlink():
        _fail("ZIP_NOT_REGULAR_FILE", f"ZIP must be a regular file: {path}")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        _fail("ZIP_FILE_TOO_LARGE", f"ZIP exceeds {MAX_FILE_BYTES} bytes: {path.name}")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            if len(members) > MAX_MEMBERS:
                _fail("ZIP_TOO_MANY_ENTRIES", f"ZIP contains {len(members)} entries")
            seen: set[str] = set()
            cumulative = 0
            for info in members:
                key = _validate_member_name(info.filename)
                if key in seen:
                    _fail("DUPLICATE_ZIP_PATH", f"case/Unicode duplicate ZIP entry: {info.filename}")
                seen.add(key)
                if info.flag_bits & 0x1:
                    _fail("ENCRYPTED_ZIP_ENTRY", f"encrypted ZIP entry denied: {info.filename}")
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if stat.S_ISLNK(mode):
                    _fail("SYMLINK_ZIP_ENTRY", f"symlink ZIP entry denied: {info.filename}")
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    _fail("SPECIAL_ZIP_ENTRY", f"special ZIP entry denied: {info.filename}")
                if reject_sensitive and not info.is_dir():
                    reason = _sensitive_reason(info.filename)
                    if reason:
                        _fail("SENSITIVE_RELEASE_CONTENT", f"{reason}: {info.filename}")
                cumulative += info.file_size
                if cumulative > MAX_UNCOMPRESSED_BYTES:
                    _fail("ZIP_UNCOMPRESSED_LIMIT", "ZIP uncompressed payload exceeds limit")
            try:
                damaged = archive.testzip()
            except (OSError, RuntimeError, zlib.error) as exc:
                _fail("ZIP_CRC_FAILURE", f"ZIP payload decompression/CRC failed: {type(exc).__name__}")
            if damaged is not None:
                _fail("ZIP_CRC_FAILURE", f"CRC failed for ZIP entry: {damaged}")
    except zipfile.BadZipFile as exc:
        _fail("INVALID_ZIP", f"invalid or damaged ZIP {path.name}: {exc}")
    return {
        "name": path.name,
        "size_bytes": size,
        "sha256": sha256(path),
        "entries": len(members),
        "uncompressed_bytes": cumulative,
        "crc": "PASS",
        "path_safety": "PASS",
        "sensitive_content_gate": "PASS" if reject_sensitive else "NOT_APPLICABLE",
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


class _BuildLock:
    def __init__(self, lock_path: Path):
        self.path = lock_path
        self.fd: int | None = None

    def __enter__(self) -> "_BuildLock":
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(self.fd, json.dumps({"pid": os.getpid()}).encode("ascii"))
            os.fsync(self.fd)
        except FileExistsError:
            _fail("BUILD_LOCKED", f"another build or interrupted lock exists: {self.path.name}")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _verify_batch(path: Path, expected_manifest: dict) -> dict:
    outer = inspect_zip(path, reject_sensitive=False)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            actual_manifest = json.loads(archive.read("BATCH_MANIFEST.json"))
            if actual_manifest != expected_manifest:
                _fail("BATCH_MANIFEST_MISMATCH", "batch manifest readback differs from build input")
            expected_names = {"BATCH_MANIFEST.json"}
            for record in expected_manifest["files"]:
                member = f"packages/{record['name']}"
                expected_names.add(member)
                if _sha256_member(archive, member) != record["sha256"]:
                    _fail("EMBEDDED_RELEASE_HASH_MISMATCH", f"embedded hash mismatch: {record['name']}")
            if set(archive.namelist()) != expected_names:
                _fail("UNDECLARED_BATCH_MEMBER", "batch contains undeclared members")
    except (KeyError, json.JSONDecodeError) as exc:
        _fail("INVALID_BATCH_MANIFEST", f"cannot read batch manifest: {exc}")
    return outer


def create_batch(root: Path, batch_id: str, files: list[str]) -> dict:
    root = root.resolve(strict=True)
    if not BATCH_ID_RE.fullmatch(batch_id):
        _fail("INVALID_BATCH_ID", "batch ID must be 4..40 ASCII letters, digits, '_' or '-'")
    if not 1 <= len(files) <= MAX_RELEASES:
        _fail("INVALID_RELEASE_COUNT", f"require 1..{MAX_RELEASES} release ZIPs")
    if len(set(files)) != len(files):
        _fail("REPEATED_RELEASE_NAME", "release filenames must be unique")

    releases = _under_root(root, root / "review/releases", must_exist=True)
    if releases.is_symlink() or not releases.is_dir():
        _fail("UNSAFE_RELEASE_DIRECTORY", "review/releases must be a regular directory")
    outdir = _ensure_directory(root, "review/00_TO_UPLOAD")
    lockdir = _ensure_directory(root, "experiments/E01/locks")
    target = outdir / f"CDH_BATCH_{batch_id}_REVIEW.zip"
    if target.exists():
        _fail("BATCH_ALREADY_EXISTS", f"batch already exists: {target.name}")

    records: list[dict] = []
    total = 0
    for name in sorted(files):
        if not PKG_RE.fullmatch(name) or name.startswith("CDH_BATCH_"):
            _fail("INVALID_RELEASE_NAME", f"not a permitted release filename: {name}")
        path = _under_root(root, releases / name, must_exist=True)
        if path.parent != releases:
            _fail("RELEASE_ESCAPED_DIRECTORY", f"release escaped parent: {name}")
        record = inspect_zip(path, reject_sensitive=True)
        total += record["size_bytes"]
        if total > MAX_BATCH_BYTES:
            _fail("BATCH_SIZE_LIMIT", "combined release ZIP size exceeds limit")
        records.append(record)

    manifest = {
        "schema": SCHEMA,
        "batch_id": batch_id,
        "original_releases_preserved": True,
        "release_count": len(records),
        "files": records,
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    temporary = outdir / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.partial"
    lock_path = lockdir / f"{target.name}.lock"
    try:
        with _BuildLock(lock_path):
            if target.exists():
                _fail("BATCH_ALREADY_EXISTS", f"batch already exists: {target.name}")
            with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
                archive.writestr(_zip_info("BATCH_MANIFEST.json"), manifest_bytes)
                for record in records:
                    source = releases / record["name"]
                    archive.write(
                        source,
                        arcname=f"packages/{record['name']}",
                        compress_type=zipfile.ZIP_STORED,
                    )
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            outer = _verify_batch(temporary, manifest)
            os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()

    output = _verify_batch(target, manifest)
    output.update(
        {
            "batch_id": batch_id,
            "bundled_release_count": len(records),
            "pending_upload": True,
            "original_releases_preserved": True,
        }
    )
    return output


def list_pending(root: Path) -> dict:
    root = root.resolve(strict=True)
    pending = root / "review/00_TO_UPLOAD"
    if not pending.exists():
        return {"files": [], "pending_count": 0}
    pending = _under_root(root, pending, must_exist=True)
    if pending.is_symlink() or not pending.is_dir():
        _fail("UNSAFE_UPLOAD_DIRECTORY", "review/00_TO_UPLOAD must be a regular directory")
    files: list[dict] = []
    for path in sorted(pending.iterdir(), key=lambda item: item.name.casefold()):
        if path.name.startswith(".") and path.name.endswith(".partial"):
            _fail("INTERRUPTED_BUILD_ARTIFACT", f"partial build requires operator review: {path.name}")
        if not BATCH_NAME_RE.fullmatch(path.name):
            _fail("UNEXPECTED_UPLOAD_ENTRY", f"unexpected item in upload queue: {path.name}")
        files.append(inspect_zip(path, reject_sensitive=False))
    return {"files": files, "pending_count": len(files)}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_receipt(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("INVALID_ARCHIVE_RECEIPT", f"cannot read archive receipt: {exc}")


def archive_acknowledged(root: Path, name: str, expected_sha: str, acknowledged: bool) -> dict:
    root = root.resolve(strict=True)
    if not acknowledged:
        _fail("ACKNOWLEDGEMENT_REQUIRED", "archive requires explicit central Orchestrator acknowledgement")
    match = BATCH_NAME_RE.fullmatch(name)
    if not match:
        _fail("INVALID_BATCH_NAME", "only a valid CDH batch ZIP can be archived")
    if not HEX_RE.fullmatch(expected_sha):
        _fail("INVALID_SHA256", "expected sha256 must be 64 lowercase hexadecimal characters")

    batch_id = match.group(1)
    pending = _ensure_directory(root, "review/00_TO_UPLOAD")
    archive_dir = _ensure_directory(root, f"review/90_UPLOADED_ARCHIVE/{batch_id}")
    source = pending / name
    destination = archive_dir / name
    receipt_path = archive_dir / "ARCHIVE_RECEIPT.json"

    # Idempotent recovery: a prior atomic move may have completed before receipt write.
    if not source.exists() and destination.exists():
        actual = sha256(destination)
        if actual != expected_sha:
            _fail("ARCHIVED_HASH_MISMATCH", "existing archived batch has a different SHA-256")
        recovered = not receipt_path.exists()
        if receipt_path.exists():
            receipt = _read_receipt(receipt_path)
            if receipt.get("file") != name or receipt.get("sha256") != expected_sha:
                _fail("ARCHIVE_RECEIPT_MISMATCH", "existing receipt does not match acknowledged batch")
        else:
            receipt = {
                "schema": "CDH-HANDOFF-ARCHIVE-RECEIPT-1",
                "batch_id": batch_id,
                "file": name,
                "sha256": expected_sha,
                "acknowledged_by": "central_orchestrator_explicit_receipt",
                "archived_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "recovered_after_completed_move": True,
            }
            _write_json_atomic(receipt_path, receipt)
        return {
            "archived_to": str(destination),
            "sha256": expected_sha,
            "release_originals_untouched": True,
            "already_archived": not recovered,
            "recovered_receipt": recovered,
        }

    if not source.exists():
        _fail("PENDING_BATCH_MISSING", f"pending batch does not exist: {name}")
    if source.is_symlink() or not source.is_file():
        _fail("PENDING_BATCH_NOT_REGULAR", "pending batch must be a regular file")
    if destination.exists() or receipt_path.exists():
        _fail("ARCHIVE_COLLISION", "archive destination or receipt already exists")
    inspect_zip(source, reject_sensitive=False)
    actual = sha256(source)
    if actual != expected_sha:
        _fail("RECEIPT_SHA256_MISMATCH", "receipt sha256 does not match pending batch")

    os.replace(source, destination)
    if sha256(destination) != expected_sha:
        _fail("POST_MOVE_SHA256_MISMATCH", "post-move SHA-256 verification failed")
    receipt = {
        "schema": "CDH-HANDOFF-ARCHIVE-RECEIPT-1",
        "batch_id": batch_id,
        "file": name,
        "sha256": expected_sha,
        "acknowledged_by": "central_orchestrator_explicit_receipt",
        "archived_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "recovered_after_completed_move": False,
    }
    _write_json_atomic(receipt_path, receipt)
    return {
        "archived_to": str(destination),
        "sha256": expected_sha,
        "release_originals_untouched": True,
        "already_archived": False,
        "recovered_receipt": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="action", required=True)
    build = subparsers.add_parser("build", help="create one pending batch from named releases")
    build.add_argument("--batch-id", required=True)
    build.add_argument("--files", nargs="+", required=True)
    subparsers.add_parser("list", help="validate and list pending batch ZIPs")
    archive = subparsers.add_parser("archive", help="archive one explicitly acknowledged batch")
    archive.add_argument("--name", required=True)
    archive.add_argument("--sha256", required=True)
    archive.add_argument("--acknowledged", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.project_root.resolve(strict=True)
    if args.action == "build":
        result = create_batch(root, args.batch_id, args.files)
    elif args.action == "list":
        result = list_pending(root)
    else:
        result = archive_acknowledged(root, args.name, args.sha256, args.acknowledged)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HandoffError as exc:
        print(
            json.dumps({"error": exc.code, "detail": exc.detail}, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception as exc:  # fail closed without a traceback or accidental secret dump
        print(
            json.dumps({"error": "UNEXPECTED_FAILURE", "detail": type(exc).__name__}, sort_keys=True),
            file=sys.stderr,
        )
        sys.exit(3)
