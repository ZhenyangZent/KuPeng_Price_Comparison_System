from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath

B15_FILENAME = "CDH_B_R11_001_REVIEW.zip"
B15_SHA256 = "5a987c8a07a32f9b71d4fd995c9a8976b4c2fe8602a1d53c9e4c010d5c4d02be"
B15_MANIFEST_SHA256 = "aa52061728b9b922cb07e1fa6fff85384909dde463807c2e91a32611ebb4c335"
PACKAGE_ROOT = "CDH_B_R11_001_REVIEW"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(name: str) -> str:
    value = name.replace("\\", "/").rstrip("/")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_MEMBER:{name}")
    return pure.as_posix()


def verify_b15(path: Path) -> dict[str, object]:
    actual = sha256_file(path)
    if actual != B15_SHA256:
        raise ValueError(f"B15_SHA256_MISMATCH:{actual}")
    with zipfile.ZipFile(path) as archive:
        bad_crc = archive.testzip()
        if bad_crc is not None:
            raise ValueError(f"B15_CRC_FAILURE:{bad_crc}")
        members: dict[str, zipfile.ZipInfo] = {}
        folded: set[str] = set()
        for info in archive.infolist():
            name = normalize(info.filename)
            if name.casefold() in folded:
                raise ValueError(f"B15_CASEFOLD_DUPLICATE:{name}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"B15_SYMLINK:{name}")
            folded.add(name.casefold())
            members[name] = info
        manifest_name = PACKAGE_ROOT + "/REVIEW_MANIFEST.json"
        raw_manifest = archive.read(members[manifest_name])
        if sha256_bytes(raw_manifest) != B15_MANIFEST_SHA256:
            raise ValueError("B15_MANIFEST_SHA256_MISMATCH")
        manifest = json.loads(raw_manifest)
        records = manifest.get("payloads")
        if not isinstance(records, list):
            raise ValueError("B15_MANIFEST_INVALID")
        declared: set[str] = set()
        for record in records:
            name = normalize(record["path"])
            raw = archive.read(members[name])
            declared.add(name)
            if len(raw) != record["bytes"] or sha256_bytes(raw) != record["sha256"]:
                raise ValueError(f"B15_PAYLOAD_MISMATCH:{name}")
        if declared | {manifest_name} != set(members):
            raise ValueError("B15_MANIFEST_COVERAGE_FAILURE")
        return {
            "status": "PASS", "zip_sha256": actual, "manifest_sha256": B15_MANIFEST_SHA256,
            "entries": len(members), "payloads": len(records), "crc_pass": True,
            "missing": 0, "mismatch": 0, "undeclared": 0, "duplicates": 0,
            "safe_paths": True, "no_symlinks": True, "no_casefold_duplicates": True,
        }
