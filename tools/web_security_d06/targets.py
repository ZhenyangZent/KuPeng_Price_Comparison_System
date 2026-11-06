from __future__ import annotations

import hashlib
import json
import re
import stat
import unicodedata
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class TargetIdentity:
    filename: str
    sha256: str
    bytes: int
    entries: int
    crc_pass: bool
    safe_paths: bool
    no_symlinks: bool
    no_casefold_duplicates: bool
    manifest_path: str
    manifest_sha256: str
    manifest_payload_count: int
    manifest_mismatch_count: int
    manifest_missing_count: int
    manifest_undeclared_count: int
    manifest_undeclared: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_BIDI_CONTROLS = {"\u061c", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069"}
_ALLOWED_DOT_FILES = {".env.example"}


def normalize_member_name(name: str) -> str:
    """Return a portable virtual path without changing archive bytes or ZipInfo."""
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError("TARGET_PATH_EMPTY_OR_NUL")
    if any(ord(character) < 0x20 or character in _BIDI_CONTROLS for character in name):
        raise ValueError("TARGET_PATH_CONTROL_OR_BIDI")
    if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
        raise ValueError("TARGET_PATH_ABSOLUTE_OR_DRIVE")
    if ("/" in name and "\\" in name) or "//" in name or "\\\\" in name:
        raise ValueError("TARGET_PATH_AMBIGUOUS_SEPARATOR")
    directory = name.endswith(("/", "\\"))
    normalized = name.replace("\\", "/")
    if directory:
        normalized = normalized[:-1]
    parts = normalized.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("TARGET_PATH_EMPTY_DOT_OR_TRAVERSAL")
    for part in parts:
        if part.endswith((" ", ".")) or ":" in part:
            raise ValueError("TARGET_PATH_CONCEALED_WINDOWS_NAME")
        if part.startswith(".") and part not in _ALLOWED_DOT_FILES:
            raise ValueError("TARGET_PATH_CONCEALED_DOTFILE")
        if unicodedata.normalize("NFC", part) != part:
            raise ValueError("TARGET_PATH_NONCANONICAL_UNICODE")
    value = "/".join(parts)
    return value + ("/" if directory else "")


def safe_member_name(name: str) -> bool:
    try:
        normalize_member_name(name)
        return True
    except ValueError:
        return False


def _member_map(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    result: dict[str, zipfile.ZipInfo] = {}
    folded: dict[str, str] = {}
    for info in archive.infolist():
        raw_name = info.orig_filename
        normalized = normalize_member_name(raw_name)
        folded_name = normalized.casefold()
        if folded_name in folded:
            raise ValueError(f"TARGET_PATH_NORMALIZED_CASEFOLD_DUPLICATE:{folded[folded_name]}:{raw_name}")
        folded[folded_name] = raw_name
        result[normalized] = info
    return result


def read_unique_member(path: str | Path, suffix: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        members = _member_map(archive)
        matches = [name for name in members if name.endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f"TARGET_MEMBER_COUNT:{suffix}:{len(matches)}")
        return archive.read(members[matches[0]])


def unique_member_name(path: str | Path, suffix: str) -> str:
    with zipfile.ZipFile(path) as archive:
        members = _member_map(archive)
        matches = [name for name in members if name.endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f"TARGET_MEMBER_COUNT:{suffix}:{len(matches)}")
        return matches[0]


def _manifest(archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo]) -> tuple[str, bytes, dict[str, object]]:
    candidates = [
        name for name in members
        if name.count("/") == 1
        and (name.endswith("/REVIEW_MANIFEST.json") or name.endswith("/MANIFEST.json"))
    ]
    if len(candidates) != 1:
        raise ValueError(f"TARGET_TOP_MANIFEST_COUNT:{len(candidates)}")
    raw = archive.read(members[candidates[0]])
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("TARGET_MANIFEST_ROOT_INVALID")
    return candidates[0], raw, value


def verify_target(
    path: str | Path,
    *,
    expected_sha256: str,
    reject_undeclared: bool = False,
) -> TargetIdentity:
    target = Path(path)
    digest = sha256_file(target)
    if digest != expected_sha256:
        raise ValueError(f"TARGET_SHA256_MISMATCH:{target.name}:{digest}")
    with zipfile.ZipFile(target) as archive:
        infos = archive.infolist()
        members = _member_map(archive)
        names = list(members)
        files = {name for name in names if not name.endswith("/")}
        manifest_name, manifest_raw, manifest = _manifest(archive, members)
        records = manifest.get("files", manifest.get("payloads"))
        if not isinstance(records, list):
            raise ValueError("TARGET_MANIFEST_RECORDS_INVALID")
        prefix = manifest_name.rsplit("/", 1)[0] + "/"
        declared: set[str] = set()
        mismatch: list[str] = []
        missing: list[str] = []
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise ValueError("TARGET_MANIFEST_RECORD_INVALID")
            record_name = normalize_member_name(str(record["path"]))
            if record_name.endswith("/"):
                raise ValueError("TARGET_MANIFEST_RECORD_DIRECTORY_INVALID")
            member = record_name if record_name in files else prefix + record_name
            declared.add(member)
            if member not in files:
                missing.append(member)
                continue
            raw = archive.read(members[member])
            expected_bytes = record.get("bytes", record.get("size"))
            if len(raw) != expected_bytes or hashlib.sha256(raw).hexdigest() != record.get("sha256"):
                mismatch.append(member)
        undeclared = tuple(sorted(files - declared - {manifest_name}))
        result = TargetIdentity(
            filename=target.name,
            sha256=digest,
            bytes=target.stat().st_size,
            entries=len(names),
            crc_pass=archive.testzip() is None,
            safe_paths=True,
            no_symlinks=not any(stat.S_ISLNK(item.external_attr >> 16) for item in infos),
            no_casefold_duplicates=True,
            manifest_path=manifest_name,
            manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
            manifest_payload_count=len(records),
            manifest_mismatch_count=len(mismatch),
            manifest_missing_count=len(missing),
            manifest_undeclared_count=len(undeclared),
            manifest_undeclared=undeclared,
        )
    if not all((result.crc_pass, result.safe_paths, result.no_symlinks, result.no_casefold_duplicates)):
        raise ValueError(f"TARGET_ZIP_SAFETY_FAILURE:{target.name}")
    if result.manifest_mismatch_count or result.manifest_missing_count:
        raise ValueError(f"TARGET_MANIFEST_INTEGRITY_FAILURE:{target.name}")
    if reject_undeclared and result.manifest_undeclared_count:
        raise ValueError(f"TARGET_MANIFEST_UNDECLARED_FILES:{target.name}:{result.manifest_undeclared_count}")
    return result
