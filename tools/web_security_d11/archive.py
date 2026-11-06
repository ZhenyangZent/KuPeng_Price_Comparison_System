from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath

A11_SHA256 = "40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd"
A11_ROOT = "CDH_A_R09_001_REVIEW/"
A11_DOTFILE_ALLOWLIST = {
    A11_ROOT + "apps/price-web/frontend/.env.example",
    A11_ROOT + "apps/price-web/frontend/.gitignore",
}
B14_SHA256 = "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normal(name: str) -> str:
    value = name.replace("\\", "/")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_MEMBER:{name}")
    return pure.as_posix()


def verify_a11(path: Path, expected_sha256: str = A11_SHA256) -> dict[str, object]:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ValueError(f"A11_SHA256_MISMATCH:{actual}")
    with zipfile.ZipFile(path) as archive:
        bad_crc = archive.testzip()
        if bad_crc is not None:
            raise ValueError(f"A11_CRC_FAILURE:{bad_crc}")
        members: dict[str, zipfile.ZipInfo] = {}
        folded: set[str] = set()
        for info in archive.infolist():
            name = _normal(info.filename.rstrip("/"))
            if name.casefold() in folded:
                raise ValueError(f"A11_CASEFOLD_DUPLICATE:{name}")
            folded.add(name.casefold())
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"A11_SYMLINK:{name}")
            concealed = [part for part in PurePosixPath(name).parts if part.startswith(".")]
            if concealed and name not in A11_DOTFILE_ALLOWLIST:
                raise ValueError(f"A11_UNEXPECTED_CONCEALED_PATH:{name}")
            members[name] = info
        manifest_name = A11_ROOT + "SHA256_MANIFEST.json"
        manifest_raw = archive.read(members[manifest_name])
        manifest = json.loads(manifest_raw)
        records = manifest.get("payloads")
        if not isinstance(records, list):
            raise ValueError("A11_MANIFEST_PAYLOADS_INVALID")
        declared: set[str] = set()
        for record in records:
            relative = _normal(str(record["path"]))
            name = A11_ROOT + relative
            raw = archive.read(members[name])
            declared.add(name)
            if len(raw) != record["size"] or sha256_bytes(raw) != record["sha256"]:
                raise ValueError(f"A11_MANIFEST_MISMATCH:{name}")
        if declared | {manifest_name} != set(members):
            raise ValueError("A11_MANIFEST_COVERAGE_FAILURE")
        return {
            "status": "PASS",
            "zip_sha256": actual,
            "manifest_sha256": sha256_bytes(manifest_raw),
            "entries": len(members),
            "payloads": len(records),
            "crc_pass": True,
            "safe_paths": True,
            "no_symlinks": True,
            "no_casefold_duplicates": True,
            "manifest_coverage_pass": True,
            "concealed_path_allowlist": sorted(A11_DOTFILE_ALLOWLIST),
        }


def verify_b14(path: Path, expected_sha256: str = B14_SHA256) -> dict[str, object]:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ValueError(f"B14_SHA256_MISMATCH:{actual}")
    with zipfile.ZipFile(path) as archive:
        bad_crc = archive.testzip()
        if bad_crc is not None:
            raise ValueError(f"B14_CRC_FAILURE:{bad_crc}")
        members: dict[str, zipfile.ZipInfo] = {}
        folded: set[str] = set()
        for info in archive.infolist():
            name = _normal(info.filename.rstrip("/"))
            if name.casefold() in folded:
                raise ValueError(f"B14_CASEFOLD_DUPLICATE:{name}")
            folded.add(name.casefold())
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"B14_SYMLINK:{name}")
            members[name] = info
        manifest_name = "CDH_B_R10_001_REVIEW/REVIEW_MANIFEST.json"
        manifest_raw = archive.read(members[manifest_name])
        manifest = json.loads(manifest_raw)
        records = manifest.get("payloads")
        if not isinstance(records, list):
            raise ValueError("B14_MANIFEST_PAYLOADS_INVALID")
        declared: set[str] = set()
        for record in records:
            name = _normal(str(record["path"]))
            raw = archive.read(members[name])
            declared.add(name)
            if len(raw) != record["bytes"] or sha256_bytes(raw) != record["sha256"]:
                raise ValueError(f"B14_MANIFEST_MISMATCH:{name}")
        if declared | {manifest_name} != set(members):
            raise ValueError("B14_MANIFEST_COVERAGE_FAILURE")
        return {
            "status": "PASS",
            "zip_sha256": actual,
            "manifest_sha256": sha256_bytes(manifest_raw),
            "entries": len(members),
            "payloads": len(records),
            "crc_pass": True,
            "safe_paths": True,
            "no_symlinks": True,
            "no_casefold_duplicates": True,
            "manifest_coverage_pass": True,
        }
